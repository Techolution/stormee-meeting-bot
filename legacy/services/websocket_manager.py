"""WebSocket connection manager for Socket.IO lifecycle management."""

import asyncio
import logging
from typing import Optional, Callable

import socketio

from services.reconnection_strategy import (
    ReconnectionStrategy,
    ErrorType,
)
from utilities.env_config import config


logger = logging.getLogger(__name__)


class WebSocketManager:
    """
    Manages the Socket.IO AsyncClient lifecycle.

    Important:
    - Initial connection is retried explicitly.
    - A fresh AsyncClient is created after a failed/closed connection.
    - Event handlers are registered exactly once per client.
    - Explicit disconnect does not leave a stale client around.
    """

    _instance: Optional["WebSocketManager"] = None

    def __init__(self):
        self.sio: Optional[socketio.AsyncClient] = None

        self._connecting = False
        self._connect_lock = asyncio.Lock()

        self._ws_url: Optional[str] = None

        self._on_reconnect_success: Optional[Callable] = None

        self._reconnection_strategy = ReconnectionStrategy(
            initial_delay_ms=config.get("WEBSOCKET_RECONNECT_DELAY"),
            backoff_factor=config.get("WEBSOCKET_BACKOFF_FACTOR"),
            max_delay_ms=config.get("WEBSOCKET_MAX_RECONNECT_DELAY"),
            max_attempts=config.get("WEBSOCKET_MAX_RECONNECT_ATTEMPTS"),
        )

    # ------------------------------------------------------------------
    # CLIENT CREATION
    # ------------------------------------------------------------------

    def _create_client(self) -> socketio.AsyncClient:
        """
        Create a completely fresh Socket.IO client.

        This is important after an explicit disconnect or failed
        namespace handshake.
        """

        sio = socketio.AsyncClient(
            logger=False,
            engineio_logger=False,

            # We manage retries ourselves.
            reconnection=False,

            # Keep connection timeout controlled by connect().
            request_timeout=30,
        )

        self._register_handlers(sio)

        return sio

    def _register_handlers(self, sio: socketio.AsyncClient) -> None:
        """
        Register handlers once for this client instance.
        """

        @sio.event
        async def connect():
            logger.info(
                "WebSocket connected successfully "
                f"(sid={sio.sid})"
            )

        @sio.event
        async def disconnect():
            logger.info(
                f"WebSocket disconnected (sid={sio.sid})"
            )

        @sio.event
        async def connect_error(data):
            logger.error(
                f"WebSocket connection error: {data}"
            )

    def get_instance(self) -> socketio.AsyncClient:
        """
        Return current Socket.IO client.

        Creates a new one if no client exists.
        """

        if self.sio is None:
            self.sio = self._create_client()

        return self.sio

    # ------------------------------------------------------------------
    # CONNECT
    # ------------------------------------------------------------------

    async def connect(
        self,
        ws_url: str,
        max_attempts: Optional[int] = None,
    ) -> bool:
        """
        Connect to Socket.IO with explicit retry handling.

        Returns:
            True if connected successfully.
            False if all attempts failed.
        """

        if not ws_url:
            logger.warning(
                "WebSocket URL is missing or empty; "
                "skipping connection"
            )
            return False

        async with self._connect_lock:

            # Already connected.
            if self.sio is not None and self.sio.connected:
                logger.info(
                    f"WebSocket already connected to {ws_url}"
                )
                return True

            self._ws_url = ws_url

            # Use configured retry count unless explicitly provided.
            if max_attempts is None:
                try:
                    max_attempts = int(
                        config.get("WEBSOCKET_MAX_RECONNECT_ATTEMPTS")
                    )
                except (ValueError, TypeError):
                    max_attempts = 5

            # Always have at least one attempt.
            max_attempts = max(1, max_attempts)

            self._connecting = True

            try:
                for attempt in range(1, max_attempts + 1):

                    # --------------------------------------------------
                    # IMPORTANT:
                    # Create a fresh client for every new attempt.
                    # --------------------------------------------------

                    if self.sio is not None and self.sio.connected:
                        logger.info(
                            "WebSocket became connected while retrying"
                        )
                        return True

                    # If an old client exists but is disconnected,
                    # completely dispose of it.
                    if self.sio is not None:
                        try:
                            if self.sio.connected:
                                await self.sio.disconnect()
                        except Exception:
                            pass

                        self.sio = None

                    self.sio = self._create_client()

                    delay = 0.0

                    if attempt > 1:
                        try:
                            delay = self._reconnection_strategy.get_delay_seconds()
                        except Exception:
                            delay = min(2 ** (attempt - 2), 10)

                        logger.info(
                            f"Waiting {delay:.2f}s before WebSocket "
                            f"connection attempt {attempt}/{max_attempts}"
                        )

                        await asyncio.sleep(delay)

                    logger.info(
                        f"Connecting to WebSocket "
                        f"(attempt {attempt}/{max_attempts}): {ws_url}"
                    )

                    try:
                        # --------------------------------------------------
                        # Explicit websocket transport.
                        #
                        # Your logs show the server accepts websocket
                        # connections, so avoid getting stuck between
                        # polling -> websocket upgrades.
                        # --------------------------------------------------

                        await self.sio.connect(
                            ws_url,
                            transports=["websocket"],
                            wait_timeout=15,
                            socketio_path="api/meet/socket.io"
                        )

                        # Socket.IO connect() should only return once the
                        # namespace handshake succeeds, but verify anyway.
                        await asyncio.sleep(0.2)

                        if self.sio.connected:
                            logger.info(
                                f"WebSocket connection established "
                                f"successfully on attempt {attempt}"
                            )

                            self._reconnection_strategy.reset()

                            return True

                        logger.warning(
                            f"WebSocket connect returned but client "
                            f"is not connected "
                            f"(attempt {attempt}/{max_attempts})"
                        )

                    except Exception as e:
                        logger.warning(
                            f"WebSocket connection attempt "
                            f"{attempt}/{max_attempts} failed: {e}"
                        )

                        # Dispose failed client.
                        try:
                            if self.sio is not None:
                                await self.sio.disconnect()
                        except Exception:
                            pass

                        self.sio = None

                        if attempt < max_attempts:
                            try:
                                self._reconnection_strategy.record_attempt()
                            except Exception:
                                pass

                logger.error(
                    f"WebSocket connection failed after "
                    f"{max_attempts} attempts"
                )

                return False

            finally:
                self._connecting = False

    # ------------------------------------------------------------------
    # DISCONNECT
    # ------------------------------------------------------------------

    async def disconnect(self) -> None:
        """
        Completely disconnect and dispose of the current client.

        The next connect() will create a fresh AsyncClient.
        """

        async with self._connect_lock:

            self._connecting = False

            if self.sio is None:
                logger.debug(
                    "WebSocket disconnect requested but no client exists"
                )
                return

            old_sio = self.sio

            try:
                if old_sio.connected:
                    logger.info(
                        f"Disconnecting WebSocket (sid={old_sio.sid})"
                    )

                    await old_sio.disconnect()

                    # Give Engine.IO a moment to finish cleanup.
                    await asyncio.sleep(0.1)

            except Exception as e:
                logger.warning(
                    f"Error while disconnecting WebSocket: {e}"
                )

            finally:
                # VERY IMPORTANT:
                # Don't reuse this AsyncClient on the next recording.
                self.sio = None

                logger.info(
                    "WebSocket client disposed"
                )

    # ------------------------------------------------------------------
    # STATE
    # ------------------------------------------------------------------

    def get_connection_state(self) -> str:
        """
        Return current connection state.
        """

        if self._connecting:
            return "connecting"

        if self.sio is not None and self.sio.connected:
            return "active"

        return "disconnected"

    def is_connected(self) -> bool:
        """
        Return True only when Socket.IO is actually connected.
        """

        return (
            self.sio is not None
            and self.sio.connected
        )

    # ------------------------------------------------------------------
    # CALLBACK
    # ------------------------------------------------------------------

    def set_on_reconnect_success(
        self,
        callback: Optional[Callable],
    ) -> None:
        self._on_reconnect_success = callback