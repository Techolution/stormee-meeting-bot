"""Tests for both upload transports."""

from __future__ import annotations

import pytest

from app.recording.audio_buffer import AudioBuffer
from app.recording.chunk_uploader import DirectChunkUploader, StreamingChunkUploader
from app.recording.models import RecordingContext, RecordingStats
from tests.conftest import FakeAudioService, FakeCWClient, FakeStorage, make_chunk

pytestmark = pytest.mark.asyncio

BLOCK = 256 * 1024


@pytest.fixture
def context() -> RecordingContext:
    return RecordingContext(
        meeting_id="meeting-1",
        project_id="project-test",
        meeting_title="Test Meeting",
        user_name="Test User",
        user_email="test@example.com",
    )


# --------------------------------------------------------------------------
# Streaming transport
# --------------------------------------------------------------------------


async def test_streaming_sends_chunks_while_connected(context: RecordingContext) -> None:
    service = FakeAudioService(connected=True)
    stats = RecordingStats()
    uploader = StreamingChunkUploader(
        audio_service=service, buffer=AudioBuffer(), stats=stats
    )
    await uploader.start(context)

    await uploader.upload(make_chunk(0))

    assert len(service.sent) == 1
    assert stats.chunks_uploaded == 1
    assert uploader.pending_count() == 0


async def test_streaming_buffers_while_disconnected(context: RecordingContext) -> None:
    """Audio keeps being captured during an outage; it must not be discarded."""
    service = FakeAudioService(connected=False)
    uploader = StreamingChunkUploader(
        audio_service=service, buffer=AudioBuffer(), stats=RecordingStats()
    )
    await uploader.start(context)

    for sequence in range(3):
        await uploader.upload(make_chunk(sequence))

    assert service.sent == []
    assert uploader.pending_count() == 3


async def test_streaming_drains_buffer_after_reconnect(context: RecordingContext) -> None:
    service = FakeAudioService(connected=False)
    uploader = StreamingChunkUploader(
        audio_service=service, buffer=AudioBuffer(), stats=RecordingStats()
    )
    await uploader.start(context)
    for sequence in range(3):
        await uploader.upload(make_chunk(sequence))

    service.is_connected = True
    sent = await uploader.flush_buffered()

    assert sent == 3
    assert [payload["chunkId"] for payload in service.sent] == [
        "meeting-1-0", "meeting-1-1", "meeting-1-2"
    ]
    assert uploader.pending_count() == 0


async def test_interrupted_drain_preserves_the_remainder(context: RecordingContext) -> None:
    """A link that drops mid-drain must leave the unsent tail intact and in order."""
    service = FakeAudioService(connected=True)
    uploader = StreamingChunkUploader(
        audio_service=service, buffer=AudioBuffer(), stats=RecordingStats()
    )
    await uploader.start(context)

    service.is_connected = False
    for sequence in range(4):
        await uploader.upload(make_chunk(sequence))

    # Back up, but the link drops again after two chunks get through.
    service.is_connected = True
    service.fail_from = 2
    sent = await uploader.flush_buffered()

    assert sent == 2
    assert uploader.pending_count() == 2

    # Once it is healthy again, the untouched tail goes out in order.
    service.fail_from = None
    remaining = await uploader.flush_buffered()
    assert remaining == 2
    assert [payload["chunkId"] for payload in service.sent] == [
        "meeting-1-0", "meeting-1-1", "meeting-1-2", "meeting-1-3"
    ]


async def test_streaming_finalize_reports_incomplete_when_chunks_remain(
    context: RecordingContext,
) -> None:
    service = FakeAudioService(connected=False)
    uploader = StreamingChunkUploader(
        audio_service=service, buffer=AudioBuffer(), stats=RecordingStats()
    )
    await uploader.start(context)
    await uploader.upload(make_chunk(0))

    outcome = await uploader.finalize()

    assert outcome.complete is False
    assert outcome.pending_chunks == 1


