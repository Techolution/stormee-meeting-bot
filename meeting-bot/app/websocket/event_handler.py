"""Inbound event dispatch.

The audio service can push work back to the bot — play this audio, leave that
meeting. Those events arrive on the socket and have to reach meeting logic
without the transport learning what a meeting is.

This dispatcher is the join point: the transport hands it payloads, it parses
them into typed commands, and it calls handlers registered by the meeting
layer. Both sides stay ignorant of each other.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from app.schemas.websocket import (
    EVENT_ERROR,
    EVENT_LEAVE_MEETING,
    EVENT_PLAY_AUDIO,
    PlayAudioCommand,
)
from app.websocket.connection_manager import ConnectionManager

logger = logging.getLogger(__name__)

PlayAudioHandler = Callable[[PlayAudioCommand], Awaitable[None]]
LeaveHandler = Callable[[str], Awaitable[None]]


class AudioServiceEventHandler:
    """Routes inbound audio-service events to meeting-layer callbacks.

    Unregistered events are logged and dropped rather than treated as errors:
    the audio service may broadcast events this bot version does not care
    about, and that must not be noisy.
    """

    def __init__(self, connection: ConnectionManager) -> None:
        self._connection = connection
        self._on_play_audio: PlayAudioHandler | None = None
        self._on_leave: LeaveHandler | None = None
        self._registered = False

    def register(self) -> None:
        """Subscribe to the events this handler understands. Idempotent."""
        if self._registered:
            return
        self._connection.on(EVENT_PLAY_AUDIO, self._handle_play_audio)
        self._connection.on(EVENT_LEAVE_MEETING, self._handle_leave)
        self._connection.on(EVENT_ERROR, self._handle_error)
        self._registered = True
        logger.debug("Audio service event handlers registered")

    def on_play_audio(self, handler: PlayAudioHandler) -> None:
        self._on_play_audio = handler

    def on_leave_meeting(self, handler: LeaveHandler) -> None:
        self._on_leave = handler

    # ------------------------------------------------------------------
    # Handlers
    # ------------------------------------------------------------------

    async def _handle_play_audio(self, payload: Any) -> None:
        command = PlayAudioCommand.from_wire(payload)
        if command is None:
            logger.warning("Discarded malformed playAudio event", extra={"payload_type": type(payload).__name__})
            return

        if self._on_play_audio is None:
            logger.debug("playAudio received but no handler is registered")
            return

        logger.info(
            "Audio service requested playback",
            extra={"meeting_id": command.meeting_id, "volume": command.volume},
        )
        await self._on_play_audio(command)

    async def _handle_leave(self, payload: Any) -> None:
        meeting_id = ""
        if isinstance(payload, dict):
            meeting_id = str(payload.get("meetingId") or payload.get("meeting_id") or "")

        if self._on_leave is None:
            logger.debug("leaveMeeting received but no handler is registered")
            return

        logger.info("Audio service requested meeting exit", extra={"meeting_id": meeting_id})
        await self._on_leave(meeting_id)

    async def _handle_error(self, payload: Any) -> None:
        logger.error("Audio service reported an error", extra={"detail": str(payload)[:300]})
