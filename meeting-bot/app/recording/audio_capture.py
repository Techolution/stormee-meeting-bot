"""Audio capture: from the page callback to an ordered chunk stream.

The browser's ``MediaRecorder`` calls into Python once per timeslice. This
module is the receiving end. It has one hard constraint: **it must never
raise**. An exception here propagates back into page JavaScript and stops the
recorder, silently ending the recording mid-meeting.

So every failure is caught, counted and logged, and capture continues.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone

from app.meeting_platform.base import ChunkSink
from app.recording.models import AudioChunk, RecordingStats

logger = logging.getLogger(__name__)

ChunkHandler = Callable[[AudioChunk], Awaitable[None]]


class AudioCapture(ChunkSink):
    """Turns raw page payloads into :class:`AudioChunk` objects and forwards them.

    Deliberately thin: it parses, counts, and hands off. Deciding what happens
    to a chunk belongs to :class:`~app.recording.recorder.Recorder`.
    """

    def __init__(
        self,
        *,
        meeting_id: str,
        handler: ChunkHandler,
        project_id: str | None = None,
        stats: RecordingStats | None = None,
    ) -> None:
        self._meeting_id = meeting_id
        self._handler = handler
        self._project_id = project_id
        self._stats = stats or RecordingStats()
        self._active = False
        self._malformed = 0

    @property
    def stats(self) -> RecordingStats:
        return self._stats

    @property
    def is_active(self) -> bool:
        return self._active

    @property
    def malformed_count(self) -> int:
        """Payloads discarded because they could not be parsed."""
        return self._malformed

    def start(self) -> None:
        """Begin accepting chunks."""
        self._active = True
        self._stats.started_at = datetime.now(timezone.utc)
        logger.debug("Audio capture armed", extra={"meeting_id": self._meeting_id})

    def stop(self) -> None:
        """Stop accepting chunks.

        Chunks that arrive after this are ignored, which matters because the
        page callback stays bound for the life of the page and a stale
        recorder can emit one final chunk after the stop call returns.
        """
        self._active = False
        self._stats.stopped_at = datetime.now(timezone.utc)
        logger.debug(
            "Audio capture disarmed",
            extra={
                "meeting_id": self._meeting_id,
                "chunks_captured": self._stats.chunks_captured,
                "bytes_captured": self._stats.bytes_captured,
            },
        )

    async def on_chunk(self, payload: dict) -> None:
        """Receive one chunk from the page.

        Called by: page JavaScript, via the ``sendAudioChunkToPython``
        binding installed by ``GoogleMeetPlatform.bind_chunk_sink``. There is no
        Python caller — see docs/ENTRY_POINTS.md §2.

        Never raises — see the module docstring.
        """
        if not self._active:
            logger.debug(
                "Ignoring chunk received while capture is inactive",
                extra={"meeting_id": self._meeting_id, "chunk_id": payload.get("chunkId")},
            )
            return

        try:
            chunk = AudioChunk.from_page_payload(payload, project_id=self._project_id)
        except (ValueError, TypeError) as error:
            self._malformed += 1
            logger.error(
                "Discarded malformed audio chunk",
                extra={
                    "meeting_id": self._meeting_id,
                    "reason": str(error),
                    "malformed_total": self._malformed,
                },
            )
            return

        self._stats.chunks_captured += 1
        self._stats.bytes_captured += chunk.size_bytes

        logger.debug(
            "Audio chunk captured",
            extra={
                "meeting_id": chunk.meeting_id,
                "chunk_id": chunk.chunk_id,
                "sequence": chunk.sequence,
                "size_bytes": chunk.size_bytes,
            },
        )

        try:
            await self._handler(chunk)
        except Exception as error:
            logger.error(
                "Chunk handler failed; capture continues",
                exc_info=error,
                extra={"meeting_id": chunk.meeting_id, "chunk_id": chunk.chunk_id},
            )
