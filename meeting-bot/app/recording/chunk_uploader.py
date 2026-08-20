"""Chunk upload.

Two transports, one interface. Which one a deployment uses is configuration,
not a code path callers know about:

  ``websocket``  Stream chunks to the external audio service, which owns
                 object-storage ingest. This is the normal production topology
                 and the default.
  ``direct``     Perform the resumable upload from this process. Used where no
                 audio service is deployed, and as the fallback that keeps this
                 bot independently runnable.

Both implement :class:`ChunkUploader`, so
:class:`~app.recording.recorder.Recorder` never branches on transport.

The uploader is also where the "chunk produced" concern ends. It knows how to
persist a chunk; it does not know that a completed recording triggers artifact
generation or email — that belongs to
:class:`~app.recording.upload_finalizer.UploadFinalizer`.

Container framing is likewise not its concern: a recording split into segments
has to be re-framed so each segment is a playable file rather than a slice of
one, and that belongs to
:class:`~app.recording.webm_segmenter.WebMSegmenter`.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from abc import ABC, abstractmethod

from app.clients.audio_service import AudioServiceClient
from app.clients.cw_utils import CWUtilsClient, ResumableUploadTarget
from app.clients.object_storage import ResumableUploadClient, ResumableUploadState
from app.core.exceptions import ChunkUploadError, WebSocketNotConnectedError
from app.recording.audio_buffer import AudioBuffer
from app.recording.models import AudioChunk, RecordingContext, RecordingStats
from app.recording.sequencer import ChunkSequencer
from app.recording.webm_segmenter import WebMSegmenter

logger = logging.getLogger(__name__)


class ChunkUploader(ABC):
    """Persists audio chunks somewhere durable."""

    #: Transport identifier, surfaced on the status endpoint.
    transport: str = "unknown"

    @abstractmethod
    async def start(self, context: RecordingContext) -> None:
        """Prepare for a recording. Called once, before the first chunk."""

    @abstractmethod
    async def upload(self, chunk: AudioChunk) -> None:
        """Persist one chunk, or buffer it for a later attempt.

        Must not raise for a recoverable failure — the recorder cannot pause
        the meeting while storage recovers.
        """

    @abstractmethod
    async def finalize(self) -> UploadOutcome:
        """Flush everything outstanding and close the upload."""

    @abstractmethod
    def pending_count(self) -> int:
        """Chunks captured but not yet persisted."""

    @abstractmethod
    async def reinitialize(self, context: RecordingContext) -> None:
        """Re-initialize the uploader for the next segment.
        
        Called after auto-uploading a segment, to prepare for the next segment.
        For resumable uploads, this creates a fresh resumable URL.
        For streaming, this resets any internal state.
        
        Args:
            context: Recording context for the new segment.
        """

    async def flush_buffered(self) -> int:
        """Retry anything held back. Called after the transport recovers.

        Returns:
            The number of chunks successfully sent.
        """
        return 0

    def segment_duration_seconds(self) -> float | None:
        """Audio captured into the current segment, in seconds of media time.

        Media time is what a segment should be measured by: it counts the audio
        the encoder actually produced, so a stalled capture does not advance it
        the way a wall clock would.

        Returns:
            None when the transport cannot know — it is forwarding opaque bytes
            rather than parsing them — leaving the caller to fall back to wall
            clock.
        """
        return None


class UploadOutcome:
    """What finalization achieved.

    ``complete`` is the question that matters: it drives whether downstream
    processing should be triggered.
    """

    __slots__ = ("complete", "detail", "pending_chunks", "public_url", "uploaded_bytes", "uploaded_chunks")

    def __init__(
        self,
        *,
        complete: bool,
        uploaded_chunks: int = 0,
        uploaded_bytes: int = 0,
        pending_chunks: int = 0,
        public_url: str | None = None,
        detail: str = "",
    ) -> None:
        self.complete = complete
        self.uploaded_chunks = uploaded_chunks
        self.uploaded_bytes = uploaded_bytes
        self.pending_chunks = pending_chunks
        self.public_url = public_url
        self.detail = detail

    def as_dict(self) -> dict[str, object]:
        return {
            "complete": self.complete,
            "uploaded_chunks": self.uploaded_chunks,
            "uploaded_bytes": self.uploaded_bytes,
            "pending_chunks": self.pending_chunks,
            "public_url": self.public_url,
            "detail": self.detail,
        }


class StreamingChunkUploader(ChunkUploader):
    """Streams chunks to the audio service, buffering across disconnects.

    Ordering is the audio service's problem in this mode; this side guarantees
    only that every chunk is offered at least once and that chunks buffered
    during an outage are replayed in order.
    """

    transport = "websocket"

    def __init__(
        self,
        *,
        audio_service: AudioServiceClient,
        buffer: AudioBuffer,
        stats: RecordingStats,
    ) -> None:
        self._audio_service = audio_service
        self._buffer = buffer
        self._stats = stats
        self._context: RecordingContext | None = None

    async def start(self, context: RecordingContext) -> None:
        self._context = context
        logger.info(
            "Streaming recording to the audio service",
            extra={"meeting_id": context.meeting_id},
        )

    async def upload(self, chunk: AudioChunk) -> None:
        """Send a chunk, buffering it if the link is down."""
        if not self._audio_service.is_connected:
            self._buffer.append(chunk)
            return

        try:
            await self._audio_service.send_audio_chunk(chunk.as_wire_payload())
        except WebSocketNotConnectedError:
            self._buffer.append(chunk)
            return
        except Exception as error:  # noqa: BLE001 - buffered and retried later
            logger.warning(
                "Chunk send failed; buffering for retry",
                extra={"meeting_id": chunk.meeting_id, "chunk_id": chunk.chunk_id, "reason": str(error)},
            )
            self._buffer.append(chunk)
            return

        self._stats.chunks_uploaded += 1
        self._stats.bytes_uploaded += chunk.size_bytes

    async def flush_buffered(self) -> int:
        """Replay buffered chunks in order.

        Stops at the first failure and restores the remainder, so a link that
        drops mid-drain does not scatter the sequence.
        """
        if self._buffer.is_empty:
            return 0

        # Checked up front so an offline flush does not drain the buffer only to
        # put every chunk straight back.
        if not self._audio_service.is_connected:
            logger.debug(
                "Skipping buffer drain: audio service not connected",
                extra={"buffered_chunks": len(self._buffer)},
            )
            return 0

        pending = self._buffer.drain()
        logger.info("Draining buffered chunks", extra={"chunk_count": len(pending)})

        for index, chunk in enumerate(pending):
            try:
                await self._audio_service.send_audio_chunk(chunk.as_wire_payload())
            except Exception as error:  # noqa: BLE001 - remainder is preserved below
                logger.warning(
                    "Buffer drain interrupted",
                    extra={
                        "meeting_id": chunk.meeting_id,
                        "chunk_id": chunk.chunk_id,
                        "sent": index,
                        "remaining": len(pending) - index,
                        "reason": str(error),
                    },
                )
                self._buffer.restore(pending[index:])
                return index

            self._stats.chunks_uploaded += 1
            self._stats.bytes_uploaded += chunk.size_bytes

        logger.info("Buffer drained", extra={"chunk_count": len(pending)})
        return len(pending)

    async def finalize(self) -> UploadOutcome:
        """Drain the buffer. The audio service closes the object itself."""
        drained = await self.flush_buffered()
        pending = len(self._buffer)

        if pending:
            logger.warning(
                "Recording finalized with chunks still buffered",
                extra={"pending_chunks": pending, "drained": drained},
            )

        return UploadOutcome(
            complete=pending == 0,
            uploaded_chunks=self._stats.chunks_uploaded,
            uploaded_bytes=self._stats.bytes_uploaded,
            pending_chunks=pending,
            detail="audio service owns object finalization",
        )

    def pending_count(self) -> int:
        return len(self._buffer)

    async def reinitialize(self, context: RecordingContext) -> None:
        """Re-initialize the uploader for the next segment.
        
        For streaming mode, re-initialization means resetting context
        and clearing any internal state. The audio service will handle
        creating new logical segments on the remote end.
        """
        self._context = context
        # Buffer is preserved to handle any chunks that arrived during transition
        
        logger.info(
            "Streaming uploader re-initialized for next segment",
            extra={"meeting_id": context.meeting_id, "buffered_chunks": len(self._buffer)},
        )


class DirectChunkUploader(ChunkUploader):
    """Uploads to object storage from this process using the resumable protocol.

    Bytes pass through a :class:`~app.recording.webm_segmenter.WebMSegmenter` on
    the way out. For a recording that is never split that changes nothing
    observable; for one that is, it is what makes each uploaded object a file
    in its own right instead of a slice of a stream that only the first object
    can decode.
    """

    transport = "direct"

    def __init__(
        self,
        *,
        cw_client: CWUtilsClient,
        storage: ResumableUploadClient,
        stats: RecordingStats,
        block_size_bytes: int = 256 * 1024,
        content_type: str = "audio/webm;codecs=opus",
        final_block_attempts: int = 3,
        final_block_retry_seconds: float = 0.5,
    ) -> None:
        self._cw = cw_client
        self._storage = storage
        self._stats = stats
        self._block_size = block_size_bytes
        self._content_type = content_type
        self._final_attempts = max(final_block_attempts, 1)
        self._final_retry_seconds = final_block_retry_seconds

        self._context: RecordingContext | None = None
        self._sequencer: ChunkSequencer | None = None
        self._segmenter: WebMSegmenter | None = None
        self._target: ResumableUploadTarget | None = None
        self._state: ResumableUploadState | None = None
        self._pending_bytes = bytearray()
        #: Bytes closed off in earlier segments. ``_state`` only counts the
        #: object currently open, and each segment opens a new one.
        self._uploaded_base = 0
        self._failed = False

        self._lock = asyncio.Lock()

    async def start(self, context: RecordingContext) -> None:
        """Prepare sequencing and framing. The object itself is reserved on first use."""
        self._context = context
        if self._sequencer is None:
            self._sequencer = ChunkSequencer(meeting_id=context.meeting_id)
        self._segmenter = WebMSegmenter(meeting_id=context.meeting_id)
        self._pending_bytes.clear()
        self._uploaded_base = 0
        self._failed = False
        logger.info(
            "Uploading recording directly to object storage",
            extra={"meeting_id": context.meeting_id},
        )

    async def _ensure_target(self) -> bool:
        """Create the upload target on first use."""
        if self._state is not None:
            return True
        if self._context is None:
            return False

        project_id = self._context.project_id
        if not project_id:
            logger.error(
                "Cannot upload recording: no project id on the recording context",
                extra={"meeting_id": self._context.meeting_id},
            )
            self._failed = True
            return False

        filename = _object_name(self._context.meeting_id)
        try:
            self._target = await self._cw.create_resumable_upload(
                project_id=project_id,
                filename=filename,
                content_type=self._content_type,
            )
        except Exception as error:
            logger.error(
                "Could not create an upload target; recording will not be persisted",
                exc_info=error,
                extra={"meeting_id": self._context.meeting_id},
            )
            self._failed = True
            return False

        self._state = ResumableUploadState(
            upload_url=self._target.upload_url,
            content_type=self._content_type,
        )
        return True

    async def upload(self, chunk: AudioChunk) -> None:
        """Sequence the chunk, re-frame it, and upload any full blocks it completes."""
        async with self._lock:
            if self._failed or self._sequencer is None or self._segmenter is None:
                return

            if not self._sequencer.accept(chunk):
                return

            for ready in self._sequencer.release_ready():
                self._segmenter.feed(ready.data)
            self._pending_bytes.extend(self._segmenter.drain())

            # Reserving the object is deferred until there is something to put
            # in it. The segmenter holds the opening blocks back until it can
            # close a cluster, and a recording that ends inside that window
            # should not leave an empty upload behind.
            if not self._pending_bytes:
                return
            if not await self._ensure_target():
                return

            await self._upload_full_blocks()

    async def _upload_full_blocks(self) -> None:
        """Send complete blocks, holding back unaligned trailing bytes."""
        assert self._state is not None

        if self._state.completed:
            # This segment's object is already sealed, so these bytes are the
            # start of the next one. Hold them until reinitialize opens it.
            return

        while len(self._pending_bytes) > self._block_size:
            block = bytes(self._pending_bytes[: self._block_size])
            try:
                await self._storage.upload_block(
                    self._state,
                    block,
                    is_final=False,
                    meeting_id=self._context.meeting_id if self._context else "",
                )
            except ChunkUploadError as error:
                logger.error("Block upload failed; will retry on the next chunk", extra={"reason": str(error)})
                return

            del self._pending_bytes[: self._block_size]
            self._stats.chunks_uploaded += 1
            self._stats.bytes_uploaded = self._uploaded_base + self._state.uploaded_bytes

    async def finalize(self) -> UploadOutcome:
        """Close the current segment: flush its remaining bytes and seal the object."""
        async with self._lock:
            return await self._finalize_locked()

    async def _finalize_locked(self) -> UploadOutcome:
        if self._failed or self._sequencer is None or self._segmenter is None:
            return UploadOutcome(
                complete=False,
                detail="upload target unavailable" if self._failed else "upload was never initialised",
            )

        for chunk in self._sequencer.release_all():
            self._segmenter.feed(chunk.data)

        # Ends the segment, which is what makes the object standalone: the
        # cluster still being filled is written out here, and whatever the
        # recorder produces next begins a fresh file with its own header.
        self._pending_bytes.extend(self._segmenter.cut())

        meeting_id = self._context.meeting_id if self._context else ""
        uploaded_before = self._state.uploaded_bytes if self._state is not None else 0

        if not self._pending_bytes and uploaded_before == 0:
            logger.warning(
                "Recording produced no audio; nothing to finalize",
                extra={"meeting_id": meeting_id},
            )
            return UploadOutcome(complete=False, detail="no audio was captured")

        if not await self._ensure_target():
            return UploadOutcome(complete=False, detail="upload target unavailable")

        await self._upload_full_blocks()
        assert self._state is not None

        error = await self._close_object(meeting_id)
        if error is not None:
            logger.error(
                "Final block upload failed; recording is incomplete",
                extra={
                    "meeting_id": meeting_id,
                    "reason": str(error),
                    "attempts": self._final_attempts,
                    "discarded_bytes": len(self._pending_bytes),
                },
            )
            # Dropped rather than carried forward: these bytes continue an
            # object that never closed, so they cannot be replayed into the
            # next segment, whose file begins with its own header.
            self._pending_bytes.clear()
            return UploadOutcome(
                complete=False,
                uploaded_chunks=self._state.block_count,
                uploaded_bytes=self._state.uploaded_bytes,
                pending_chunks=self._sequencer.pending_count,
                detail=str(error),
            )

        self._pending_bytes.clear()
        self._stats.bytes_uploaded = self._uploaded_base + self._state.uploaded_bytes

        logger.info(
            "Recording upload complete",
            extra={
                "meeting_id": meeting_id,
                "blocks": self._state.block_count,
                "bytes": self._state.uploaded_bytes,
            },
        )

        return UploadOutcome(
            complete=True,
            uploaded_chunks=self._state.block_count,
            uploaded_bytes=self._state.uploaded_bytes,
            pending_chunks=0,
            public_url=self._target.public_url if self._target else None,
        )

    async def _close_object(self, meeting_id: str) -> ChunkUploadError | None:
        """Send the block that seals the object, retrying a transient refusal.

        Every other block gets a free retry: its bytes stay pending and the next
        chunk attempts them again. The block that closes a segment has no next
        chunk behind it, so a single refused request would cost everything
        captured since the last accepted block, which on a long segment is
        minutes of audio. Retrying the same bytes at the same offset is what the
        resumable protocol is built for.

        Returns:
            None once storage accepts the block, or the last error if every
            attempt was refused.
        """
        assert self._state is not None
        last_error: ChunkUploadError | None = None

        for attempt in range(1, self._final_attempts + 1):
            try:
                await self._storage.upload_block(
                    self._state,
                    bytes(self._pending_bytes),
                    is_final=True,
                    meeting_id=meeting_id,
                )
                return None
            except ChunkUploadError as error:
                last_error = error
                if attempt < self._final_attempts:
                    logger.warning(
                        "Could not close the recording object; retrying",
                        extra={
                            "meeting_id": meeting_id,
                            "attempt": attempt,
                            "of": self._final_attempts,
                            "reason": str(error),
                        },
                    )
                    await asyncio.sleep(self._final_retry_seconds * attempt)

        return last_error

    def pending_count(self) -> int:
        return self._sequencer.pending_count if self._sequencer else 0

    def segment_duration_seconds(self) -> float | None:
        """Media time captured into the segment currently being uploaded."""
        if self._segmenter is None or self._segmenter.degraded:
            return None
        return self._segmenter.segment_duration_ms / 1000.0

    async def reinitialize(self, context: RecordingContext) -> None:
        """Point the uploader at a fresh object for the next segment.

        Only the *upload* is reset. The segmenter keeps reading the recorder's
        stream without interruption — ``finalize`` already ended the previous
        segment on it — so the next bytes it emits open a new, self-contained
        file and no audio is dropped across the boundary.

        Anything still pending here arrived *after* that cut, from a chunk that
        raced finalization, and so already belongs to the new segment. It is
        kept and uploaded as the new object's opening bytes; finalize is what
        clears bytes belonging to the object it closed.
        """
        self._context = context
        async with self._lock:
            if self._state is not None:
                self._uploaded_base += self._state.uploaded_bytes

            self._target = None
            self._state = None
            self._failed = False

        logger.info(
            "Uploader ready for the next segment",
            extra={
                "meeting_id": context.meeting_id,
                "carried_over_bytes": len(self._pending_bytes),
            },
        )



def _object_name(meeting_id: str) -> str:
    """Build a collision-free object name for a recording.

    The meeting id alone is not safe: it can contain path separators, and a
    meeting recorded twice would otherwise overwrite its first recording.
    Display names are handled separately via the CW API's display_name parameter.
    """
    safe = meeting_id.replace("/", "_").replace(":", "_").strip() or "meeting"
    return f"{safe}_{uuid.uuid4()}.webm"
