"""Runtime state — what this process is doing right now.

Strictly separate from durable meeting state, which lives in
:mod:`app.repositories`. Runtime state is in-memory and dies with the pod;
treating it as a source of truth about a meeting is a bug waiting for a restart.
"""

from app.runtime.heartbeat import Heartbeat
from app.runtime.session import SessionRegistry
from app.runtime.state import ComponentState, ComponentStatus, RuntimeState, SessionState

__all__ = [
    "ComponentState",
    "ComponentStatus",
    "Heartbeat",
    "RuntimeState",
    "SessionRegistry",
    "SessionState",
]
