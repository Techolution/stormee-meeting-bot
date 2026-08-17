"""Connection lifecycle and supervision.

The client below this knows how to hold one connection open. This module keeps
a connection *available*: it retries the initial connect, notices drops, and
reconnects in the background under the policy in
:mod:`app.websocket.reconnection`.

Reconnection is what makes buffering worthwhile. When the socket drops, the
recorder keeps producing chunks into a buffer; the ``on_reconnect`` callback
registered here is what drains that buffer once the link is back. Without
active supervision the buffer only ever drains at end of recording, which is
what happened before this module existed.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any

from app.core.config import WebSocketSettings
from app.core.exceptions import WebSocketError, WebSocketNotConnectedError
from app.core.tasks import TaskSupervisor
from app.websocket.client import EventHandler, WebSocketClient
from app.websocket.models import ConnectionInfo, ConnectionState
from app.websocket.reconnection import ErrorKind, ReconnectionPolicy, classify_error

logger = logging.getLogger(__name__)

ReconnectCallback = Callable[[], Awaitable[None]]

_SUPERVISOR_TASK = "reconnect"


class ConnectionManager:
    """Keeps a connection to the audio service available."""

    def __init__(
        self,
        settings: WebSocketSettings,
        *,
        owner: str = "websocket",
    ) -> None:
        self._settings = settings
        self._client = WebSocketClient(
            url=settings.url,
            socketio_path=settings.path,
            connect_timeout_seconds=settings.connect_timeout_seconds,
            request_timeout_seconds=settings.request_timeout_seconds,
        )
        self._policy = ReconnectionPolicy(
            initial_delay_ms=settings.reconnect_initial_delay_ms,
            backoff_factor=settings.reconnect_backoff_factor,
            max_delay_ms=settings.reconnect_max_delay_ms,
            max_attempts=settings.max_reconnect_attempts,
        )
        self._tasks = TaskSupervisor(owner)

        self._state = ConnectionState.DISCONNECTED
        self._connected_at: datetime | None = None
        self._last_error = ""
        self._lock = asyncio.Lock()
        self._on_reconnect: ReconnectCallback | None = None
        self._shutting_down = False

        self._client.on_disconnect(self._handle_drop)

    # ------------------------------------------------------------------
    # State
    # ------------------------------------------------------------------

    @property
    def state(self) -> ConnectionState:
        return self._state

    @property
    def is_connected(self) -> bool:
        return self._client.is_connected

    @property
    def enabled(self) -> bool:
        return self._settings.enabled

    def info(self) -> ConnectionInfo:
        return ConnectionInfo(
            state=self._state,
            url=self._settings.url,
            session_id=self._client.session_id,
            connected_at=self._connected_at,
            last_error=self._last_error,
            reconnect_attempts=self._policy.attempts,
        )

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def on(self, event: str, handler: EventHandler) -> None:
        """Register an inbound event handler. Survives reconnects."""
        self._client.on(event, handler)

    def set_on_reconnect(self, callback: ReconnectCallback | None) -> None:
        """Register work to run after the link is re-established.

        Used to drain buffered audio chunks.
        """
        self._on_reconnect = callback

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def connect(self, *, max_attempts: int | None = None) -> bool:
        """Establish the initial connection, retrying under the policy.

        Returns:
            True if connected. False means the bot should continue without
            streaming — a meeting still records locally-buffered audio and can
            drain it later, so this is not fatal.
        """
        if not self.enabled:
            logger.info("Audio service streaming disabled: no WEBSOCKET_URL configured")
            return False

        async with self._lock:
            if self._client.is_connected:
                return True

            self._shutting_down = False
            attempts = max(1, max_attempts or self._settings.max_reconnect_attempts)
            self._policy.reset()

            for attempt in range(1, attempts + 1):
                self._state = ConnectionState.CONNECTING
                try:
                    await self._client.connect()
                except WebSocketError as error:
                    self._last_error = str(error)
                    kind = classify_error(error)
                    logger.warning(
                        "Audio service connection attempt failed",
                        extra={
                            "attempt": attempt,
                            "max_attempts": attempts,
                            "error_kind": kind.value,
                            "reason": str(error),
                        },
                    )

                    if kind is ErrorKind.PERMANENT or attempt >= attempts:
                        break

                    self._policy.record_attempt()
                    await asyncio.sleep(self._policy.next_delay_seconds())
                    continue

                self._mark_connected()
                return True

            self._state = ConnectionState.FAILED
            logger.error(
                "Could not reach the audio service; audio will be buffered locally",
                extra={"url": self._settings.url, "attempts": attempts},
            )
            return False

    async def disconnect(self) -> None:
        """Shut down deliberately. Stops supervision so nothing reconnects behind us."""
        self._shutting_down = True
        await self._tasks.cancel_all()
        await self._client.disconnect()
        self._state = ConnectionState.CLOSED
        self._connected_at = None
        logger.info("Audio service connection closed")

    # ------------------------------------------------------------------
    # Messaging
    # ------------------------------------------------------------------

    async def emit(self, event: str, payload: Any) -> None:
        """Send an event.

        Raises:
            WebSocketNotConnectedError: If the link is down. Callers buffer.
        """
        await self._client.emit(event, payload)

    async def call(self, event: str, payload: Any, *, timeout_seconds: float | None = None) -> Any:
        """Send an event and await its acknowledgement."""
        return await self._client.call(event, payload, timeout_seconds=timeout_seconds)

    # ------------------------------------------------------------------
    # Supervision
    # ------------------------------------------------------------------

    def _mark_connected(self) -> None:
        self._state = ConnectionState.CONNECTED
        self._connected_at = datetime.now(timezone.utc)
        self._last_error = ""
        self._policy.reset()

    async def _handle_drop(self) -> None:
        """React to a connection the server or network closed.

        Called by: the Socket.IO client, via the ``on_disconnect`` hook registered
        in ``__init__`` — see docs/ENTRY_POINTS.md, internal callbacks.
        """
        if self._shutting_down:
            return

        self._connected_at = None
        self._state = ConnectionState.DISCONNECTED

        if not self._settings.auto_reconnect:
            logger.warning("Connection dropped and auto-reconnect is disabled")
            return

        if self._tasks.is_running(_SUPERVISOR_TASK):
            return

        logger.info("Connection dropped; scheduling reconnect")
        self._tasks.spawn(_SUPERVISOR_TASK, self._reconnect_loop())

    async def _reconnect_loop(self) -> None:
        """Retry until connected, the policy gives up, or shutdown begins."""
        self._state = ConnectionState.RECONNECTING
        self._policy.reset()

        while not self._shutting_down and self._policy.should_retry():
            delay = self._policy.next_delay_seconds()
            self._policy.record_attempt()

            logger.info(
                "Reconnecting to audio service",
                extra={
                    "attempt": self._policy.attempts,
                    "max_attempts": self._policy.max_attempts,
                    "delay_seconds": round(delay, 2),
                },
            )
            await asyncio.sleep(delay)

            if self._shutting_down:
                break

            try:
                await self._client.connect()
            except WebSocketError as error:
                self._last_error = str(error)
                if classify_error(error) is ErrorKind.PERMANENT:
                    logger.error("Giving up: permanent connection error", extra={"reason": str(error)})
                    break
                continue

            self._mark_connected()
            logger.info("Reconnected to audio service", extra={"attempts": self._policy.attempts})
            await self._run_reconnect_callback()
            return

        if not self._shutting_down:
            self._state = ConnectionState.FAILED
            logger.error("Reconnection abandoned; buffered audio will be flushed at end of recording")

    async def _run_reconnect_callback(self) -> None:
        """Run the post-reconnect hook, typically a buffer drain."""
        if self._on_reconnect is None:
            return
        try:
            await self._on_reconnect()
        except Exception as error:
            logger.error("Post-reconnect callback failed", exc_info=error)


__all__ = ["ConnectionManager", "WebSocketNotConnectedError"]