# --------------------------------------------------------------------------
# Direct transport
# --------------------------------------------------------------------------


async def test_direct_upload_waits_for_a_full_block(context: RecordingContext) -> None:
    """Storage rejects a short non-final block, so bytes accumulate first."""
    storage = FakeStorage()
    uploader = DirectChunkUploader(
        cw_client=FakeCWClient(), storage=storage, stats=RecordingStats()
    )
    await uploader.start(context)

    # Half a block: nothing should be sent yet.
    await uploader.upload(make_chunk(0, size=BLOCK // 2))
    assert storage.blocks == []

    # Completing the block triggers exactly one upload.
    await uploader.upload(make_chunk(1, size=BLOCK // 2))
    assert storage.blocks == [(BLOCK, False)]


async def test_direct_upload_finalizes_with_a_short_last_block(
    context: RecordingContext,
) -> None:
    """Only the final block may be under the block size."""
    storage = FakeStorage()
    uploader = DirectChunkUploader(
        cw_client=FakeCWClient(), storage=storage, stats=RecordingStats()
    )
    await uploader.start(context)
    await uploader.upload(make_chunk(0, size=BLOCK + 500))

    outcome = await uploader.finalize()

    assert storage.blocks == [(BLOCK, False), (500, True)]
    assert outcome.complete is True
    assert outcome.uploaded_bytes == BLOCK + 500
    assert outcome.public_url is not None


async def test_direct_upload_writes_bytes_in_sequence_order(
    context: RecordingContext,
) -> None:
    """Out-of-order arrival must not reorder the object's bytes."""
    storage = FakeStorage()
    uploader = DirectChunkUploader(
        cw_client=FakeCWClient(), storage=storage, stats=RecordingStats()
    )
    await uploader.start(context)

    for sequence in (2, 0, 1):
        await uploader.upload(make_chunk(sequence, size=16))
    await uploader.finalize()

    # make_chunk fills each chunk with its own sequence byte.
    assert bytes(storage.data) == bytes([0]) * 16 + bytes([1]) * 16 + bytes([2]) * 16


async def test_direct_upload_reserves_the_object_only_once(
    context: RecordingContext,
) -> None:
    cw = FakeCWClient()
    uploader = DirectChunkUploader(cw_client=cw, storage=FakeStorage(), stats=RecordingStats())
    await uploader.start(context)

    for sequence in range(3):
        await uploader.upload(make_chunk(sequence, size=BLOCK))

    assert cw.upload_targets == 1


async def test_direct_upload_reports_failure_when_storage_rejects_the_final_block(
    context: RecordingContext,
) -> None:
    """An incomplete upload must never be reported as complete."""
    storage = FakeStorage()
    uploader = DirectChunkUploader(
        cw_client=FakeCWClient(), storage=storage, stats=RecordingStats()
    )
    await uploader.start(context)
    await uploader.upload(make_chunk(0, size=100))

    storage.fail_next = 1
    outcome = await uploader.finalize()

    assert outcome.complete is False
    assert outcome.detail


async def test_direct_upload_degrades_when_no_upload_target_can_be_created(
    context: RecordingContext,
) -> None:
    """A signed-URL failure must not raise into the capture callback."""
    cw = FakeCWClient()
    cw.fail_target = True
    uploader = DirectChunkUploader(cw_client=cw, storage=FakeStorage(), stats=RecordingStats())
    await uploader.start(context)

    await uploader.upload(make_chunk(0))  # must not raise

    outcome = await uploader.finalize()
    assert outcome.complete is False


async def test_direct_upload_requires_a_project(context: RecordingContext) -> None:
    """Without a project there is nowhere to put the recording; fail visibly, not loudly."""
    uploader = DirectChunkUploader(
        cw_client=FakeCWClient(), storage=FakeStorage(), stats=RecordingStats()
    )
    await uploader.start(RecordingContext(meeting_id="m", project_id=None))

    await uploader.upload(make_chunk(0))

    outcome = await uploader.finalize()
    assert outcome.complete is False
