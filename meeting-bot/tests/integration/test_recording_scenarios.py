"""Whole meetings, played through the real recording pipeline.

These exercise the pipeline the way a meeting does: a browser pushing audio in
five-second chunks for anything from five minutes to four hours, with segments
cut along the way. The point is not any single behaviour but a set of
invariants that must hold for every meeting length and every way of driving it:

  * every uploaded object is a playable file, header first, timeline from zero
  * the audio that went in comes out exactly once, across all the segments
  * a segment is never shorter than asked for, and never longer by more than
    one chunk

A recording is the one artefact of a meeting that cannot be recreated, so the
failures worth catching here are the quiet ones: audio dropped at a boundary,
a segment that uploads but will not play, a second recording that captures
nothing.
"""

from __future__ import annotations

import random
from typing import Any

import pytest

from app.meeting_platform.google_meet.platform import GoogleMeetPlatform
from app.recording.chunk_uploader import DirectChunkUploader
from app.recording.models import RecordingContext, RecordingStats
from app.recording.recorder import Recorder
from tests.conftest import make_webm_stream, read_webm, webm_init_bytes

pytestmark = pytest.mark.asyncio

BLOCK_MS = 65          # Chrome's real Opus cadence
CLUSTER_MS = 30_000    # Chrome opens a cluster about this often
CHUNK_MS = 5_000       # the default MediaRecorder timeslice


# ----------------------------------------------------------------------
# Doubles
# ----------------------------------------------------------------------


class FakePage:
    """A page that binds a callback name once, as Playwright does."""

    def __init__(self) -> None:
        self.is_available = True
        self.callback: Any = None
        self.rebinds_refused = 0

    async def expose_function(self, name: str, handler: Any) -> bool:
        if self.callback is not None:
            self.rebinds_refused += 1
            return False
        self.callback = handler
        return True

    async def evaluate(self, script: str, arg: Any = None) -> None:
        return None


class FakeCW:
    """Issues a distinct upload target per segment, as CW does."""

    def __init__(self, *, fail_after: int | None = None) -> None:
        self.issued = 0
        self._fail_after = fail_after

    async def create_resumable_upload(
        self, *, project_id: str, filename: str, content_type: str
    ) -> Any:
        from app.clients.cw_utils import ResumableUploadTarget

        if self._fail_after is not None and self.issued >= self._fail_after:
            raise RuntimeError("simulated signed-url failure")
        self.issued += 1
        return ResumableUploadTarget(
            upload_url=f"upload://{self.issued}",
            public_url=f"https://storage.test.invalid/{filename}",
        )


class SegmentStorage:
    """Keeps each segment's object separately, so each can be checked as a file."""

    def __init__(
        self,
        *,
        fail_puts: set[int] | None = None,
        fail_objects: set[str] | None = None,
    ) -> None:
        self._objects: dict[str, bytearray] = {}
        self._order: list[str] = []
        self.puts = 0
        self._fail_puts = fail_puts or set()
        self._fail_objects = fail_objects or set()

    async def upload_block(
        self, state: Any, data: bytes, *, is_final: bool, meeting_id: str = ""
    ) -> None:
        from app.core.exceptions import ChunkUploadError

        self.puts += 1
        if self.puts in self._fail_puts or state.upload_url in self._fail_objects:
            raise ChunkUploadError(f"simulated storage failure on put {self.puts}")

        if state.upload_url not in self._objects:
            self._objects[state.upload_url] = bytearray()
            self._order.append(state.upload_url)
        self._objects[state.upload_url].extend(data)
        state.uploaded_bytes += len(data)
        state.block_count += 1
        if is_final:
            state.completed = True

    @property
    def files(self) -> list[bytes]:
        return [bytes(self._objects[url]) for url in self._order]


# ----------------------------------------------------------------------
# Driving a meeting
# ----------------------------------------------------------------------


