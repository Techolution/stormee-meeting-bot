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

    async def flush_buffered(self) -> int:
        """Retry anything held back. Called after the transport recovers.

        Returns:
            The number of chunks successfully sent.
        """
        return 0


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


class DirectChunkUploader(ChunkUploader):
    """Uploads to object storage from this process using the resumable protocol.

    Ordering and block sizing are enforced here:

      * :class:`~app.recording.sequencer.ChunkSequencer` guarantees chunks are
        concatenated in sequence.
      * Bytes accumulate until a full 256 KiB block is available, because
        storage rejects a short non-final block.
      * The final flush declares the object's total size and closes it.
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
    ) -> None:
        self._cw = cw_client
        self._storage = storage
        self._stats = stats
        self._block_size = block_size_bytes
        self._content_type = content_type

        self._context: RecordingContext | None = None
        self._sequencer: ChunkSequencer | None = None
        self._target: ResumableUploadTarget | None = None
        self._state: ResumableUploadState | None = None
        self._pending_bytes = bytearray()
        self._failed = False

        # The page delivers chunks through an exposed callback, and Playwright
        # dispatches each call as its own task — so `upload` runs concurrently.
        # Everything it touches is order-dependent: reserving the object must
        # happen once, and bytes must reach storage at strictly increasing
        # offsets. Without this lock two chunks arriving together each reserve
        # their own object and the recording is split across both.
        self._lock = asyncio.Lock()

    async def start(self, context: RecordingContext) -> None:
        """Reserve the object and prepare sequencing."""
        self._context = context
        self._sequencer = ChunkSequencer(meeting_id=context.meeting_id)
        self._pending_bytes.clear()
        self._failed = False
        logger.info(
            "Uploading recording directly to object storage",
            extra={"meeting_id": context.meeting_id},
        )

    async def _ensure_target(self) -> bool:
        """Create the upload target on first use.

        Deferred until the first chunk so a meeting that is never recorded does
        not reserve an object.
        """
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
        """Sequence the chunk and upload any full blocks it completes.

        Serialised: concurrent callers would otherwise reserve duplicate objects
        and interleave their blocks, and the resumable protocol accepts bytes at
        exactly one offset at a time.
        """
        async with self._lock:
            if self._failed or self._sequencer is None:
                return
            if not await self._ensure_target():
                return

            if not self._sequencer.accept(chunk):
                return

            for ready in self._sequencer.release_ready():
                self._pending_bytes.extend(ready.data)

            await self._upload_full_blocks()

    async def _upload_full_blocks(self) -> None:
        """Send complete blocks, always holding at least one byte back.

        The comparison is ``>`` rather than ``>=`` on purpose. Only the final
        request may declare the object's total size, and a request that declares
        it must carry data: a zero-length ``PUT`` with ``Content-Range:
        bytes */TOTAL`` is a *status query* in the resumable protocol, which
        answers 308 and leaves the object open rather than closing it.

        Draining to exactly empty is therefore only safe if more data is coming,
        and at finalize time none is. Retaining a byte guarantees the final block
        is non-empty for any recording that captured anything at all — including
        one whose length happens to be an exact multiple of the block size, which
        is the case that used to fail.
        """
        assert self._state is not None

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
                # Leave the bytes in place: the resumable protocol requires this
                # exact block at this exact offset, so the retry must be identical.
                logger.error("Block upload failed; will retry on the next chunk", extra={"reason": str(error)})
                return

            del self._pending_bytes[: self._block_size]
            self._stats.chunks_uploaded += 1
            self._stats.bytes_uploaded = self._state.uploaded_bytes

    async def finalize(self) -> UploadOutcome:
        """Flush remaining bytes as the final block and close the object.

        Takes the same lock as :meth:`upload`: a chunk still in flight when the
        recorder stops would otherwise append to the buffer after the final
        block had been sent, and the object is closed by then.
        """
        async with self._lock:
            return await self._finalize_locked()

    async def _finalize_locked(self) -> UploadOutcome:
        if self._failed or self._state is None or self._sequencer is None:
            return UploadOutcome(
                complete=False,
                detail="upload was never initialised" if not self._failed else "upload target unavailable",
            )

        # Anything still held for ordering has to go out now; nothing more is coming.
        for chunk in self._sequencer.release_all():
            self._pending_bytes.extend(chunk.data)

        await self._upload_full_blocks()

        meeting_id = self._context.meeting_id if self._context else ""

        # Nothing was ever captured. There is no object to close, and a
        # zero-length finalize would be a status query rather than a finalize.
        if not self._pending_bytes and self._state.uploaded_bytes == 0:
            logger.warning(
                "Recording produced no audio; nothing to finalize",
                extra={"meeting_id": meeting_id},
            )
            return UploadOutcome(complete=False, detail="no audio was captured")

        try:
            await self._storage.upload_block(
                self._state,
                bytes(self._pending_bytes),
                is_final=True,
                meeting_id=meeting_id,
            )
        except ChunkUploadError as error:
            logger.error(
                "Final block upload failed; recording is incomplete",
                extra={"meeting_id": meeting_id, "reason": str(error)},
            )
            return UploadOutcome(
                complete=False,
                uploaded_chunks=self._state.block_count,
                uploaded_bytes=self._state.uploaded_bytes,
                pending_chunks=self._sequencer.pending_count,
                detail=str(error),
            )

        self._pending_bytes.clear()
        self._stats.bytes_uploaded = self._state.uploaded_bytes

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

    def pending_count(self) -> int:
        return self._sequencer.pending_count if self._sequencer else 0


def _object_name(meeting_id: str) -> str:
    """Build a collision-free object name for a recording.

    The meeting id alone is not safe: it can contain path separators, and a
    meeting recorded twice would otherwise overwrite its first recording.
    """
    safe = meeting_id.replace("/", "_").replace(":", "_").strip() or "meeting"
    return f"{safe}_{uuid.uuid4()}.webm"
