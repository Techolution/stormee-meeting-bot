"""Resumable upload client for signed object-storage URLs.

Recordings are streamed to object storage while the meeting is still running,
using the GCS resumable-upload protocol against a signed URL issued by CW. The
protocol has two rules that shape the code around it:

  * Every non-final block must be a multiple of 256 KiB.
  * ``Content-Range`` must describe the block's absolute byte offset within the
    object, with a total size of ``*`` until the final block declares it.

This client owns those rules. Callers hand it bytes in order and it tracks the
offset; :class:`~app.recording.chunk_uploader.ChunkUploader` handles deciding
*when* a block is ready.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import httpx

from app.core.exceptions import ChunkUploadError

logger = logging.getLogger(__name__)

#: GCS answers an accepted-but-incomplete resumable block with 308.
_STATUS_RESUME_INCOMPLETE = 308
_STATUS_COMPLETE = frozenset({200, 201})


@dataclass(slots=True)
class ResumableUploadState:
    """Byte-offset bookkeeping for one object being uploaded."""

    upload_url: str
    content_type: str
    uploaded_bytes: int = 0
    block_count: int = 0
    completed: bool = False
    _closed: bool = field(default=False, repr=False)

    @property
    def next_offset(self) -> int:
        return self.uploaded_bytes


class ResumableUploadClient:
    """Performs resumable PUTs against signed URLs."""

    service_name = "object-storage"

    def __init__(self, *, timeout_seconds: float = 300.0) -> None:
        self._timeout = timeout_seconds
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(self._timeout))
        return self._client

    async def aclose(self) -> None:
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
        self._client = None

    async def upload_block(
        self,
        state: ResumableUploadState,
        data: bytes,
        *,
        is_final: bool,
        meeting_id: str = "",
    ) -> None:
        """Append one block to the object and advance ``state``.

        Args:
            state: Upload bookkeeping. Mutated in place on success.
            data: Bytes to append at ``state.next_offset``.
            is_final: True for the last block; declares the object's total size
                and closes it. Only a final block may be shorter than 256 KiB.
            meeting_id: Correlation id for logging.

        Raises:
            ChunkUploadError: If storage rejects the block or the transport fails.
                ``state`` is left untouched so the caller can retry the same bytes.
        """
        if state.completed:
            raise ChunkUploadError(
                "upload already finalized",
                details={"meeting_id": meeting_id},
            )
        if not data and not is_final:
            return

        if not data:
            # A zero-length PUT is a *status query* in this protocol, not a
            # finalize: storage answers 308 and leaves the object open. Callers
            # must retain at least one byte for the final block — see
            # DirectChunkUploader._upload_full_blocks. Refusing here keeps the
            # mistake loud instead of surfacing as a silently unfinished upload.
            raise ChunkUploadError(
                "cannot finalize with an empty block: a zero-length request queries "
                "status rather than closing the object",
                details={"meeting_id": meeting_id, "uploaded_bytes": state.uploaded_bytes},
            )

        start = state.next_offset
        end = start + len(data) - 1
        # Only the final request may declare the total; until then the size is
        # unknown and every block must say so.
        total = str(start + len(data)) if is_final else "*"
        content_range = f"bytes {start}-{end}/{total}"

        headers = {
            "Content-Type": state.content_type,
            "Content-Length": str(len(data)),
            "Content-Range": content_range,
        }

        log_fields = {
            "meeting_id": meeting_id,
            "block_bytes": len(data),
            "content_range": content_range,
            "is_final": is_final,
        }

        client = await self._get_client()
        try:
            response = await client.put(state.upload_url, content=data, headers=headers)
        except httpx.HTTPError as error:
            logger.error("Resumable upload transport error", extra=log_fields, exc_info=error)
            raise ChunkUploadError(
                f"transport error during resumable upload: {error}",
                details=log_fields,
            ) from error

        if response.status_code == _STATUS_RESUME_INCOMPLETE and not is_final:
            state.uploaded_bytes += len(data)
            state.block_count += 1
            logger.debug("Resumable block accepted", extra={**log_fields, "total_bytes": state.uploaded_bytes})
            return

        if response.status_code in _STATUS_COMPLETE:
            state.uploaded_bytes += len(data)
            state.block_count += 1
            state.completed = True
            logger.info(
                "Resumable upload complete",
                extra={**log_fields, "total_bytes": state.uploaded_bytes, "blocks": state.block_count},
            )
            return

        # 308 on a final block means storage still expects more bytes — treat as
        # a failure so the caller does not report a truncated object as complete.
        body = response.text[:300] if response.content else ""

        # On a 308, storage reports what it actually holds in `Range`. Comparing
        # it with our offset is the difference between "we disagree about the
        # byte count" and "the request was malformed", so it belongs in the log.
        acknowledged = response.headers.get("Range", "")
        failure = {
            **log_fields,
            "status": response.status_code,
            "body": body,
            "storage_ack_range": acknowledged or None,
            "our_offset": state.uploaded_bytes,
        }
        logger.error("Resumable upload rejected", extra=failure)
        raise ChunkUploadError(
            f"object storage returned {response.status_code} for {content_range}",
            details=failure,
        )
