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
    ) -> None:
        self._platform = platform
        self._uploader = uploader
        self._context = context
        self._finalizer = finalizer
        self._chunk_duration_ms = chunk_duration_ms
        self._grace_period = finalize_grace_period_seconds

        self._stats = RecordingStats()
        self._status = RecordingStatus.IDLE
        self._capture = AudioCapture(
            meeting_id=context.meeting_id,
            handler=self._on_chunk,
            project_id=context.project_id,
            stats=self._stats,
        )
        self._lock = asyncio.Lock()

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
            await self._finalizer.finalize(self._context, outcome)

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

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _on_chunk(self, chunk: AudioChunk) -> None:
        """Hand a captured chunk to the uploader."""
        await self._uploader.upload(chunk)
