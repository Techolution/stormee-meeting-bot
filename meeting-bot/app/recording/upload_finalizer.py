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
from app.recording.models import RecordingContext

logger = logging.getLogger(__name__)


class UploadFinalizer:
    """Registers a completed recording and triggers downstream work."""

    def __init__(
        self,
        *,
        cw_client: CWUtilsClient,
        mail_client: MailClient | None = None,
    ) -> None:
        self._cw = cw_client
        self._mail = mail_client

    async def finalize(self, context: RecordingContext, outcome: UploadOutcome) -> bool:
        """Confirm the upload with CW and start follow-up processing.

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

        await self._request_artifact(context, uploaded.filename)
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
            )
        except Exception as error:  # noqa: BLE001 - follow-up work, not the recording
            logger.warning(
                "Could not request meeting artifact generation",
                extra={"meeting_id": context.meeting_id, "reason": str(error)},
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