def meeting_audio(total_ms: int, *, block_ms: int = BLOCK_MS) -> bytes:
    """A WebM stream shaped like a meeting of ``total_ms``."""
    plan = [
        (start, list(range(start, min(start + CLUSTER_MS, total_ms), block_ms)))
        for start in range(0, total_ms, CLUSTER_MS)
    ]
    return make_webm_stream(plan)


def into_chunks(stream: bytes, total_ms: int, *, chunk_ms: int = CHUNK_MS) -> list[bytes]:
    """Slice the stream the way the browser delivers it: on a timer, mid-element."""
    count = max(total_ms // chunk_ms, 1)
    step = len(stream) // count + 1
    return [stream[offset : offset + step] for offset in range(0, len(stream), step)]


async def build_recorder(
    page: FakePage,
    storage: SegmentStorage,
    cw: FakeCW,
    *,
    target_seconds: int | None,
    chunk_ms: int = CHUNK_MS,
    platform: GoogleMeetPlatform | None = None,
) -> Recorder:
    # One platform serves the whole meeting, which is how MeetingSession holds
    # it: recording twice does not re-create the page or its bindings.
    platform = platform or GoogleMeetPlatform(page)  # type: ignore[arg-type]
    stats = RecordingStats()
    uploader = DirectChunkUploader(
        cw_client=cw,
        storage=storage,
        stats=stats,
        final_block_retry_seconds=0,  # no need to wait out real backoff in a test
    )
    return Recorder(
        platform=platform,
        uploader=uploader,
        context=RecordingContext(meeting_id="meeting-1", project_id="project-test"),
        finalizer=None,
        chunk_duration_ms=chunk_ms,
        finalize_grace_period_seconds=0,
        max_duration_seconds=target_seconds,
    )


async def play(
    recorder: Recorder,
    page: FakePage,
    chunks: list[bytes],
    *,
    sequence_start: int = 0,
) -> None:
    """Push audio at the page callback, which is what the browser really does."""
    for index, data in enumerate(chunks, start=sequence_start):
        await page.callback(
            {
                "meetingId": "meeting-1",
                "chunkId": f"meeting-1-{index}",
                "audioBlob": list(data),
            }
        )


async def record_meeting(
    minutes: float,
    *,
    target_seconds: int | None,
    chunk_ms: int = CHUNK_MS,
    block_ms: int = BLOCK_MS,
) -> tuple[list[bytes], int, RecordingStats]:
    """Record one meeting end to end. Returns its files, blocks in, and stats."""
    total_ms = int(minutes * 60_000)
    stream = meeting_audio(total_ms, block_ms=block_ms)
    blocks_in = len(read_webm(stream)[1])

    page, storage, cw = FakePage(), SegmentStorage(), FakeCW()
    recorder = await build_recorder(
        page, storage, cw, target_seconds=target_seconds, chunk_ms=chunk_ms
    )
    await recorder.start()
    await play(recorder, page, into_chunks(stream, total_ms, chunk_ms=chunk_ms))
    await recorder.stop()
    return storage.files, blocks_in, recorder.stats


# ----------------------------------------------------------------------
# The invariants
# ----------------------------------------------------------------------


def assert_playable(files: list[bytes]) -> list[tuple[int, list[bytes]]]:
    """Every uploaded object must stand on its own. Returns each file's blocks."""
    parsed = []
    for index, data in enumerate(files, start=1):
        init, blocks = read_webm(data)  # raises if the container is malformed
        assert init == webm_init_bytes(), f"segment {index} is missing its header"
        assert blocks, f"segment {index} contains no audio"
        assert blocks[0][0] == 0, f"segment {index} does not start its timeline at zero"
        duration = blocks[-1][0] - blocks[0][0] + BLOCK_MS
        parsed.append((duration, [payload for _, payload in blocks]))
    return parsed


def assert_audio_intact(parsed: list[tuple[int, list[bytes]]], blocks_in: int) -> None:
    """Nothing dropped at a boundary, nothing replayed into the next segment."""
    recovered = [payload for _, payloads in parsed for payload in payloads]
    assert len(recovered) == blocks_in, (
        f"{blocks_in} audio blocks went in, {len(recovered)} came out"
    )
    assert len(set(recovered)) == len(recovered), "an audio block was uploaded twice"


def assert_segment_lengths(parsed: list[tuple[int, list[bytes]]], target_seconds: int) -> None:
    """Never short of the target, never over it by more than one chunk."""
    target_ms = target_seconds * 1_000
    for index, (duration, _) in enumerate(parsed[:-1], start=1):
        assert duration >= target_ms, f"segment {index} is {duration} ms, short of {target_ms}"
        assert duration < target_ms + CHUNK_MS + BLOCK_MS, (
            f"segment {index} overran by more than one chunk: {duration} ms"
        )


# ----------------------------------------------------------------------
# Meetings of every length
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "minutes",
    [5, 14.9, 15, 15.05, 30, 47, 60, 63, 120, 240],
    ids=["5min", "just-under-one", "exactly-one", "just-over-one", "30min",
         "47min", "1hr", "1hr3min", "2hr", "4hr"],
)
async def test_a_meeting_of_any_length_uploads_playable_segments(minutes: float) -> None:
    """The house configuration: 15-minute segments, whatever the meeting does."""
    target = 15 * 60
    files, blocks_in, _ = await record_meeting(minutes, target_seconds=target)

    parsed = assert_playable(files)
    assert_audio_intact(parsed, blocks_in)
    assert_segment_lengths(parsed, target)

    # One file per completed target period, plus a remainder when the meeting
    # does not end just as a cut fires.
    whole = int(minutes * 60 // target)
    assert max(whole, 1) <= len(files) <= whole + 1
    total = sum(duration for duration, _ in parsed)
    assert total == pytest.approx(minutes * 60_000, rel=0.002), "segments must cover the meeting"


@pytest.mark.parametrize("minutes", [1.2, 8.3, 23.7, 51.4, 96.5, 183.2])
async def test_random_meeting_lengths_hold_the_same_invariants(minutes: float) -> None:
    """Lengths that land nowhere near a segment boundary."""
    target = 15 * 60
    files, blocks_in, _ = await record_meeting(minutes, target_seconds=target)

    parsed = assert_playable(files)
    assert_audio_intact(parsed, blocks_in)
    assert_segment_lengths(parsed, target)


@pytest.mark.parametrize("target_minutes", [1, 5, 15, 30, 60])
async def test_a_two_hour_meeting_at_every_segment_size(target_minutes: int) -> None:
    """The same two hours, cut into 120 pieces or into 2."""
    files, blocks_in, _ = await record_meeting(120, target_seconds=target_minutes * 60)

    parsed = assert_playable(files)
    assert_audio_intact(parsed, blocks_in)
    assert_segment_lengths(parsed, target_minutes * 60)
    assert len(files) == 120 // target_minutes


async def test_a_four_hour_meeting_without_segmentation_is_one_valid_file() -> None:
    """Turning the feature off must degrade to a single playable recording."""
    files, blocks_in, _ = await record_meeting(240, target_seconds=None)

    parsed = assert_playable(files)
    assert_audio_intact(parsed, blocks_in)
    assert len(files) == 1
    assert parsed[0][0] == pytest.approx(240 * 60_000, rel=0.001)


# ----------------------------------------------------------------------
# Edges
# ----------------------------------------------------------------------


async def test_a_meeting_ending_exactly_on_a_boundary_uploads_no_empty_file() -> None:
    """Two hours of 15-minute segments divides evenly; the tail has nothing in it."""
    files, blocks_in, _ = await record_meeting(120, target_seconds=15 * 60)

    parsed = assert_playable(files)
    assert_audio_intact(parsed, blocks_in)
    assert len(files) == 8, "an empty ninth object would be uploaded but unplayable"


async def test_a_meeting_that_ends_moments_after_a_cut() -> None:
    """The final segment is whatever is left, even if that is a few seconds."""
    files, blocks_in, _ = await record_meeting(15.2, target_seconds=15 * 60)

    parsed = assert_playable(files)
    assert_audio_intact(parsed, blocks_in)
    assert len(files) == 2
    assert parsed[1][0] < 30_000, "the tail should be the short remainder"


async def test_a_recording_stopped_before_any_audio_arrives() -> None:
    page, storage, cw = FakePage(), SegmentStorage(), FakeCW()
    recorder = await build_recorder(page, storage, cw, target_seconds=15 * 60)

    await recorder.start()
    outcome = await recorder.stop()

    assert outcome.complete is False
    assert storage.files == [], "nothing was captured, so nothing should be uploaded"
    assert cw.issued == 0, "an upload target should not be reserved for silence"


async def test_a_very_short_meeting() -> None:
    files, blocks_in, _ = await record_meeting(0.5, target_seconds=15 * 60)

    parsed = assert_playable(files)
    assert_audio_intact(parsed, blocks_in)
    assert len(files) == 1


@pytest.mark.parametrize("chunk_ms", [1_000, 5_000, 10_000, 30_000])
async def test_the_browser_chunk_size_does_not_change_the_outcome(chunk_ms: int) -> None:
    """Segments get tighter with smaller chunks, but nothing is ever lost."""
    target = 5 * 60
    files, blocks_in, _ = await record_meeting(22, target_seconds=target, chunk_ms=chunk_ms)

    parsed = assert_playable(files)
    assert_audio_intact(parsed, blocks_in)
    for duration, _ in parsed[:-1]:
        assert duration >= target * 1_000
        assert duration < target * 1_000 + chunk_ms + BLOCK_MS


# ----------------------------------------------------------------------
# Ways a meeting goes wrong
# ----------------------------------------------------------------------


async def test_chunks_that_arrive_out_of_order_are_still_written_in_order() -> None:
    """A reconnect can interleave a replayed chunk with a fresh one."""
    total_ms = 20 * 60_000
    stream = meeting_audio(total_ms)
    blocks_in = len(read_webm(stream)[1])
    chunks = into_chunks(stream, total_ms)

    page, storage, cw = FakePage(), SegmentStorage(), FakeCW()
    recorder = await build_recorder(page, storage, cw, target_seconds=15 * 60)
    await recorder.start()

    order = list(range(len(chunks)))
    random.Random(7).shuffle(order[3:9])  # a burst arrives scrambled
    for index in order:
        await page.callback(
            {
                "meetingId": "meeting-1",
                "chunkId": f"meeting-1-{index}",
                "audioBlob": list(chunks[index]),
            }
        )
    await recorder.stop()

    parsed = assert_playable(storage.files)
    assert_audio_intact(parsed, blocks_in)


async def test_a_chunk_delivered_twice_is_not_recorded_twice() -> None:
    total_ms = 10 * 60_000
    stream = meeting_audio(total_ms)
    blocks_in = len(read_webm(stream)[1])
    chunks = into_chunks(stream, total_ms)

    page, storage, cw = FakePage(), SegmentStorage(), FakeCW()
    recorder = await build_recorder(page, storage, cw, target_seconds=15 * 60)
    await recorder.start()
    for index, data in enumerate(chunks):
        await page.callback(
            {"meetingId": "meeting-1", "chunkId": f"meeting-1-{index}", "audioBlob": list(data)}
        )
        if index % 4 == 0:  # the page re-sends after a wobbly connection
            await page.callback(
                {"meetingId": "meeting-1", "chunkId": f"meeting-1-{index}", "audioBlob": list(data)}
            )
    await recorder.stop()

    parsed = assert_playable(storage.files)
    assert_audio_intact(parsed, blocks_in)


async def test_a_storage_failure_mid_segment_is_retried_not_lost() -> None:
    """One rejected block must not cost the meeting anything."""
    total_ms = 20 * 60_000
    stream = meeting_audio(total_ms)
    blocks_in = len(read_webm(stream)[1])

    page, cw = FakePage(), FakeCW()
    storage = SegmentStorage(fail_puts={2})  # storage refuses a single PUT, once
    recorder = await build_recorder(page, storage, cw, target_seconds=15 * 60)
    await recorder.start()
    await play(recorder, page, into_chunks(stream, total_ms))
    await recorder.stop()

    parsed = assert_playable(storage.files)
    assert_audio_intact(parsed, blocks_in)


async def test_a_segment_that_fails_to_close_does_not_corrupt_the_next_one() -> None:
    """Losing one segment is bad. Losing the rest of the meeting with it is worse."""
    total_ms = 35 * 60_000
    stream = meeting_audio(total_ms)
    page, cw = FakePage(), FakeCW()

    # Every PUT for the first segment's object is refused, including the one
    # that would close it. The first upload target CW issues is upload://1.
    storage = SegmentStorage(fail_objects={"upload://1"})
    recorder = await build_recorder(page, storage, cw, target_seconds=15 * 60)
    await recorder.start()
    await play(recorder, page, into_chunks(stream, total_ms))
    await recorder.stop()

    # Whatever survived must still be a playable file starting from zero.
    parsed = assert_playable(storage.files)
    assert parsed, "later segments should still upload after an early failure"
    recovered = [payload for _, payloads in parsed for payload in payloads]
    assert len(set(recovered)) == len(recovered), "recovery must not duplicate audio"


async def test_a_recording_with_no_upload_target_fails_without_losing_the_meeting() -> None:
    """CW being down should not look like a successful empty recording."""
    total_ms = 6 * 60_000
    stream = meeting_audio(total_ms)
    page, storage = FakePage(), SegmentStorage()
    cw = FakeCW(fail_after=0)

    recorder = await build_recorder(page, storage, cw, target_seconds=15 * 60)
    await recorder.start()
    await play(recorder, page, into_chunks(stream, total_ms))
    outcome = await recorder.stop()

    assert outcome.complete is False
    assert storage.files == []


# ----------------------------------------------------------------------
# Recording a meeting more than once
# ----------------------------------------------------------------------


async def test_recording_twice_in_one_meeting_captures_both() -> None:
    """Start, stop, start again: the second recording used to capture nothing."""
    page = FakePage()
    storage, cw = SegmentStorage(), FakeCW()

    first_ms, second_ms = 20 * 60_000, 18 * 60_000
    first_stream, second_stream = meeting_audio(first_ms), meeting_audio(second_ms)
    blocks_in = len(read_webm(first_stream)[1]) + len(read_webm(second_stream)[1])

    platform = GoogleMeetPlatform(page)  # type: ignore[arg-type]
    first = await build_recorder(page, storage, cw, target_seconds=15 * 60, platform=platform)
    await first.start()
    await play(first, page, into_chunks(first_stream, first_ms))
    await first.stop()

    # A new Recorder on the same platform, as MeetingSession builds for every
    # start_recording call.
    second = await build_recorder(page, storage, cw, target_seconds=15 * 60, platform=platform)
    await second.start()
    # The page restarts its own recorder too, so chunk numbering starts over.
    await play(second, page, into_chunks(second_stream, second_ms))
    await second.stop()

    assert page.rebinds_refused == 1, "the page binds the callback only once"

    parsed = assert_playable(storage.files)
    recovered = [payload for _, payloads in parsed for payload in payloads]
    assert len(recovered) == blocks_in, "audio from both recordings must reach storage"
    assert len(storage.files) == 4, "two segments and a remainder each"


async def test_the_second_recording_starts_a_fresh_timeline() -> None:
    """Its segments must not inherit the first recording's clock."""
    page = FakePage()
    storage, cw = SegmentStorage(), FakeCW()

    platform = GoogleMeetPlatform(page)  # type: ignore[arg-type]
    for _ in range(2):
        recorder = await build_recorder(
            page, storage, cw, target_seconds=15 * 60, platform=platform
        )
        await recorder.start()
        await play(recorder, page, into_chunks(meeting_audio(6 * 60_000), 6 * 60_000))
        await recorder.stop()

    for data in storage.files:
        _, blocks = read_webm(data)
        assert blocks[0][0] == 0
