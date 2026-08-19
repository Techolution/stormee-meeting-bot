"""Recording orchestration.

The Recorder is the seam between the meeting and the audio pipeline. It owns
one recording's lifecycle and coordinates three collaborators, each of which
does one job:

  :class:`~app.recording.audio_capture.AudioCapture`   receives chunks from the page
  :class:`~app.recording.chunk_uploader.ChunkUploader` persists them
  :class:`~app.recording.upload_finalizer.UploadFinalizer` handles what comes after

It deliberately does *not* know how audio reaches storage, what a resumable
block is, or that a finished recording produces an email. That was the shape of
the code this replaces, and it is why a change to upload behaviour used to
require editing meeting logic.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from app.core.exceptions import RecordingAlreadyActiveError, RecordingNotActiveError
from app.meeting_platform.base import MeetingPlatform
from app.recording.audio_capture import AudioCapture
from app.recording.chunk_uploader import ChunkUploader, UploadOutcome
from app.recording.models import AudioChunk, RecordingContext, RecordingStats, RecordingStatus
from app.recording.upload_finalizer import UploadFinalizer

logger = logging.getLogger(__name__)


class Recorder:
    """Runs one meeting's audio recording."""

    def __init__(
        self,
        *,
        platform: MeetingPlatform,
        uploader: ChunkUploader,
        context: RecordingContext,
        finalizer: UploadFinalizer | None = None,
        chunk_duration_ms: int = 5_000,
        finalize_grace_period_seconds: float = 2.0,
        max_duration_seconds: int | None = None,
        generate_incremental_highlights: bool = False,
    ) -> None:
        self._platform = platform
        self._uploader = uploader
        self._context = context
        self._finalizer = finalizer
        self._chunk_duration_ms = chunk_duration_ms
        self._grace_period = finalize_grace_period_seconds
        self._max_duration_seconds = max_duration_seconds
        self._generate_incremental_highlights = generate_incremental_highlights

        self._stats = RecordingStats()
        self._status = RecordingStatus.IDLE
        self._capture = AudioCapture(
            meeting_id=context.meeting_id,
            handler=self._on_chunk,
            project_id=context.project_id,
            stats=self._stats,
        )
        self._lock = asyncio.Lock()
        
        # For incremental segment uploads: track which segment we're on and when last upload occurred
        self._segment_number = 1  # Current segment number (1-indexed)
        self._last_segment_upload_duration = 0.0  # Duration (in seconds) at which last segment was uploaded
        self._segment_upload_in_progress = False  # Guard flag to prevent concurrent segment uploads

    # ------------------------------------------------------------------
    # State
    # ------------------------------------------------------------------

    @property
    def status(self) -> RecordingStatus:
        return self._status

    @property
    def is_active(self) -> bool:
        return self._status.is_active

    @property
    def stats(self) -> RecordingStats:
        return self._stats

    @property
    def transport(self) -> str:
        return self._uploader.transport

    @property
    def pending_chunks(self) -> int:
        """Chunks captured but not yet persisted."""
        return self._uploader.pending_count()

    @property
    def context(self) -> RecordingContext:
        return self._context

    def status_detail(self) -> dict:
        return {
            "status": self._status.value,
            "transport": self._uploader.transport,
            "pending_chunks": self._uploader.pending_count(),
            **self._stats.as_dict(),
        }

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Begin recording.

        Order matters. The chunk sink is bound and the uploader initialised
        *before* the page recorder starts, so the first chunk has somewhere to
        go — otherwise the opening seconds of a meeting are lost.

        Raises:
            RecordingAlreadyActiveError: If a recording is already running.
            RecordingError: If the page could not start capturing.
        """
        async with self._lock:
            if self._status.is_active:
                raise RecordingAlreadyActiveError(
                    f"recording already active for meeting {self._context.meeting_id!r}"
                )

            self._status = RecordingStatus.STARTING
            logger.info(
                "Starting recording",
                extra={
                    "meeting_id": self._context.meeting_id,
                    "transport": self._uploader.transport,
                    "chunk_duration_ms": self._chunk_duration_ms,
                },
            )

            try:
                await self._platform.bind_chunk_sink(self._capture)
                await self._uploader.start(self._context)
                self._capture.start()
                await self._platform.start_recording(
                    self._context.meeting_id,
                    chunk_duration_ms=self._chunk_duration_ms,
                )
            except Exception:
                self._status = RecordingStatus.FAILED
                self._capture.stop()
                raise

            self._status = RecordingStatus.RECORDING
            self._stats.started_at = datetime.now(timezone.utc)

    async def stop(self) -> UploadOutcome:
        """Stop recording, flush everything, and run post-upload processing.

        Raises:
            RecordingNotActiveError: If no recording is running.
        """
        async with self._lock:
            if not self._status.is_active:
                raise RecordingNotActiveError(
                    f"no active recording for meeting {self._context.meeting_id!r}"
                )

            self._status = RecordingStatus.STOPPING
            logger.info("Stopping recording", extra={"meeting_id": self._context.meeting_id})

            await self._platform.stop_recording()

            # The recorder's final chunk is emitted asynchronously after stop()
            # returns. Closing the pipeline immediately truncates the recording.
            await asyncio.sleep(self._grace_period)
            self._capture.stop()

            outcome = await self._uploader.finalize()
            self._stats.stopped_at = datetime.now(timezone.utc)
            self._status = RecordingStatus.STOPPED

            logger.info(
                "Recording stopped",
                extra={
                    "meeting_id": self._context.meeting_id,
                    "complete": outcome.complete,
                    **self._stats.as_dict(),
                },
            )

        # Outside the lock: follow-up work talks to CW and can be slow, and
        # nothing else needs the recorder by this point.
        if self._finalizer is not None:
            # Finalize remaining audio as the final segment
            # This handles: 1) recordings that never reached max_duration_seconds,
            # or 2) the remaining audio after the last auto-uploaded segment
            await self._finalizer.finalize(
                context=self._context,
                outcome=outcome,
                stats=self._stats,
                is_final_segment=True,  # This is the end of recording
                segment_number=self._segment_number,  # Current segment (last one)
                generate_incremental_highlights=self._generate_incremental_highlights,
            )

        return outcome

    async def abort(self) -> None:
        """Tear down without finalizing. For shutdown paths where the meeting is gone."""
        if self._status is RecordingStatus.IDLE:
            return
        self._capture.stop()
        try:
            await self._platform.stop_recording()
        except Exception as error:  # noqa: BLE001 - already shutting down
            logger.debug("Recorder stop failed during abort", extra={"reason": str(error)})
        self._status = RecordingStatus.FAILED
        logger.warning("Recording aborted", extra={"meeting_id": self._context.meeting_id})

    async def flush_pending(self) -> int:
        """Retry buffered chunks. Wired to the websocket reconnect hook."""
        return await self._uploader.flush_buffered()

    async def _trigger_segment_upload(self) -> None:
        """Finalize current segment, upload it, generate highlights, and prepare for next segment.
        
        This is called when the max_duration_seconds threshold is reached during recording.
        The segment is uploaded with highlights, and a new uploader is created for the
        next segment. Recording continues uninterrupted.
        """
        # Finalize the current segment upload
        outcome = await self._uploader.finalize()
        
        logger.info(
            "Segment upload finalized",
            extra={
                "meeting_id": self._context.meeting_id,
                "segment_number": self._segment_number,
                "complete": outcome.complete,
                "bytes": outcome.uploaded_bytes,
            },
        )
        
        # Request highlights/artifacts for this segment (not final)
        if self._finalizer is not None:
            await self._finalizer.finalize(
                context=self._context,
                outcome=outcome,
                stats=self._stats,
                is_final_segment=False,
                segment_number=self._segment_number,
                generate_incremental_highlights=self._generate_incremental_highlights,
            )
        
        # Update segment tracking
        self._last_segment_upload_duration = self._stats.duration_seconds
        self._segment_number += 1
        
        logger.info(
            "Preparing next segment for recording",
            extra={
                "meeting_id": self._context.meeting_id,
                "next_segment_number": self._segment_number,
            },
        )
        
        # Re-initialize uploader for the next segment
        # For direct uploads, this creates a new resumable URL
        # For streaming, this updates context and lets audio service handle segmentation
        await self._uploader.reinitialize(self._context)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _on_chunk(self, chunk: AudioChunk) -> None:
        """Hand a captured chunk to the uploader.
        
        Also monitors duration for incremental segment uploads. When the
        max_duration_seconds threshold is reached, automatically finalizes
        the current segment, generates highlights, and creates a new uploader
        for the next segment.
        """
        await self._uploader.upload(chunk)
        
        # Check if we've reached the auto-upload duration threshold
        # Use guard flag to prevent concurrent segment uploads
        if (
            not self._segment_upload_in_progress
            and self._max_duration_seconds
            and self._stats.duration_seconds >= (self._last_segment_upload_duration + self._max_duration_seconds)
        ):
            # Trigger auto-upload of current segment
            self._segment_upload_in_progress = True
            logger.info(
                "Recording segment duration threshold reached; auto-uploading segment",
                extra={
                    "meeting_id": self._context.meeting_id,
                    "segment_number": self._segment_number,
                    "duration_seconds": self._stats.duration_seconds,
                },
            )
            try:
                await self._trigger_segment_upload()
            finally:
                self._segment_upload_in_progress = False
