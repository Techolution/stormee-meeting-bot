"""Chunk ordering.

Audio chunks must be concatenated in the order the recorder produced them. A
WebM/Opus stream written out of order is not merely scrambled — it is
unplayable, because the container's structure depends on sequence.

Chunks do not always arrive in order. A reconnect drains a buffer while fresh
chunks are still arriving, and the two interleave. This class absorbs that: it
holds out-of-order arrivals until the gap ahead of them fills, then releases
the longest contiguous run available.

It is pure bookkeeping — no I/O — which makes the ordering rules directly
testable.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from app.recording.models import AudioChunk

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class SequencerStats:
    """What the sequencer has seen."""

    accepted: int = 0
    duplicates: int = 0
    released: int = 0
    out_of_order: int = 0
    max_gap: int = 0


@dataclass(slots=True)
class ChunkSequencer:
    """Releases chunks in unbroken sequence order.

    Args:
        meeting_id: Correlation id for logging.
        first_sequence: Ordinal the stream starts at. The recorder counts from
            zero.
    """

    meeting_id: str
    first_sequence: int = 0

    _next_expected: int = field(init=False, default=0)
    _pending: dict[int, AudioChunk] = field(init=False, default_factory=dict)
    _seen: set[int] = field(init=False, default_factory=set)
    _stats: SequencerStats = field(init=False, default_factory=SequencerStats)

    def __post_init__(self) -> None:
        self._next_expected = self.first_sequence

    # ------------------------------------------------------------------
    # State
    # ------------------------------------------------------------------

    @property
    def next_expected(self) -> int:
        """The sequence number that would unblock the pending chunks."""
        return self._next_expected

    @property
    def pending_count(self) -> int:
        """Chunks held back waiting for an earlier one."""
        return len(self._pending)

    @property
    def stats(self) -> SequencerStats:
        return self._stats

    @property
    def has_gap(self) -> bool:
        """True when chunks are waiting on one that has not arrived."""
        return bool(self._pending)

    # ------------------------------------------------------------------
    # Operations
    # ------------------------------------------------------------------

    def accept(self, chunk: AudioChunk) -> bool:
        """Take a chunk into the sequencer.

        Returns:
            True if it was accepted, False if it was a duplicate. Duplicates
            occur legitimately — a chunk buffered during a disconnect can be
            re-sent after the reconnect — so they are dropped, not treated as
            errors.
        """
        sequence = chunk.sequence

        if sequence in self._seen or sequence in self._pending:
            self._stats.duplicates += 1
            logger.debug(
                "Ignoring duplicate chunk",
                extra={"meeting_id": self.meeting_id, "sequence": sequence},
            )
            return False

        if sequence < self._next_expected:
            # Already released; arriving now means a stale re-send.
            self._stats.duplicates += 1
            logger.debug(
                "Ignoring chunk already released",
                extra={"meeting_id": self.meeting_id, "sequence": sequence},
            )
            return False

        self._pending[sequence] = chunk
        self._stats.accepted += 1

        if sequence != self._next_expected:
            self._stats.out_of_order += 1
            gap = sequence - self._next_expected
            self._stats.max_gap = max(self._stats.max_gap, gap)
            logger.debug(
                "Chunk arrived out of order",
                extra={
                    "meeting_id": self.meeting_id,
                    "sequence": sequence,
                    "expected": self._next_expected,
                    "gap": gap,
                },
            )

        return True

    def release_ready(self) -> list[AudioChunk]:
        """Return the longest contiguous run starting at ``next_expected``.

        Stops at the first gap. Returns an empty list when the next expected
        chunk has not arrived.
        """
        ready: list[AudioChunk] = []

        while self._next_expected in self._pending:
            chunk = self._pending.pop(self._next_expected)
            self._seen.add(self._next_expected)
            ready.append(chunk)
            self._next_expected += 1

        if ready:
            self._stats.released += len(ready)
            logger.debug(
                "Released sequential chunks",
                extra={
                    "meeting_id": self.meeting_id,
                    "count": len(ready),
                    "from_sequence": ready[0].sequence,
                    "to_sequence": ready[-1].sequence,
                    "still_pending": len(self._pending),
                },
            )

        return ready

    def release_all(self) -> list[AudioChunk]:
        """Release everything held, in sequence order, accepting gaps.

        Called only at finalization. By then no further chunks are coming, so
        holding audio back to preserve a gap that will never fill would simply
        discard it. The gap is logged because it means the recording is
        incomplete.
        """
        if not self._pending:
            return []

        ordered = [self._pending[key] for key in sorted(self._pending)]
        expected_run = ordered[-1].sequence - self._next_expected + 1

        if len(ordered) != expected_run:
            logger.warning(
                "Finalizing with missing chunks; recording will have a gap",
                extra={
                    "meeting_id": self.meeting_id,
                    "released": len(ordered),
                    "expected_range": expected_run,
                    "next_expected": self._next_expected,
                },
            )

        for chunk in ordered:
            self._seen.add(chunk.sequence)

        self._next_expected = ordered[-1].sequence + 1
        self._pending.clear()
        self._stats.released += len(ordered)
        return ordered

    def requeue(self, chunks: list[AudioChunk]) -> None:
        """Put a released run back after a failed upload.

        Rewinds ``next_expected`` so the same bytes are retried at the same
        offset — the resumable protocol will not accept them anywhere else.
        """
        if not chunks:
            return

        for chunk in chunks:
            self._pending[chunk.sequence] = chunk
            self._seen.discard(chunk.sequence)

        self._next_expected = min(self._next_expected, chunks[0].sequence)
        self._stats.released -= len(chunks)

        logger.warning(
            "Requeued chunks after a failed upload",
            extra={
                "meeting_id": self.meeting_id,
                "count": len(chunks),
                "next_expected": self._next_expected,
            },
        )
