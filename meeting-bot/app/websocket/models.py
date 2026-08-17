"""WebSocket transport value objects."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum


class ConnectionState(str, Enum):
    """Where the client stands with the audio service."""

    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"

    #: Retries exhausted or a permanent error. No further attempts will be made
    #: without an explicit reconnect.
    FAILED = "failed"

    #: Deliberately shut down. Distinct from FAILED so supervision does not
    #: fight an intentional disconnect.
    CLOSED = "closed"

    @property
    def is_usable(self) -> bool:
        return self is ConnectionState.CONNECTED


@dataclass(frozen=True, slots=True)
class ConnectionInfo:
    """Snapshot of connection health, for status endpoints and logs."""

    state: ConnectionState
    url: str = ""
    session_id: str | None = None
    connected_at: datetime | None = None
    last_error: str = ""
    reconnect_attempts: int = 0

    @property
    def uptime_seconds(self) -> float:
        if self.connected_at is None:
            return 0.0
        return (datetime.now(timezone.utc) - self.connected_at).total_seconds()

    def as_dict(self) -> dict:
        return {
            "state": self.state.value,
            "url": self.url,
            "session_id": self.session_id,
            "uptime_seconds": round(self.uptime_seconds, 1),
            "reconnect_attempts": self.reconnect_attempts,
            "last_error": self.last_error,
        }
