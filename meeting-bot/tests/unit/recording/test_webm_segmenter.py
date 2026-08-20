"""Tests for re-framing a live WebM stream into standalone segments.

The behaviour that matters here is not "the bytes changed" but two guarantees
a player and a user respectively depend on: every segment is a file in its own
right, and the audio that went in comes out exactly once.
"""

from __future__ import annotations

from app.recording.webm_segmenter import WebMSegmenter
from tests.conftest import make_webm_stream, read_webm, webm_init_bytes


def _segment_stream(
    stream: bytes,
    *,
    cut_at: list[int] | None = None,
    feed_size: int | None = None,
) -> list[bytes]:
    """Run a stream through a segmenter, cutting at the given byte offsets.

    Args:
        stream: The bytes a recorder would produce.
        cut_at: Offsets into ``stream`` to cut at, standing in for a duration
            threshold being reached partway through a recording. The end of the
            stream always cuts, as stopping a recording does.
        feed_size: Feed in slices of this many bytes rather than in one go.

    Returns:
        One ``bytes`` per segment, each of which should be a playable file.
    """
    boundaries = [*sorted(set(cut_at or [])), len(stream)]
    segmenter = WebMSegmenter(meeting_id="test")

    files: list[bytes] = []
    start = 0
    for boundary in boundaries:
        window = stream[start:boundary]
        step = feed_size or max(len(window), 1)
        current = bytearray()
        for offset in range(0, len(window), step):
            segmenter.feed(window[offset : offset + step])
            current.extend(segmenter.drain())
        current.extend(segmenter.cut())
        if current:
            files.append(bytes(current))
        start = boundary
    return files


