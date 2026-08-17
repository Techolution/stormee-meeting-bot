"""Tests for the bounded audio buffer.

The bound is the point: an unbounded buffer during a network outage takes the
pod down and loses the whole meeting instead of part of it.
"""

from __future__ import annotations

from app.recording.audio_buffer import AudioBuffer
from tests.conftest import make_chunk


def test_chunks_come_back_in_order() -> None:
    buffer = AudioBuffer(max_chunks=10, max_memory_bytes=1_000_000)

    for sequence in range(3):
        buffer.append(make_chunk(sequence))

    assert [chunk.sequence for chunk in buffer.drain()] == [0, 1, 2]
    assert buffer.is_empty


def test_chunk_limit_drops_the_oldest_audio() -> None:
    """At capacity the head goes, because the tail is what is still arriving."""
    buffer = AudioBuffer(max_chunks=3, max_memory_bytes=1_000_000)

    for sequence in range(5):
        buffer.append(make_chunk(sequence))

    assert [chunk.sequence for chunk in buffer.drain()] == [2, 3, 4]
    assert buffer.dropped_count == 2


def test_memory_limit_is_enforced_independently_of_chunk_count() -> None:
    """A few large chunks must trip the byte limit before the count limit."""
    buffer = AudioBuffer(max_chunks=100, max_memory_bytes=3_000)

    for sequence in range(5):
        buffer.append(make_chunk(sequence, size=1_000))

    assert buffer.size_bytes <= 3_000
    assert len(buffer) == 3
    assert buffer.dropped_count == 2


def test_append_reports_whether_audio_was_lost() -> None:
    buffer = AudioBuffer(max_chunks=2, max_memory_bytes=1_000_000)

    assert buffer.append(make_chunk(0)) is True
    assert buffer.append(make_chunk(1)) is True
    assert buffer.append(make_chunk(2)) is False


def test_restore_puts_chunks_back_at_the_head_in_order() -> None:
    """A drain interrupted mid-flight must not scatter the sequence."""
    buffer = AudioBuffer(max_chunks=10, max_memory_bytes=1_000_000)
    for sequence in range(4):
        buffer.append(make_chunk(sequence))

    drained = buffer.drain()
    buffer.append(make_chunk(4))
    buffer.restore(drained[2:])

    assert [chunk.sequence for chunk in buffer.drain()] == [2, 3, 4]


def test_utilisation_reflects_whichever_limit_is_closer() -> None:
    buffer = AudioBuffer(max_chunks=4, max_memory_bytes=1_000_000)

    buffer.append(make_chunk(0, size=10))
    buffer.append(make_chunk(1, size=10))

    assert buffer.utilisation == 0.5


def test_size_tracking_stays_accurate_across_operations() -> None:
    buffer = AudioBuffer(max_chunks=10, max_memory_bytes=1_000_000)

    buffer.append(make_chunk(0, size=100))
    buffer.append(make_chunk(1, size=200))
    assert buffer.size_bytes == 300

    buffer.pop()
    assert buffer.size_bytes == 200

    buffer.clear()
    assert buffer.size_bytes == 0
