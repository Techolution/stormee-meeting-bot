"""Cutting a live WebM stream into independently playable files.

``MediaRecorder`` does not emit a sequence of files. It emits *one* WebM
stream, sliced into blobs at timeslice boundaries, and only the very first
blob carries the initialisation data — the EBML header, ``Info`` and
``Tracks`` — that a decoder needs to make sense of anything that follows.
Splitting that byte stream at a blob boundary therefore produces one playable
file and N unplayable ones.

Three properties of Chrome's real output make the naive fixes fail, and each
one is a constraint this module is built around:

  **Blob boundaries fall inside elements.** Observed against Chrome: every
  boundary lands between a ``SimpleBlock``'s ID byte and its size, so a blob
  is not a unit of anything. Parsing has to be byte-continuous across feeds,
  which is why :meth:`WebMSegmenter.feed` keeps a partial-element buffer.

  **Re-using the first blob as a "header" duplicates audio.** That blob is
  header *plus* the opening seconds of the meeting. Prepending it to a later
  segment replays those seconds and still leaves the segment's own blocks
  carrying timestamps that do not follow from it.

  **Chrome opens a new Cluster only about every 30 seconds.** So cutting at
  cluster boundaries cannot honour a segment target shorter than that. Blocks
  are re-packed into this module's own clusters instead, which makes any block
  boundary a legal cut point.

What comes out is a remux, not a re-encode: every Opus block is copied
verbatim and exactly once, so no audio is re-compressed, dropped or repeated.
Only container framing is rewritten — clusters get their own known sizes, and
each segment's timestamps are rebased so it starts at zero rather than at its
offset into the meeting.

Bytes that do not yet form a complete element stay buffered and roll into the
next segment, so a cut never truncates a block.

If the stream turns out not to be WebM at all, the segmenter degrades to
passing bytes through untouched. A recording that is hard to split is worth
more than no recording, and the mismatch is logged as an error rather than
hidden.
"""

from __future__ import annotations

import logging
import struct

logger = logging.getLogger(__name__)

# EBML/Matroska element ids, stored with their length-marker bits intact, which
# is how they appear on the wire and how they are written back out.
_EBML_HEADER = 0x1A45DFA3
_SEGMENT = 0x18538067
_SEEK_HEAD = 0x114D9B74
_INFO = 0x1549A966
_TRACKS = 0x1654AE6B
_CLUSTER = 0x1F43B675
_CUES = 0x1C53BB6B
_ATTACHMENTS = 0x1941A469
_CHAPTERS = 0x1043A770
_TAGS = 0x1254C367

_TIMECODE = 0xE7
_SIMPLE_BLOCK = 0xA3
_BLOCK_GROUP = 0xA0
_BLOCK = 0xA1

#: Elements that sit directly under ``Segment``. A cluster written with an
#: unknown size — which is what Chrome writes — has no length to count down, so
#: it ends where the next one of these begins.
_TOP_LEVEL_IDS = frozenset(
    {_SEGMENT, _SEEK_HEAD, _INFO, _TRACKS, _CLUSTER, _CUES, _ATTACHMENTS, _CHAPTERS, _TAGS}
)

#: A block's timestamp is stored as a 16-bit signed offset from its cluster, so
#: no cluster may span more than this many ticks.
_MAX_BLOCK_OFFSET = 32_767


class _CorruptStream(Exception):
    """The bytes cannot be an element header, however many more arrive.

    Distinct from "not enough data yet", which is the ordinary case at the end
    of a feed. Conflating the two would leave the parser waiting forever on
    bytes that will never make sense, quietly swallowing the rest of the
    recording.
    """