def test_every_segment_carries_the_stream_header() -> None:
    """The reason later segments were unplayable: only the first had a header."""
    stream = make_webm_stream([(0, [0, 500, 1000, 1500, 2000, 2500])])

    files = _segment_stream(stream, cut_at=[len(stream) // 2])

    assert len(files) == 2
    for file in files:
        init, blocks = read_webm(file)
        assert init == webm_init_bytes()
        assert blocks


def test_no_audio_is_lost_or_repeated_across_a_cut() -> None:
    """A cut must move the boundary, not drop or replay audio around it."""
    timestamps = [index * 20 for index in range(300)]
    stream = make_webm_stream([(0, timestamps[:150]), (3000, timestamps[150:])])

    files = _segment_stream(stream, cut_at=[len(stream) // 3, 2 * len(stream) // 3])

    recovered = [payload for file in files for _, payload in read_webm(file)[1]]
    expected = [payload for _, payload in read_webm(stream)[1]]
    assert recovered == expected


def test_a_segment_starts_its_timeline_at_zero() -> None:
    """Audio 30 minutes into a meeting has to look like the start of its file.

    Left alone, a later segment's blocks keep their offsets from the beginning
    of the meeting, and a player reads that as a file that opens with a very
    long silence.
    """
    stream = make_webm_stream([(1_800_000, [1_800_000 + index * 20 for index in range(100)])])

    files = _segment_stream(stream)

    assert len(files) == 1
    _, blocks = read_webm(files[0])
    assert blocks[0][0] == 0
    assert [timestamp for timestamp, _ in blocks] == [index * 20 for index in range(100)]


def test_each_segment_is_timed_from_its_own_start() -> None:
    stream = make_webm_stream([(0, [index * 100 for index in range(60)])])

    files = _segment_stream(stream, cut_at=[len(stream) // 2])

    for file in files:
        _, blocks = read_webm(file)
        assert blocks[0][0] == 0


def test_bytes_split_inside_an_element_are_reassembled() -> None:
    """Chrome splits its blobs mid-element, so no feed boundary is safe to trust.

    Observed against a real recorder: the split lands between a block's id byte
    and its size. Feeding one byte at a time covers that and every other place
    a boundary could fall.
    """
    stream = make_webm_stream([(0, [index * 20 for index in range(50)])])

    whole = _segment_stream(stream)
    fragmented = _segment_stream(stream, feed_size=1)

    assert fragmented == whole


def test_media_time_follows_the_encoder_not_the_clock() -> None:
    segmenter = WebMSegmenter(meeting_id="test")
    assert segmenter.segment_duration_ms == 0

    # Four blocks a second apart hold four seconds of audio: the last one plays
    # too, even though nothing after it says where it ends.
    segmenter.feed(make_webm_stream([(0, [0, 1_000, 2_000, 3_000])]))
    assert segmenter.segment_duration_ms == 4_000

    segmenter.cut()
    assert segmenter.segment_duration_ms == 0


def test_media_time_restarts_when_a_segment_does() -> None:
    segmenter = WebMSegmenter(meeting_id="test")
    segmenter.feed(make_webm_stream([(0, [0, 5_000])]))
    segmenter.cut()

    segmenter.feed(make_webm_stream([(10_000, [10_000, 12_000])])[len(webm_init_bytes()) :])

    # Counted from this segment's own first block, not from the meeting's.
    assert segmenter.segment_duration_ms == 4_000


def test_a_cut_with_no_audio_produces_no_file() -> None:
    """An empty segment would upload as a header with nothing behind it."""
    segmenter = WebMSegmenter(meeting_id="test")
    segmenter.feed(webm_init_bytes())

    assert segmenter.has_segment_data is False
    assert segmenter.cut() == b""


def test_clusters_with_declared_sizes_are_handled() -> None:
    """Not every writer leaves clusters open; both encodings are legal."""
    stream = make_webm_stream(
        [(0, [0, 100, 200]), (300, [300, 400])], known_cluster_sizes=True
    )

    files = _segment_stream(stream)

    _, blocks = read_webm(files[0])
    assert [timestamp for timestamp, _ in blocks] == [0, 100, 200, 300, 400]


def test_long_runs_are_split_across_clusters() -> None:
    """A block's timestamp is a 16-bit offset from its cluster, so one cluster
    cannot span a long recording. Chrome opens a new one only every 30 seconds,
    which is far too coarse to cut a segment on, so blocks are re-packed into
    clusters of this module's own — and every timestamp has to survive that."""
    timestamps = [index * 1_000 for index in range(120)]
    stream = make_webm_stream(
        [(start, [t for t in timestamps if start <= t < start + 30_000])
         for start in range(0, 120_000, 30_000)]
    )

    files = _segment_stream(stream)

    _, blocks = read_webm(files[0])
    assert [timestamp for timestamp, _ in blocks] == timestamps


def test_audio_still_reaches_storage_when_the_stream_is_not_webm() -> None:
    """A recording that cannot be re-framed is worth more than no recording."""
    segmenter = WebMSegmenter(meeting_id="test")

    segmenter.feed(b"not a webm stream at all")
    segmenter.feed(b" and some more of it")

    assert segmenter.degraded is True
    assert segmenter.drain() + segmenter.cut() == b"not a webm stream at all and some more of it"
    # No media time to report, which is the uploader's cue to fall back to the clock.
    assert segmenter.segment_duration_ms == 0


def test_blocks_survive_a_cut_that_lands_between_feeds() -> None:
    """The open cluster is written out by the cut, not carried into the next file."""
    stream = make_webm_stream([(0, [0, 20, 40, 60, 80])])
    segmenter = WebMSegmenter(meeting_id="test")

    segmenter.feed(stream)
    # Nothing has closed a cluster yet, so a plain drain would leave audio behind.
    first = segmenter.drain() + segmenter.cut()

    init, blocks = read_webm(first)
    assert init == webm_init_bytes()
    assert len(blocks) == 5


def test_corruption_mid_stream_does_not_swallow_the_rest_of_the_recording() -> None:
    """Bytes that cannot be a header must not leave the parser waiting forever.

    Treating corruption as "not enough data yet" would buffer the remainder of
    the meeting and upload none of it.
    """
    stream = make_webm_stream([(0, [0, 20, 40])])
    segmenter = WebMSegmenter(meeting_id="test")

    segmenter.feed(stream)
    segmenter.feed(b"\x00\x00\x00\x00")  # 0x00 cannot begin an element id
    segmenter.feed(b"trailing audio bytes")

    assert segmenter.degraded is True
    output = segmenter.drain() + segmenter.cut()

    # The audio parsed before the corruption is still written out, header first.
    assert output.startswith(webm_init_bytes())
    for timestamp in (0, 20, 40):
        assert b"audio-" + timestamp.to_bytes(4, "big") in output
    # And everything after it still reaches storage rather than being buffered.
    assert output.endswith(b"trailing audio bytes")
