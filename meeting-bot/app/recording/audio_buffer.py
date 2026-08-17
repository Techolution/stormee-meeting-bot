"""Bounded buffer for chunks that could not be sent yet.

When the audio service is unreachable the recorder keeps producing audio. That
audio has to go somewhere with a hard ceiling: a bot pod has a fixed memory
budget, and an unbounded buffer during a long outage takes the pod down and
loses the meeting entirely.

The buffer therefore enforces two limits at once — a chunk count and a byte
total — and drops from the head when either is hit. Dropping the oldest audio
is the right trade: the tail is what is still arriving, and a recording with a
gap is more useful than no recording.

One buffer per recording. The previous implementation shared a single global
queue across every meeting the pod handled, which interleaved chunks from
different meetings into each other's uploads.
"""

from __future__ import annotations

import logging
from collections import deque
from collections.abc import Iterator

from app.recording.models import AudioChunk

logger = logging.getLogger(__name__)


class AudioBuffer:
    """FIFO buffer with dual capacity limits and head-drop overflow."""

    def __init__(self, *, max_chunks: int = 100, max_memory_bytes: int = 10 * 1024 * 1024) -> None:
        if max_chunks <= 0:
            raise ValueError("max_chunks must be positive")
        if max_memory_bytes <= 0:
            raise ValueError("max_memory_bytes must be positive")

        self._max_chunks = max_chunks
        self._max_memory_bytes = max_memory_bytes
        self._chunks: deque[AudioChunk] = deque()
        self._bytes = 0
        self._dropped = 0

    # ------------------------------------------------------------------
    # State
    # ------------------------------------------------------------------

    def __len__(self) -> int:
        return len(self._chunks)

    def __iter__(self) -> Iterator[AudioChunk]:
        return iter(self._chunks)

    @property
    def is_empty(self) -> bool:
        return not self._chunks

    @property
    def size_bytes(self) -> int:
        return self._bytes

    @property
    def dropped_count(self) -> int:
        """Chunks discarded to stay within capacity since this buffer was created."""
        return self._dropped

    @property
    def is_at_capacity(self) -> bool:
        return len(self._chunks) >= self._max_chunks or self._bytes >= self._max_memory_bytes

    @property
    def utilisation(self) -> float:
        """Fill level as a fraction, taking whichever limit is closer."""
        by_count = len(self._chunks) / self._max_chunks
        by_bytes = self._bytes / self._max_memory_bytes
        return max(by_count, by_bytes)

    # ------------------------------------------------------------------
    # Operations
    # ------------------------------------------------------------------

    def append(self, chunk: AudioChunk) -> bool:
        """Buffer a chunk, evicting from the head if it would exceed a limit.

        Returns:
            True if nothing was evicted; False if the buffer had to drop audio.
        """
        evicted = 0
        while self._chunks and self._would_exceed(chunk.size_bytes):
            dropped = self._chunks.popleft()
            self._bytes -= dropped.size_bytes
            self._dropped += 1
            evicted += 1

        self._chunks.append(chunk)
        self._bytes += chunk.size_bytes

        if evicted:
            logger.warning(
                "Audio buffer at capacity; dropped oldest chunks",
                extra={
                    "meeting_id": chunk.meeting_id,
                    "dropped_now": evicted,
                    "dropped_total": self._dropped,
                    "buffered_chunks": len(self._chunks),
                    "buffered_bytes": self._bytes,
                },
            )
            return False

        logger.debug(
            "Chunk buffered",
            extra={
                "meeting_id": chunk.meeting_id,
                "chunk_id": chunk.chunk_id,
                "buffered_chunks": len(self._chunks),
                "buffered_bytes": self._bytes,
            },
        )
        return True

    def _would_exceed(self, incoming_bytes: int) -> bool:
        return (
            len(self._chunks) >= self._max_chunks
            or self._bytes + incoming_bytes > self._max_memory_bytes
        )

    def pop(self) -> AudioChunk | None:
        """Remove and return the oldest chunk, or ``None`` when empty."""
        if not self._chunks:
            return None
        chunk = self._chunks.popleft()
        self._bytes -= chunk.size_bytes
        return chunk

    def drain(self) -> list[AudioChunk]:
        """Remove and return every buffered chunk, oldest first."""
        chunks = list(self._chunks)
        self._chunks.clear()
        self._bytes = 0
        if chunks:
            logger.info("Drained audio buffer", extra={"chunk_count": len(chunks)})
        return chunks

    def restore(self, chunks: list[AudioChunk]) -> None:
        """Put chunks back at the head after a failed send.

        Order is preserved so the sequence stays intact for the retry.
        """
        for chunk in reversed(chunks):
            self._chunks.appendleft(chunk)
            self._bytes += chunk.size_bytes
        if chunks:
            logger.debug("Restored chunks to buffer", extra={"chunk_count": len(chunks)})

    def clear(self) -> None:
        """Discard everything. Used when a recording is abandoned."""
        count = len(self._chunks)
        self._chunks.clear()
        self._bytes = 0
        if count:
            logger.info("Cleared audio buffer", extra={"discarded_chunks": count})

    def stats(self) -> dict[str, int | float]:
        return {
            "buffered_chunks": len(self._chunks),
            "buffered_bytes": self._bytes,
            "dropped_chunks": self._dropped,
            "utilisation": round(self.utilisation, 3),
            "max_chunks": self._max_chunks,
            "max_memory_bytes": self._max_memory_bytes,
        }
