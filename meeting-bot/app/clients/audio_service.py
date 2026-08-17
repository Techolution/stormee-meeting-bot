"""Contract with the external audio service.

The audio service is a separately deployed process that ingests streamed audio
and owns object-storage upload on the bot's behalf. This module describes
*what* the bot says to it — the event names and payload shapes — while
:mod:`app.websocket` owns *how* the connection is maintained.

Splitting the two matters because they change for different reasons: the
protocol changes when the audio service adds a feature; the transport changes
when connection handling needs work.

Payloads arrive here already serialised. A client is an outer layer and must not
import a domain model, so translating an ``AudioChunk`` into wire form is the
caller's job — see :meth:`~app.recording.models.AudioChunk.as_wire_payload`.
"""

from __future__ import annotations

import logging
from typing import Any

from app.core.exceptions import WebSocketNotConnectedError
from app.schemas.websocket import (
    EVENT_AUDIO_CHUNK,
    EVENT_RECORDING_ENDED,
    EVENT_TRANSCRIPT_SEGMENT,
    RecordingEndedAck,
    RecordingEndedEvent,
)
from app.websocket.connection_manager import ConnectionManager

logger = logging.getLogger(__name__)


class AudioServiceClient:
    """Typed facade over the audio service's Socket.IO API."""

    def __init__(self, connection: ConnectionManager) -> None:
        self._connection = connection

    @property
    def is_connected(self) -> bool:
        return self._connection.is_connected

    async def send_audio_chunk(self, payload: dict[str, Any]) -> None:
        """Stream one audio chunk.

        Args:
            payload: Wire-form chunk, from ``AudioChunk.as_wire_payload()``.

        Raises:
            WebSocketNotConnectedError: If the connection is down. Callers are
                expected to buffer and retry — see
                :class:`~app.recording.audio_buffer.AudioBuffer`.
        """
        await self._connection.emit(EVENT_AUDIO_CHUNK, payload)

    async def send_transcript_segment(self, payload: dict[str, Any]) -> None:
        """Stream one transcript segment. Best-effort; drops silently when offline."""
        if not self.is_connected:
            logger.debug("Skipping transcript publish: audio service not connected")
            return
        try:
            await self._connection.emit(EVENT_TRANSCRIPT_SEGMENT, payload)
        except WebSocketNotConnectedError:
            logger.debug("Transcript publish skipped: connection dropped mid-send")

    async def notify_recording_ended(
        self,
        event: RecordingEndedEvent,
        *,
        timeout_seconds: float = 30.0,
    ) -> RecordingEndedAck | None:
        """Tell the audio service the recording is finished and wait for its acknowledgement.

        The acknowledgement is what confirms that every chunk was persisted, so
        this is a request/response call rather than a fire-and-forget emit.

        Returns:
            The parsed acknowledgement, or ``None`` if the service was
            unreachable or answered with something unusable. A ``None`` here is
            a warning, not a failure — the meeting has already ended.
        """
        if not self.is_connected:
            logger.warning(
                "Cannot notify recording end: audio service not connected",
                extra={"meeting_id": event.meeting_id},
            )
            return None

        try:
            raw = await self._connection.call(
                EVENT_RECORDING_ENDED,
                event.as_wire_payload(),
                timeout_seconds=timeout_seconds,
            )
        except Exception as error:  # noqa: BLE001 - the meeting is already over
            logger.warning(
                "Audio service did not acknowledge recording end",
                extra={"meeting_id": event.meeting_id, "reason": str(error)},
            )
            return None

        ack = RecordingEndedAck.from_wire(raw)
        logger.info(
            "Audio service acknowledged recording end",
            extra={
                "meeting_id": event.meeting_id,
                "ack_status": ack.status,
                "uploaded_chunks": ack.uploaded_chunks,
                "uploaded_bytes": ack.uploaded_bytes,
            },
        )
        return ack
