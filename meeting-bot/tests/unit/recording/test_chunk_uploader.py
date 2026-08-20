"""Tests for both upload transports."""

from __future__ import annotations

import asyncio

import pytest

from app.core.exceptions import ChunkUploadError
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


async def test_direct_upload_waits_for_more_than_a_full_block(
    context: RecordingContext,
) -> None:
    """Bytes accumulate, and one whole block is deliberately held back.

    Storage rejects a short non-final block, so data must reach a block boundary
    before it can be sent. But the buffer is never drained to empty: only the
    final request may declare the object's total size, and such a request has to
    carry data. Holding a block back guarantees there is something to send.
    """
    storage = FakeStorage()
    uploader = DirectChunkUploader(
        cw_client=FakeCWClient(), storage=storage, stats=RecordingStats()
    )
    await uploader.start(context)

    # Half a block: nothing to send yet.
    await uploader.upload(make_chunk(0, size=BLOCK // 2))
    assert storage.blocks == []

    # Exactly one block: still nothing, because it is being kept for the finalize.
    await uploader.upload(make_chunk(1, size=BLOCK // 2))
    assert storage.blocks == []

    # Past a block boundary, the first block can safely go.
    await uploader.upload(make_chunk(2, size=1))
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


# --------------------------------------------------------------------------
# Block-boundary finalization
#
# The bug these cover: the streaming loop used to drain the buffer to exactly
# empty, so a recording whose length was a multiple of the block size had no
# bytes left for the final request. A zero-length PUT is a status query in the
# resumable protocol, so storage answered 308 and never closed the object —
# which is why uploads failed only sometimes.
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "total_bytes,label",
    [
        (2 * BLOCK, "exactly two blocks"),
        (BLOCK, "exactly one block"),
        (3 * BLOCK, "exactly three blocks"),
    ],
)
async def test_a_recording_on_a_block_boundary_still_closes_the_object(
    context: RecordingContext, total_bytes: int, label: str
) -> None:
    storage = FakeStorage()
    uploader = DirectChunkUploader(
        cw_client=FakeCWClient(), storage=storage, stats=RecordingStats()
    )
    await uploader.start(context)

    await uploader.upload(make_chunk(0, size=total_bytes))
    outcome = await uploader.finalize()

    assert outcome.complete is True, f"{label} must finalize"
    assert len(storage.data) == total_bytes, "every byte must reach storage"

    final_blocks = [size for size, is_final in storage.blocks if is_final]
    assert len(final_blocks) == 1, "exactly one request may close the object"
    assert final_blocks[0] > 0, "the closing request must carry data, not query status"


async def test_no_block_is_larger_than_the_configured_size(
    context: RecordingContext,
) -> None:
    """Storage rejects a non-final block that is not a multiple of 256 KiB."""
    storage = FakeStorage()
    uploader = DirectChunkUploader(
        cw_client=FakeCWClient(), storage=storage, stats=RecordingStats()
    )
    await uploader.start(context)

    await uploader.upload(make_chunk(0, size=5 * BLOCK + 77))
    await uploader.finalize()

    for size, is_final in storage.blocks:
        if not is_final:
            assert size == BLOCK, "non-final blocks must be exactly one block"
    assert len(storage.data) == 5 * BLOCK + 77


async def test_a_recording_with_no_audio_does_not_send_a_bogus_finalize(
    context: RecordingContext,
) -> None:
    storage = FakeStorage()
    uploader = DirectChunkUploader(
        cw_client=FakeCWClient(), storage=storage, stats=RecordingStats()
    )
    await uploader.start(context)

    outcome = await uploader.finalize()

    assert outcome.complete is False
    assert storage.blocks == [], "nothing should be sent for an empty recording"


async def test_storage_refuses_an_empty_final_block(context: RecordingContext) -> None:
    """Defence in depth at the protocol boundary, independent of the caller."""
    from app.clients.object_storage import ResumableUploadClient, ResumableUploadState

    state = ResumableUploadState(upload_url="https://storage.invalid/u", content_type="audio/webm")
    state.uploaded_bytes = 2 * BLOCK

    with pytest.raises(ChunkUploadError, match="queries status"):
        await ResumableUploadClient().upload_block(state, b"", is_final=True, meeting_id="m")


# --------------------------------------------------------------------------
# Concurrency
#
# The page delivers chunks through an exposed callback and Playwright dispatches
# each call as its own task, so `upload` genuinely runs concurrently. Without
# serialisation two chunks arriving together each reserved their own object and
# the recording was split across both.
# --------------------------------------------------------------------------


class _SlowCWClient(FakeCWClient):
    """Reserving an object is a network round trip; widen the race window."""

    async def create_resumable_upload(self, **kwargs):  # type: ignore[no-untyped-def]
        await asyncio.sleep(0.02)
        return await super().create_resumable_upload(**kwargs)


async def test_concurrent_chunks_reserve_exactly_one_object(
    context: RecordingContext,
) -> None:
    cw = _SlowCWClient()
    uploader = DirectChunkUploader(cw_client=cw, storage=FakeStorage(), stats=RecordingStats())
    await uploader.start(context)

    await asyncio.gather(
        uploader.upload(make_chunk(0, size=64)),
        uploader.upload(make_chunk(1, size=64)),
        uploader.upload(make_chunk(2, size=64)),
    )
    await uploader.finalize()

    assert cw.upload_targets == 1, "one recording must map to one stored object"


async def test_concurrent_chunks_are_written_in_order(
    context: RecordingContext,
) -> None:
    """Interleaved writes would corrupt the container, not merely reorder it."""
    storage = FakeStorage()
    uploader = DirectChunkUploader(
        cw_client=_SlowCWClient(), storage=storage, stats=RecordingStats()
    )
    await uploader.start(context)

    # Delivered out of order and concurrently, as a reconnect drain would.
    await asyncio.gather(*(uploader.upload(make_chunk(i, size=32)) for i in (3, 0, 2, 1)))
    await uploader.finalize()

    expected = b"".join(bytes([i]) * 32 for i in range(4))
    assert bytes(storage.data) == expected


async def test_a_chunk_arriving_during_finalize_cannot_append_after_close(
    context: RecordingContext,
) -> None:
    storage = FakeStorage()
    uploader = DirectChunkUploader(
        cw_client=FakeCWClient(), storage=storage, stats=RecordingStats()
    )
    await uploader.start(context)
    await uploader.upload(make_chunk(0, size=128))

    # A late chunk racing the stop, which is exactly what the grace period covers.
    _, outcome = await asyncio.gather(
        uploader.upload(make_chunk(1, size=128)),
        uploader.finalize(),
    )

    finals = [is_final for _, is_final in storage.blocks if is_final]
    assert len(finals) == 1, "the object may be closed exactly once"
    assert isinstance(outcome.complete, bool)


async def test_reinitialize_preserves_bytes_during_concurrent_upload(
    context: RecordingContext,
) -> None:
    """Simulate the recorder finalizing a segment, reinitializing, and a
    concurrent chunk arriving between finalize() and reinitialize(). The
    uploader must not lose those bytes when preparing the next segment.
    """
    storage = FakeStorage()
    cw = FakeCWClient()
    uploader = DirectChunkUploader(cw_client=cw, storage=storage, stats=RecordingStats())
    await uploader.start(context)

    # First segment: a small chunk that will be held until finalize.
    await uploader.upload(make_chunk(0, size=128))

    # Race: finalize and an arriving chunk run concurrently. The late chunk may
    # complete after finalize returns but before reinitialize clears pending
    # bytes; reinitialize must not drop it.
    finalize_task = asyncio.create_task(uploader.finalize())
    upload_task = asyncio.create_task(uploader.upload(make_chunk(1, size=128)))

    # Wait for both to finish.
    outcome_first = await finalize_task
    await upload_task

    # Prepare next segment (what Recorder would do).
    await uploader.reinitialize(context)

    # Second segment: more audio.
    await uploader.upload(make_chunk(2, size=64))
    outcome_second = await uploader.finalize()

    # All bytes from all chunks must appear in storage in sequence order.
    expected = bytes([0]) * 128 + bytes([1]) * 128 + bytes([2]) * 64
    assert bytes(storage.data) == expected
    assert outcome_first.complete is True or outcome_first.complete is False
    assert outcome_second.complete is True