class WebMSegmenter:
    """Re-frames a live WebM byte stream into self-contained segments.

    Feed it the recorder's bytes in order; take output with :meth:`drain` as it
    becomes available, and end a segment with :meth:`cut`. The first bytes of
    every segment are the stream's initialisation header, so each one is a
    complete file rather than a continuation of the last.

    Args:
        meeting_id: Correlation id for logging.
        target_cluster_ms: How much audio to gather into one output cluster.
            Smaller clusters mean less buffered audio and finer cut points;
            larger ones mean less framing overhead.
        max_cluster_bytes: Size ceiling for one output cluster, so an
            unexpectedly dense stream cannot grow one without bound.
    """

    def __init__(
        self,
        *,
        meeting_id: str = "",
        target_cluster_ms: int = 1_000,
        max_cluster_bytes: int = 1024 * 1024,
    ) -> None:
        self._meeting_id = meeting_id
        self._target_cluster_ms = min(target_cluster_ms, _MAX_BLOCK_OFFSET)
        self._max_cluster_bytes = max_cluster_bytes

        # Parser state.
        self._buffer = bytearray()
        self._sniffed = False
        self._passthrough = False
        self._init = bytearray()
        self._init_complete = False
        self._in_cluster = False
        self._cluster_remaining: int | None = None
        self._source_timecode = 0

        # Writer state, for the segment currently being built.
        self._out = bytearray()
        self._init_written = False
        self._segment_base: int | None = None
        self._last_timestamp = 0
        self._last_gap = 0
        self._open_blocks: list[tuple[int, bytes, int]] = []
        self._open_timecode = 0
        self._open_bytes = 0

        self._blocks_written = 0

    # ------------------------------------------------------------------
    # State
    # ------------------------------------------------------------------

    @property
    def degraded(self) -> bool:
        """True once the input stopped being parseable WebM and is passing through."""
        return self._passthrough

    @property
    def segment_duration_ms(self) -> int:
        """Audio in the current segment so far, in milliseconds of media time.

        Media time, not wall clock: it is derived from the timestamps the
        encoder wrote, so it measures the audio actually captured rather than
        how long the meeting has been running.

        A block says when it starts and not how long it lasts, so the last one
        is measured by the gap before it. Without that the count runs one block
        short, and a segment asked to end at ten seconds waits for the next
        chunk and runs to fifteen.
        """
        if self._passthrough or self._segment_base is None:
            return 0
        return self._last_timestamp + self._last_gap

    @property
    def has_segment_data(self) -> bool:
        """True when cutting now would produce a file with audio in it."""
        if self._passthrough:
            return bool(self._out)
        return bool(self._out or self._open_blocks)

    @property
    def blocks_written(self) -> int:
        """Audio blocks emitted across every segment. Diagnostics only."""
        return self._blocks_written

    # ------------------------------------------------------------------
    # Operations
    # ------------------------------------------------------------------

    def feed(self, data: bytes) -> None:
        """Take the next bytes of the recorder's stream, in order."""
        if not data:
            return

        self._buffer.extend(data)

        if self._passthrough:
            self._out.extend(self._buffer)
            self._buffer.clear()
            return

        if not self._sniffed:
            if len(self._buffer) < 4:
                return
            if int.from_bytes(self._buffer[:4], "big") != _EBML_HEADER:
                self._degrade("stream does not begin with an EBML header")
                return
            self._sniffed = True

        self._parse()

    def drain(self) -> bytes:
        """Take the bytes ready to append to the current segment's file.

        Returns everything finished since the last call: complete clusters,
        preceded by the initialisation header when this is the segment's first
        output. Blocks in the cluster still being filled are held back until
        that cluster closes or :meth:`cut` is called.
        """
        if not self._out:
            return b""
        ready = bytes(self._out)
        self._out.clear()
        return ready

    def cut(self) -> bytes:
        """End the current segment and return its remaining bytes.

        Closes the open cluster so no block is left behind, then resets the
        writer: the next :meth:`drain` starts a new file, headers first, with
        timestamps rebased to zero again. Partially received bytes stay in the
        parser and roll into that next segment rather than being lost here.
        """
        self._close_cluster()
        ready = bytes(self._out)
        self._out.clear()

        self._init_written = False
        self._segment_base = None
        self._last_timestamp = 0
        self._last_gap = 0
        return ready

    # ------------------------------------------------------------------
    # Parsing
    # ------------------------------------------------------------------

    def _parse(self) -> None:
        """Consume as many complete elements as the buffer holds."""
        buffer = self._buffer
        limit = len(buffer)
        position = 0

        while position < limit:
            try:
                if self._in_cluster:
                    consumed = self._read_cluster_child(buffer, position, limit)
                else:
                    consumed = self._read_top_level(buffer, position, limit)
            except _CorruptStream as error:
                del buffer[:position]
                self._degrade(str(error))
                return
            if consumed is None:
                break
            position += consumed

        if position:
            del buffer[:position]

    def _read_top_level(self, buffer: bytearray, position: int, limit: int) -> int | None:
        """Handle one element under ``Segment``. Returns bytes consumed."""
        header = _read_element_header(buffer, position, limit)
        if header is None:
            return None
        element_id, size, header_length = header

        if element_id == _SEGMENT:
            # A master element with an unknown size: step inside it rather than
            # over it. Its header is part of every segment's init bytes.
            self._init.extend(buffer[position : position + header_length])
            return header_length

        if element_id == _CLUSTER:
            # The first cluster marks the end of the initialisation data — the
            # standard boundary, and the one that stays correct whatever
            # optional elements a writer puts before it.
            self._init_complete = True
            self._in_cluster = True
            self._cluster_remaining = size
            self._source_timecode = 0
            return header_length

        if size is None:
            self._degrade(f"unknown-size element {element_id:#x} outside a cluster")
            return None

        total = header_length + size
        if limit - position < total:
            return None

        if not self._init_complete:
            self._init.extend(buffer[position : position + total])
        return total

    def _read_cluster_child(self, buffer: bytearray, position: int, limit: int) -> int | None:
        """Handle one element inside a cluster. Returns bytes consumed."""
        header = _read_element_header(buffer, position, limit)
        if header is None:
            return None
        element_id, size, header_length = header

        if self._cluster_remaining is None and element_id in _TOP_LEVEL_IDS:
            # The cluster had no declared length; this element ends it. Consume
            # nothing and re-read at top level, where the flag now sends it.
            self._in_cluster = False
            return 0

        if size is None:
            self._degrade(f"unknown-size element {element_id:#x} inside a cluster")
            return None

        total = header_length + size
        if limit - position < total:
            return None

        if element_id == _TIMECODE:
            self._source_timecode = int.from_bytes(buffer[position + header_length : position + total], "big")
        elif element_id == _SIMPLE_BLOCK:
            self._take_block(bytes(buffer[position : position + total]), header_length)
        elif element_id == _BLOCK_GROUP:
            self._take_block_group(bytes(buffer[position : position + total]), header_length)

        if self._cluster_remaining is not None:
            self._cluster_remaining -= total
            if self._cluster_remaining <= 0:
                self._in_cluster = False
        return total

    def _take_block(self, data: bytes, header_length: int) -> None:
        """Queue a ``SimpleBlock``, resolving its timestamp against its cluster."""
        offset = _block_timestamp_offset(data, header_length)
        if offset is None:
            logger.warning(
                "Skipping a malformed audio block",
                extra={"meeting_id": self._meeting_id, "block_bytes": len(data)},
            )
            return
        relative = struct.unpack_from(">h", data, offset)[0]
        self._append(self._source_timecode + relative, data, offset)

    def _take_block_group(self, data: bytes, header_length: int) -> None:
        """Queue a ``BlockGroup``, timestamped by the ``Block`` inside it.

        Chrome writes plain ``SimpleBlock``s for Opus, so this exists to keep
        the parser honest about the format rather than to serve a known writer.
        The group is carried whole, so its duration and reference children
        survive the remux.
        """
        position = header_length
        limit = len(data)
        while position < limit:
            try:
                header = _read_element_header(data, position, limit)
            except _CorruptStream:
                return
            if header is None:
                return
            child_id, size, child_header = header
            if size is None:
                return
            if child_id == _BLOCK:
                offset = _block_timestamp_offset(data, position + child_header)
                if offset is None:
                    return
                relative = struct.unpack_from(">h", data, offset)[0]
                self._append(self._source_timecode + relative, data, offset)
                return
            position += child_header + size

    # ------------------------------------------------------------------
    # Writing
    # ------------------------------------------------------------------

    def _append(self, timestamp: int, data: bytes, timestamp_offset: int) -> None:
        """Add one block to the segment being built, rebased to its start."""
        if self._segment_base is None:
            self._segment_base = timestamp

        # Clamped rather than dropped: a block ahead of its own segment's start
        # would be a writer bug, and losing audio is the worse failure.
        relative = max(timestamp - self._segment_base, 0)

        # Closing on the target also keeps every block's offset within the 16
        # bits it is written into, because the target itself is clamped to that
        # range in __init__.
        if self._open_blocks and (
            relative - self._open_timecode > self._target_cluster_ms
            or self._open_bytes >= self._max_cluster_bytes
        ):
            self._close_cluster()

        if not self._open_blocks:
            self._open_timecode = relative

        self._open_blocks.append((relative, data, timestamp_offset))
        self._open_bytes += len(data)
        if relative > self._last_timestamp:
            self._last_gap = relative - self._last_timestamp
            self._last_timestamp = relative

    def _close_cluster(self) -> None:
        """Write the open cluster out, with its own timecode and known size."""
        if not self._open_blocks:
            return

        if not self._init_written:
            self._out.extend(self._init)
            self._init_written = True

        body = bytearray()
        body.extend(_element(_TIMECODE, _unsigned_bytes(self._open_timecode)))
        for relative, data, timestamp_offset in self._open_blocks:
            block = bytearray(data)
            struct.pack_into(">h", block, timestamp_offset, relative - self._open_timecode)
            body.extend(block)

        self._out.extend(_element_header(_CLUSTER, len(body)))
        self._out.extend(body)

        self._blocks_written += len(self._open_blocks)
        self._open_blocks = []
        self._open_bytes = 0

    # ------------------------------------------------------------------
    # Failure
    # ------------------------------------------------------------------

    def _degrade(self, reason: str) -> None:
        """Give up on parsing and pass the remaining bytes through untouched.

        Everything already buffered still reaches the caller — the recording
        survives — but segments after the first will be continuations rather
        than standalone files, exactly as they were before this module existed.
        """
        if self._passthrough:
            return
        self._passthrough = True
        logger.error(
            "Cannot parse the recording as WebM; segments will not be independently playable",
            extra={"meeting_id": self._meeting_id, "reason": reason},
        )
        self._close_cluster()
        self._out.extend(self._buffer)
        self._buffer.clear()


