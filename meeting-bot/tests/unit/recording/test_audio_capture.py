"""Tests for the page-to-Python capture boundary.

The invariant under test: capture never raises. An exception here reaches page
JavaScript and stops the recorder mid-meeting.
"""

from __future__ import annotations

import pytest

from app.recording.audio_capture import AudioCapture
from app.recording.models import AudioChunk

pytestmark = pytest.mark.asyncio


def page_payload(sequence: int, *, meeting_id: str = "meeting-1") -> dict:
    """The shape the browser actually sends: audio as a JSON array of bytes."""
    return {
        "meetingId": meeting_id,
        "chunkId": f"{meeting_id}-{sequence}",
        "timestamp": "2026-08-17T10:00:00Z",
        "audioBlob": [1, 2, 3, 4],
    }


async def test_page_payload_becomes_a_typed_chunk() -> None:
    received: list[AudioChunk] = []
    capture = AudioCapture(meeting_id="meeting-1", handler=_collect(received))
    capture.start()

    await capture.on_chunk(page_payload(0))

    assert len(received) == 1
    assert received[0].sequence == 0
    assert received[0].data == bytes([1, 2, 3, 4])
    assert capture.stats.chunks_captured == 1
    assert capture.stats.bytes_captured == 4


async def test_chunks_are_ignored_before_start_and_after_stop() -> None:
    """The page callback outlives a recording, so stale chunks must be dropped."""
    received: list[AudioChunk] = []
    capture = AudioCapture(meeting_id="meeting-1", handler=_collect(received))

    await capture.on_chunk(page_payload(0))
    assert received == []

    capture.start()
    await capture.on_chunk(page_payload(1))
    capture.stop()
    await capture.on_chunk(page_payload(2))

    assert [chunk.sequence for chunk in received] == [1]


async def test_malformed_payload_is_counted_not_raised() -> None:
    received: list[AudioChunk] = []
    capture = AudioCapture(meeting_id="meeting-1", handler=_collect(received))
    capture.start()

    await capture.on_chunk({"audioBlob": [1, 2]})            # no ids
    await capture.on_chunk({"meetingId": "m", "chunkId": "no-number"})  # unparseable id

    assert received == []
    assert capture.malformed_count == 2
    assert capture.stats.chunks_captured == 0


async def test_handler_failure_does_not_propagate_to_the_page() -> None:
    """A broken downstream must not stop the recorder."""

    async def explode(_chunk: AudioChunk) -> None:
        raise RuntimeError("downstream is down")

    capture = AudioCapture(meeting_id="meeting-1", handler=explode)
    capture.start()

    await capture.on_chunk(page_payload(0))  # must not raise

    # The chunk was still counted as captured; only delivery failed.
    assert capture.stats.chunks_captured == 1


async def test_project_id_defaults_but_payload_wins() -> None:
    received: list[AudioChunk] = []
    capture = AudioCapture(
        meeting_id="meeting-1", handler=_collect(received), project_id="fallback-project"
    )
    capture.start()

    await capture.on_chunk(page_payload(0))
    await capture.on_chunk({**page_payload(1), "projectId": "explicit-project"})

    assert received[0].project_id == "fallback-project"
    assert received[1].project_id == "explicit-project"


def _collect(sink: list[AudioChunk]):
    async def handler(chunk: AudioChunk) -> None:
        sink.append(chunk)

    return handler
