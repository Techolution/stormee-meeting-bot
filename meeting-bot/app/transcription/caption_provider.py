"""Transcription from in-meeting captions.

Polls the platform's caption area and hands each snapshot to
:class:`~app.transcription.caption_aggregator.CaptionAggregator`, which turns
the overlapping readings into utterances.

This provider owns only the loop: timing, error tolerance, and lifecycle. The
reconstruction rules live in the aggregator, and reading the DOM lives in the
platform. Each of the three can be changed or tested without the others.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from app.core.exceptions import TranscriptionError
from app.core.tasks import TaskSupervisor
from app.meeting_platform.base import MeetingPlatform
from app.transcription.base import SegmentSink, TranscriptionProvider
from app.transcription.caption_aggregator import CaptionAggregator
from app.transcription.models import TranscriptionStats, TranscriptionStatus, TranscriptSegment

logger = logging.getLogger(__name__)

_POLL_TASK = "caption_poll"

#: Consecutive poll failures tolerated before the provider gives up. A caption
#: read fails transiently all the time — mid-navigation, mid-render — so a
#: single failure means nothing, but a sustained run means the page is gone.
_MAX_CONSECUTIVE_ERRORS = 30


class CaptionTranscriptionProvider(TranscriptionProvider):
    """Produces a transcript by polling the meeting's caption area."""

    name = "caption"

    def __init__(
        self,
        *,
        platform: MeetingPlatform,
        meeting_id: str,
        poll_interval_seconds: float = 1.0,
    ) -> None:
        self._platform = platform
        self._meeting_id = meeting_id
        self._poll_interval = poll_interval_seconds

        self._aggregator = CaptionAggregator()
        self._stats = TranscriptionStats()
        self._status = TranscriptionStatus.IDLE
        self._tasks = TaskSupervisor(f"captions:{meeting_id}")
        self._sink: SegmentSink | None = None

    # ------------------------------------------------------------------
    # State
    # ------------------------------------------------------------------

    @property
    def status(self) -> TranscriptionStatus:
        return self._status

    @property
    def stats(self) -> TranscriptionStats:
        self._stats.duplicates_suppressed = self._aggregator.suppressed_count
        return self._stats

    def segments(self) -> list[TranscriptSegment]:
        return self._aggregator.transcript()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self, sink: SegmentSink) -> None:
        """Switch captions on and begin polling.

        Raises:
            TranscriptionError: If the platform cannot produce captions.
        """
        if self._status.is_active:
            logger.debug("Caption transcription already running", extra={"meeting_id": self._meeting_id})
            return

        if not self._platform.capabilities.supports_captions:
            raise TranscriptionError(
                "this meeting platform does not support captions",
                details={"meeting_id": self._meeting_id},
            )

        self._status = TranscriptionStatus.STARTING
        self._sink = sink
        self._aggregator.reset()
        self._stats = TranscriptionStats(started_at=datetime.now(timezone.utc))

        if not await self._platform.enable_captions():
            # Captions may already be on, or the toggle may have moved. Polling
            # will find out; failing here would abandon a recoverable case.
            logger.warning(
                "Could not confirm captions were enabled; polling anyway",
                extra={"meeting_id": self._meeting_id},
            )

        # Give the caption area a moment to mount before the first read.
        await asyncio.sleep(1.0)

        self._tasks.spawn(_POLL_TASK, self._poll_loop())
        self._status = TranscriptionStatus.RUNNING
        logger.info(
            "Caption transcription started",
            extra={"meeting_id": self._meeting_id, "poll_interval": self._poll_interval},
        )

    async def stop(self) -> list[TranscriptSegment]:
        """Stop polling, close any in-progress utterance, return the transcript."""
        if self._status is TranscriptionStatus.IDLE:
            return self.segments()

        self._status = TranscriptionStatus.STOPPING
        await self._tasks.cancel_all()

        for segment in self._aggregator.flush():
            await self._emit(segment)

        self._status = TranscriptionStatus.STOPPED
        self._stats.stopped_at = datetime.now(timezone.utc)

        transcript = self.segments()
        logger.info(
            "Caption transcription stopped",
            extra={
                "meeting_id": self._meeting_id,
                "segment_count": len(transcript),
                **self.stats.as_dict(),
            },
        )
        return transcript

    # ------------------------------------------------------------------
    # Polling
    # ------------------------------------------------------------------

    async def _poll_loop(self) -> None:
        """Read the caption area on an interval until cancelled.

        Called by: nothing. Spawned as a background task by :meth:`start` and
        cancelled by :meth:`stop` — see docs/ENTRY_POINTS.md §5.
        """
        consecutive_errors = 0

        while True:
            try:
                snapshot = await self._platform.get_captions()
            except asyncio.CancelledError:
                raise
            except Exception as error:  # noqa: BLE001 - transient reads are normal
                consecutive_errors += 1
                self._stats.poll_errors += 1
                logger.debug(
                    "Caption poll failed",
                    extra={
                        "meeting_id": self._meeting_id,
                        "consecutive_errors": consecutive_errors,
                        "reason": str(error),
                    },
                )
                if consecutive_errors >= _MAX_CONSECUTIVE_ERRORS:
                    self._status = TranscriptionStatus.FAILED
                    logger.error(
                        "Abandoning caption transcription after repeated failures",
                        extra={"meeting_id": self._meeting_id, "errors": consecutive_errors},
                    )
                    return
                # Back off while the page recovers.
                await asyncio.sleep(self._poll_interval * 2)
                continue

            consecutive_errors = 0

            for segment in self._aggregator.ingest(snapshot):
                await self._emit(segment)

            await asyncio.sleep(self._poll_interval)

    async def _emit(self, segment: TranscriptSegment) -> None:
        """Publish one finished segment."""
        self._stats.segments_emitted += 1

        if self._sink is None:
            return
        try:
            await self._sink(segment)
        except Exception as error:
            logger.error(
                "Transcript sink failed",
                exc_info=error,
                extra={"meeting_id": self._meeting_id},
            )
