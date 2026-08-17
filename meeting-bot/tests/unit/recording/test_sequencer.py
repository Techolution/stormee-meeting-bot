"""Tests for chunk ordering.

Ordering failures corrupt a recording rather than losing it, which makes them
expensive to detect after the fact. These tests pin the rules down.
"""

from __future__ import annotations

from app.recording.sequencer import ChunkSequencer
from tests.conftest import make_chunk


def test_in_order_chunks_are_released_immediately() -> None:
    sequencer = ChunkSequencer(meeting_id="m")

    for sequence in range(3):
        sequencer.accept(make_chunk(sequence))
        assert [chunk.sequence for chunk in sequencer.release_ready()] == [sequence]

    assert sequencer.pending_count == 0


def test_out_of_order_chunk_is_held_until_the_gap_fills() -> None:
    """A chunk that arrives early must not be written before its predecessor."""
    sequencer = ChunkSequencer(meeting_id="m")

    sequencer.accept(make_chunk(1))
    assert sequencer.release_ready() == []
    assert sequencer.has_gap

    sequencer.accept(make_chunk(0))
    assert [chunk.sequence for chunk in sequencer.release_ready()] == [0, 1]
    assert not sequencer.has_gap


def test_release_stops_at_the_first_gap() -> None:
    """Chunks beyond a gap stay held, however many have arrived."""
    sequencer = ChunkSequencer(meeting_id="m")

    for sequence in (0, 1, 3, 4):
        sequencer.accept(make_chunk(sequence))

    assert [chunk.sequence for chunk in sequencer.release_ready()] == [0, 1]
    assert sequencer.next_expected == 2
    assert sequencer.pending_count == 2


def test_duplicates_are_dropped_not_double_written() -> None:
    """A chunk re-sent after a reconnect must not appear twice in the object."""
    sequencer = ChunkSequencer(meeting_id="m")

    assert sequencer.accept(make_chunk(0)) is True
    assert sequencer.accept(make_chunk(0)) is False

    sequencer.release_ready()

    # A stale re-send arriving after release is also refused.
    assert sequencer.accept(make_chunk(0)) is False
    assert sequencer.release_ready() == []
    assert sequencer.stats.duplicates == 2


def test_release_all_emits_across_a_permanent_gap() -> None:
    """At finalization, held audio is written even though a chunk never arrived."""
    sequencer = ChunkSequencer(meeting_id="m")

    sequencer.accept(make_chunk(0))
    sequencer.release_ready()
    sequencer.accept(make_chunk(2))
    sequencer.accept(make_chunk(3))

    released = sequencer.release_all()

    assert [chunk.sequence for chunk in released] == [2, 3]
    assert sequencer.pending_count == 0


def test_requeue_rewinds_so_the_same_bytes_retry_at_the_same_offset() -> None:
    """A failed upload must be retried identically; the resumable protocol demands it."""
    sequencer = ChunkSequencer(meeting_id="m")

    for sequence in (0, 1):
        sequencer.accept(make_chunk(sequence))
    released = sequencer.release_ready()
    assert sequencer.next_expected == 2

    sequencer.requeue(released)

    assert sequencer.next_expected == 0
    assert [chunk.sequence for chunk in sequencer.release_ready()] == [0, 1]


def test_interleaved_reconnect_drain_reassembles_correctly() -> None:
    """The real-world case: a buffer drains while live chunks are still arriving."""
    sequencer = ChunkSequencer(meeting_id="m")
    released: list[int] = []

    # Live chunks 3 and 4 arrive first; buffered 0-2 follow out of order.
    for sequence in (3, 4, 1, 0, 2):
        sequencer.accept(make_chunk(sequence))
        released.extend(chunk.sequence for chunk in sequencer.release_ready())

    assert released == [0, 1, 2, 3, 4]
