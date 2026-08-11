"""WebSocket connection manager for persistent AsyncClient lifecycle management."""

import logging
import asyncio
from typing import Optional, Callable
import socketio
from services.reconnection_strategy import ReconnectionStrategy, ErrorType
from utilities.env_config import config

logger = logging.getLogger(__name__)


class WebSocketManager:
    """Manages a single persistent AsyncClient instance for WebSocket connections.
    
    Provides:
    - Singleton AsyncClient instance scoped to application lifecycle
    - Connection state tracking and retrieval
    - Idempotent connect operation with event handler registration
    - Connection state queries (active/disconnected/connecting)
    """
    
    _instance: Optional['WebSocketManager'] = None
    
    def __init__(self):
        """Initialize WebSocketManager with a new AsyncClient instance."""
        self.sio: Optional[socketio.AsyncClient] = None
        self._connecting = False
        self._reconnection_strategy = ReconnectionStrategy(
            initial_delay_ms=config.get('WEBSOCKET_RECONNECT_DELAY'),
            backoff_factor=config.get('WEBSOCKET_BACKOFF_FACTOR'),
            max_delay_ms=config.get('WEBSOCKET_MAX_RECONNECT_DELAY'),
            max_attempts=config.get('WEBSOCKET_MAX_RECONNECT_ATTEMPTS')
        )
        self._on_reconnect_success: Optional[Callable] = None
    
    def get_instance(self) -> socketio.AsyncClient:
        """Return the singleton AsyncClient instance, creating it if needed.
        
        Returns:
            socketio.AsyncClient: The managed socket.io client instance.
        """
        if self.sio is None:
            self.sio = socketio.AsyncClient(
                logger=False,
                engineio_logger=False,
                reconnection=True,
                reconnection_attempts=5,
                reconnection_delay=1
            )
        return self.sio
    
    async def connect(self, ws_url: str) -> None:
        """Idempotent connection method that establishes and registers event handlers.
        
        Registers event handlers for 'connect', 'disconnect', and 'connect_error' events.
        Logs all state transitions at INFO level.
        
        Args:
            ws_url: WebSocket URL to connect to (e.g., 'http://localhost:5000')
            
        Returns:
            None. Logs warning and returns if URL is missing/invalid; does not retry.
        """
        if not ws_url:
            logger.warning("WebSocket URL is missing or empty; skipping connection")
            return
        
        sio = self.get_instance()
        
        # Skip if already connected or connecting
        if sio.connected:
            logger.debug(f"WebSocket already connected to {ws_url}")
            return
        
        if self._connecting:
            logger.debug("WebSocket connection attempt already in progress")
            return
        
        # Register event handlers
        @sio.event
        async def connect():
            logger.info("WebSocket connected successfully")
        
        @sio.event
        async def disconnect():
            logger.info("WebSocket disconnected")
        
        @sio.event
        async def connect_error(data):
            logger.error(f"WebSocket connection error: {data}")
        
        # Attempt connection
        self._connecting = True
        try:
            logger.debug(f"Connecting to WebSocket at {ws_url}")
            await sio.connect(ws_url)
            await asyncio.sleep(0.5)  # Brief delay to ensure handlers are set up
            logger.info("WebSocket connection established")
        except Exception as e:
            logger.warning(f"WebSocket connection failed: {e}")
            logger.warning("Audio will be saved locally, no real-time streaming")
        finally:
            self._connecting = False
    
    def set_on_reconnect_success(self, callback: Optional[Callable]) -> None:
        """Set callback to be invoked on successful reconnection after failure.
        
        Args:
            callback: Optional async callable to invoke on successful reconnection.
        """
        self._on_reconnect_success = callback
    
    async def _handle_reconnection(self, ws_url: str) -> None:
        """Handle reconnection with exponential backoff triggered by connect_error.
        
        Implements exponential backoff retry logic for transient errors,
        with configurable max attempts and delay.
        
        Args:
            ws_url: WebSocket URL to reconnect to.
        """
        logger.info("Starting exponential backoff reconnection")
        
        while self._reconnection_strategy.should_retry(ErrorType.TRANSIENT):
            self._reconnection_strategy.record_attempt()
            delay_sec = self._reconnection_strategy.get_delay_seconds()
            
            logger.info(
                f"Reconnection attempt {self._reconnection_strategy.get_attempt_count()}: "
                f"waiting {delay_sec:.1f}s before retry"
            )
            await asyncio.sleep(delay_sec)
            
            try:
                sio = self.get_instance()
                logger.debug(f"Attempting reconnect to {ws_url}")
                await sio.connect(ws_url)
                logger.info("Reconnection successful")
                
                # Invoke success callback if set
                if self._on_reconnect_success:
                    try:
                        if asyncio.iscoroutinefunction(self._on_reconnect_success):
                            await self._on_reconnect_success()
                        else:
                            self._on_reconnect_success()
                    except Exception as cb_err:
                        logger.error(f"Reconnection success callback failed: {cb_err}")
                
                self._reconnection_strategy.reset()
                return
            except Exception as e:
                logger.warning(
                    f"Reconnection attempt {self._reconnection_strategy.get_attempt_count()} failed: {e}"
                )
        
        logger.error(
            f"Reconnection exhausted after {self._reconnection_strategy.get_attempt_count()} attempts; "
            f"audio will be saved locally only"
        )
    
    def get_connection_state(self) -> str:
        """Return the current connection state as a string.
        
        Returns:
            str: One of "active", "disconnected", or "connecting".
                 - "active": socket is currently connected
                 - "disconnected": socket is not connected and never connected
                 - "connecting": connection attempt is in progress
        """
        if self._connecting:
            return "connecting"
        
        sio = self.get_instance()
        if sio.connected:
            return "active"
        
        return "disconnected"
    
    def is_connected(self) -> bool:
        """Check if the socket is currently connected.
        
        Returns:
            bool: True if socket is connected, False otherwise.
        """
        if self.sio is None:
            return False
        return self.sio.connected