# ----------------------------------------------------------------------
# EBML primitives
# ----------------------------------------------------------------------


def _read_element_header(
    data: bytes | bytearray, position: int, limit: int
) -> tuple[int, int | None, int] | None:
    """Read an element's id and size.

    Returns:
        ``(element_id, size, header_length)``, where ``size`` is None for the
        unknown-size encoding that live writers use for ``Segment`` and
        ``Cluster``. None when the header is not fully buffered yet, which is
        the normal case at the tail of a feed.

    Raises:
        _CorruptStream: If the bytes cannot be a header at all. Waiting for
            more data would not help, so the caller stops parsing rather than
            buffering the rest of the recording forever.
    """
    if position >= limit:
        return None

    id_length = _vint_length(data[position])
    if id_length is None or id_length > 4:
        raise _CorruptStream(f"invalid element id at byte {position}")
    if limit - position < id_length:
        return None
    element_id = int.from_bytes(data[position : position + id_length], "big")

    size_position = position + id_length
    if size_position >= limit:
        return None
    size_length = _vint_length(data[size_position])
    if size_length is None:
        raise _CorruptStream(f"invalid element size on {element_id:#x}")
    if limit - size_position < size_length:
        return None

    raw = int.from_bytes(data[size_position : size_position + size_length], "big")
    value = raw & ((1 << (7 * size_length)) - 1)
    unknown = value == (1 << (7 * size_length)) - 1
    return element_id, (None if unknown else value), id_length + size_length


