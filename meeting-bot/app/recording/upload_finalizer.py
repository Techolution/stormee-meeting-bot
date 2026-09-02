"""Post-upload processing.

What happens *after* a recording lands — register it with CW, kick off artifact
generation, notify the user — is a separate concern from getting the bytes
there. Keeping it out of :mod:`app.recording.chunk_uploader` means the uploader
stays about transport and this stays about business follow-up.

Everything here is best-effort. The recording is already safe in storage by the
time this runs; a failed notification must not be reported as a failed meeting.
"""

from __future__ import annotations

import logging

from app.clients.cw_utils import CWUtilsClient, UploadedFile
from app.clients.mail import MailClient
from app.recording.chunk_uploader import UploadOutcome
from app.recording.highlights_manager import HighlightsManager
from app.recording.models import RecordingContext, RecordingStats

logger = logging.getLogger(__name__)


class UploadFinalizer:
    """Registers a completed recording and triggers downstream work.

    Supports both single-upload and incremental highlight generation for
    long-running meetings.
    """

    def __init__(
        self,
        *,
        cw_client: CWUtilsClient,
        mail_client: MailClient | None = None,
        highlights_manager: HighlightsManager | None = None,
    ) -> None:
        self._cw = cw_client
        self._mail = mail_client
        self._highlights = highlights_manager

    async def finalize(
        self,
        context: RecordingContext,
        outcome: UploadOutcome,
        stats: RecordingStats | None = None,
        is_final_segment: bool = True,
        segment_number: int = 1,
        generate_incremental_highlights: bool = False,
    ) -> bool:
        """Confirm the upload with CW and start follow-up processing.

        Supports both incremental segment uploads and final meeting uploads.
        For segments, generates highlights for that portion. For final upload,
        generates highlights for remaining audio after all segments.

        Args:
            context: Recording context with user and project information.
            outcome: The upload outcome details.
            stats: Optional recording stats for incremental highlights.
            is_final_segment: True if this is the final upload (meeting ended),
                False if this is an incremental segment upload.
            segment_number: Which segment this is (1, 2, 3, ...) for labeling.
            generate_incremental_highlights: If True, request highlights for this segment.

        Returns:
            True if CW accepted the confirmation. False when the step was
            skipped or failed — both are logged with the reason.
        """
        skip_reason = self._skip_reason(context, outcome)
        if skip_reason:
            logger.info(
                "Skipping upload finalization",
                extra={"meeting_id": context.meeting_id, "reason": skip_reason},
            )
            # A meeting that ends on a segment boundary leaves a final segment
            # with nothing in it. There is no file to register, but the earlier
            # parts did upload and the recording *is* finished, so the person
            # waiting to hear that still needs telling.
            if is_final_segment and segment_number > 1 and context.project_id:
                await self._notify_user(context)
            return False

        assert outcome.public_url is not None and context.project_id is not None

        uploaded = UploadedFile(
            filename=outcome.public_url.rsplit("/", 1)[-1],
            url=outcome.public_url,
        )

        try:
            result = await self._cw.confirm_upload(
                project_id=context.project_id,
                files=[uploaded],
                is_ai=False,
                display_name=context.meeting_title,
                user_name=context.user_name,
                user_email=context.user_email,
                auto_ingest=True,
            )
        except Exception as error:
            logger.error(
                "Failed to confirm the recording upload with CW",
                exc_info=error,
                extra={"meeting_id": context.meeting_id, "project_id": context.project_id},
            )
            return False

        if not result.get("uploaded_files"):
            logger.warning(
                "CW accepted the confirmation but reported no files",
                extra={"meeting_id": context.meeting_id},
            )
            return False

        logger.info(
            "Recording registered with CW",
            extra={"meeting_id": context.meeting_id, "object_name": uploaded.filename},
        )

        # Every upload that lands gets exactly one artifact request, and the
        # final segment is not a special case: it is the last part of the
        # meeting, not a summary of the whole thing. The audio it points at
        # covers only its own segment either way.
        #
        # The manager adds part numbering and remembers which ranges have been
        # asked for, which is what makes several artifacts from one meeting
        # tellable apart. Without one, a plain request is all that is on offer.
        if generate_incremental_highlights and self._highlights is not None and stats is not None:
            await self._request_incremental_highlights(
                context, uploaded.filename, stats, segment_number, is_final_segment
            )
        else:
            await self._request_artifact(context, uploaded.filename)

        if is_final_segment:
            await self._notify_user(context)
        return True

    @staticmethod
    def _skip_reason(context: RecordingContext, outcome: UploadOutcome) -> str | None:
        if not outcome.complete:
            return "upload did not complete"
        if not outcome.public_url:
            return "no public URL for the uploaded object"
        if not context.project_id:
            return "no project id on the recording context"
        if outcome.uploaded_bytes <= 0:
            return "nothing was uploaded"
        return None

    async def _request_artifact(self, context: RecordingContext, filename: str) -> None:
        """Ask CW to derive a meeting artifact from the recording."""
        assert context.project_id is not None
        try:
            await self._cw.generate_meeting_artifact(
                audio_name=filename,
                project_id=context.project_id,
                display_name=context.meeting_title or context.meeting_id,
                user_email=context.user_email,
                user_name=context.user_name,
                mode_ids=context.mode_ids,
            )
        except Exception as error:  # noqa: BLE001 - follow-up work, not the recording
            logger.warning(
                "Could not request meeting artifact generation",
                extra={"meeting_id": context.meeting_id, "reason": str(error)},
            )

    async def _request_incremental_highlights(
        self,
        context: RecordingContext,
        filename: str,
        stats: RecordingStats,
        segment_number: int = 1,
        is_final: bool = False,
    ) -> None:
        """Request highlights for an incremental segment of a recording.

        Args:
            context: Recording context with user and project information.
            filename: Name of the audio file in storage.
            stats: Recording statistics including duration.
            segment_number: Which segment this is (1, 2, 3, ...) for labeling.
            is_final: True when this segment ends the meeting, so CW can tell
                the closing segment from the ones before it.
        """
        if self._highlights is None:
            logger.warning(
                "Highlights manager not available; skipping incremental highlights",
                extra={"meeting_id": context.meeting_id},
            )
            return

        try:
            segment = await self._highlights.generate_incremental_highlights(
                context=context,
                stats=stats,
                audio_filename=filename,
                segment_number=segment_number,
                is_final=is_final,
            )
            if segment is None:
                logger.debug(
                    "Incremental highlights skipped due to duration threshold",
                    extra={"meeting_id": context.meeting_id},
                )
            else:
                logger.info(
                    "Incremental highlights generated",
                    extra={"segment_id": segment.segment_id},
                )
        except Exception as error:  # noqa: BLE001 - follow-up work, not the recording
            logger.warning(
                "Could not request incremental highlights",
                exc_info=error,
                extra={"meeting_id": context.meeting_id},
            )

    async def _notify_user(self, context: RecordingContext) -> None:
        """Email the requesting user that their recording is available."""
        if self._mail is None or not self._mail.enabled or not context.user_email:
            return

        assert context.project_id is not None
        await self._mail.send_meeting_file_uploaded(
            user_name=context.user_name,
            user_email=context.user_email,
            project_name=context.project_name or context.project_id,
            project_url=self._cw.project_url(context.project_id),
            meeting_title=context.meeting_title or context.meeting_id,
            file_type="recording",
        )
