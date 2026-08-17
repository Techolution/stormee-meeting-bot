"""Low-level Socket.IO client.

Exactly one responsibility: move bytes over one connection. Connect, emit,
request/response, disconnect. It does not decide when to reconnect (that is
:mod:`app.websocket.connection_manager`) and it does not know what any event
means (that is :mod:`app.clients.audio_service`).

A fresh ``AsyncClient`` is created for every connection attempt. Reusing one
after a failed handshake leaves Engine.IO in a state where subsequent connects
silently no-op — a failure mode that previously showed up as a bot that
recorded to nowhere.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from contextlib import suppress
from typing import Any

import socketio

from app.core.exceptions import WebSocketError, WebSocketNotConnectedError

logger = logging.getLogger(__name__)

EventHandler = Callable[[Any], Awaitable[None]]


class WebSocketClient:
    """One Socket.IO connection to the audio service."""

    def __init__(
        self,
        *,
        url: str,
        socketio_path: str = "api/meet/socket.io",
        connect_timeout_seconds: float = 15.0,
        request_timeout_seconds: float = 30.0,
    ) -> None:
        self._url = url
        self._path = socketio_path
        self._connect_timeout = connect_timeout_seconds
        self._request_timeout = request_timeout_seconds

        self._sio: socketio.AsyncClient | None = None
        self._handlers: dict[str, EventHandler] = {}
        self._on_disconnect: Callable[[], Awaitable[None]] | None = None

    # ------------------------------------------------------------------
    # State
    # ------------------------------------------------------------------

    @property
    def url(self) -> str:
        return self._url

    @property
    def is_connected(self) -> bool:
        return self._sio is not None and self._sio.connected

    @property
    def session_id(self) -> str | None:
        return self._sio.sid if self._sio is not None else None

    # ------------------------------------------------------------------
    # Handler registration
    # ------------------------------------------------------------------

    def on(self, event: str, handler: EventHandler) -> None:
        """Register a handler for an inbound event.

        Handlers are stored on the client and re-attached to each new
        underlying connection, so registration survives reconnects.
        """
        self._handlers[event] = handler

    def on_disconnect(self, callback: Callable[[], Awaitable[None]]) -> None:
        """Register a callback invoked when the connection drops.

        This is how the connection manager learns it needs to reconnect.
        """
        self._on_disconnect = callback

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        """Open the connection.

        Raises:
            WebSocketError: If the handshake fails or completes without a
                usable connection.
        """
        if not self._url:
            raise WebSocketError("no audio service URL configured")

        await self._dispose()
        self._sio = self._build_client()

        try:
            await self._sio.connect(
                self._url,
                # Skip the polling-to-websocket upgrade: the audio service
                # accepts websocket directly, and negotiating the upgrade adds
                # latency and an extra way to get stuck.
                transports=["websocket"],
                wait_timeout=self._connect_timeout,
                socketio_path=self._path,
            )
        except Exception as error:
            await self._dispose()
            raise WebSocketError(f"connection to {self._url} failed: {error}") from error

        if not self._sio.connected:
            await self._dispose()
            raise WebSocketError(f"handshake with {self._url} completed but no session was established")

        logger.info("Connected to audio service", extra={"url": self._url, "sid": self._sio.sid})

    async def disconnect(self) -> None:
        """Close the connection and drop the client. Safe to call when already closed."""
        if self._sio is None:
            return
        try:
            if self._sio.connected:
                await self._sio.disconnect()
        except Exception as error:  # noqa: BLE001 - teardown must not raise
            logger.warning("Error during websocket disconnect", extra={"reason": str(error)})
        finally:
            await self._dispose()
            logger.debug("Websocket client disposed")

    # ------------------------------------------------------------------
    # Messaging
    # ------------------------------------------------------------------

    async def emit(self, event: str, payload: Any) -> None:
        """Send an event without waiting for a reply.

        Raises:
            WebSocketNotConnectedError: If the connection is down.
            WebSocketError: If the send itself fails.
        """
        if not self.is_connected:
            raise WebSocketNotConnectedError(f"cannot emit {event!r}: not connected")

        assert self._sio is not None
        try:
            await self._sio.emit(event, payload)
        except Exception as error:
            raise WebSocketError(f"failed to emit {event!r}: {error}") from error

    async def call(self, event: str, payload: Any, *, timeout_seconds: float | None = None) -> Any:
        """Send an event and wait for the server's acknowledgement.

        Raises:
            WebSocketNotConnectedError: If the connection is down.
            WebSocketError: If the call fails or times out.
        """
        if not self.is_connected:
            raise WebSocketNotConnectedError(f"cannot call {event!r}: not connected")

        assert self._sio is not None
        try:
            return await self._sio.call(
                event, payload, timeout=timeout_seconds or self._request_timeout
            )
        except Exception as error:
            raise WebSocketError(f"call to {event!r} failed: {error}") from error

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _build_client(self) -> socketio.AsyncClient:
        """Create a client with our own retry policy rather than Socket.IO's.

        ``reconnection=False`` is deliberate: the library's reconnect loop is
        opaque and cannot coordinate with chunk buffering, so
        :class:`~app.websocket.connection_manager.ConnectionManager` owns it.
        """
        client = socketio.AsyncClient(
            logger=False,
            engineio_logger=False,
            reconnection=False,
            request_timeout=self._request_timeout,
        )
        self._attach_handlers(client)
        return client

    def _attach_handlers(self, client: socketio.AsyncClient) -> None:
        @client.event
        async def connect() -> None:
            logger.debug("Socket.IO session established", extra={"sid": client.sid})

        @client.event
        async def disconnect() -> None:
            logger.info("Socket.IO session ended", extra={"sid": client.sid})
            if self._on_disconnect is not None:
                await self._on_disconnect()

        @client.event
        async def connect_error(data: Any) -> None:
            logger.error("Socket.IO connection error", extra={"detail": str(data)[:300]})

        for event, handler in self._handlers.items():
            client.on(event, self._wrap_handler(event, handler))

    @staticmethod
    def _wrap_handler(event: str, handler: EventHandler) -> EventHandler:
        """Stop a failing handler from tearing down the connection."""

        async def _safe(payload: Any) -> None:
            try:
                await handler(payload)
            except Exception as error:
                logger.error(
                    "Websocket event handler failed",
                    exc_info=error,
                    extra={"event": event},
                )

        return _safe

    async def _dispose(self) -> None:
        """Drop the client and close the HTTP session underneath it.

        Dropping the reference alone leaks: python-socketio keeps an
        ``aiohttp.ClientSession`` on its Engine.IO client, and a *failed*
        connect leaves that session open with nothing to close it. Python then
        reports "Unclosed client session" — one per attempt, so a retry loop
        against an unreachable service leaks steadily for the life of the pod.
        """
        client = self._sio
        self._sio = None
        if client is None:
            return

        session = getattr(getattr(client, "eio", None), "http", None)
        if session is not None and not session.closed:
            with suppress(Exception):
                await session.close()