def _vint_length(first_byte: int) -> int | None:
    """Length of a variable-size integer from its leading byte."""
    for length in range(1, 9):
        if first_byte & (0x80 >> (length - 1)):
            return length
    return None


def _block_timestamp_offset(data: bytes, payload_start: int) -> int | None:
    """Offset of a block's 16-bit timestamp field within ``data``.

    A block payload opens with a variable-length track number, so where the
    timestamp sits depends on how that number was encoded.
    """
    if payload_start >= len(data):
        return None
    track_length = _vint_length(data[payload_start])
    if track_length is None:
        return None
    offset = payload_start + track_length
    if offset + 2 > len(data):
        return None
    return offset


def _element(element_id: int, payload: bytes) -> bytes:
    """Serialise a complete element with a known size."""
    return _element_header(element_id, len(payload)) + payload


def _element_header(element_id: int, size: int) -> bytes:
    """Serialise an element's id followed by a known size."""
    return _id_bytes(element_id) + _size_vint(size)


def _id_bytes(element_id: int) -> bytes:
    """Element ids already carry their marker bits; write them as they are."""
    return element_id.to_bytes(max((element_id.bit_length() + 7) // 8, 1), "big")


def _size_vint(size: int) -> bytes:
    """Encode a size in the shortest form that is not the unknown-size pattern."""
    for length in range(1, 9):
        capacity = (1 << (7 * length)) - 1
        if size < capacity:
            return (size | (1 << (7 * length))).to_bytes(length, "big")
    raise ValueError(f"element size {size} is too large for EBML")


def _unsigned_bytes(value: int) -> bytes:
    """Big-endian minimal-width encoding of an unsigned integer."""
    return value.to_bytes(max((value.bit_length() + 7) // 8, 1), "big")
