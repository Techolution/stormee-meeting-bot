"""WebSocket transport — client side only.

This bot is a *client* of the audio service, never a server. The Socket.IO
server that ingests audio is a separately deployed process and is intentionally
not part of this codebase.

Three layers, each with one reason to change:

  ``client.py``              One connection: connect, emit, call, disconnect.
  ``connection_manager.py``  Keeping a connection available: retries, drops,
                             reconnects, post-reconnect hooks.
  ``event_handler.py``       What inbound events mean.

Protocol semantics — which events exist and what their payloads contain — live
in :mod:`app.schemas.websocket` and :mod:`app.clients.audio_service`.
"""

from app.websocket.client import WebSocketClient
from app.websocket.connection_manager import ConnectionManager
from app.websocket.event_handler import AudioServiceEventHandler
from app.websocket.models import ConnectionInfo, ConnectionState
from app.websocket.reconnection import ErrorKind, ReconnectionPolicy

__all__ = [
    "AudioServiceEventHandler",
    "ConnectionInfo",
    "ConnectionManager",
    "ConnectionState",
    "ErrorKind",
    "ReconnectionPolicy",
    "WebSocketClient",
]
