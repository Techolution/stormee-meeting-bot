"""In-process runtime state.

This is what the bot is doing *right now*: is the browser up, is the recorder
running, is the socket connected. It lives in memory, it dies with the pod, and
that is correct — it describes a process, not a meeting.

Durable meeting state is a different thing entirely and lives elsewhere (see
:mod:`app.repositories`). Conflating the two is a mistake with consequences: a
pod restart loses runtime state, and any decision that treated it as the source
of truth silently changes its answer.

Runtime state answers "should this pod be restarted?".
Durable state answers "did this meeting get recorded?".
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class ComponentState(str, Enum):
    """Uniform lifecycle vocabulary shared by every subsystem."""

    IDLE = "idle"
    STARTING = "starting"
    ACTIVE = "active"
    DEGRADED = "degraded"
    STOPPING = "stopping"
    STOPPED = "stopped"
    FAILED = "failed"


class SessionState(str, Enum):
    """Lifecycle of one meeting session inside this process."""

    CREATED = "created"
    JOINING = "joining"
    IN_MEETING = "in_meeting"
    LEAVING = "leaving"
    ENDED = "ended"
    FAILED = "failed"

    @property
    def is_terminal(self) -> bool:
        return self in (SessionState.ENDED, SessionState.FAILED)

    @property
    def is_live(self) -> bool:
        return self in (SessionState.JOINING, SessionState.IN_MEETING)


@dataclass(slots=True)
class ComponentStatus:
    """One subsystem's current state."""

    name: str
    state: ComponentState = ComponentState.IDLE
    detail: dict[str, Any] = field(default_factory=dict)
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def set(self, state: ComponentState, **detail: Any) -> None:
        self.state = state
        self.updated_at = datetime.now(timezone.utc)
        if detail:
            self.detail.update(detail)

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "state": self.state.value,
            "detail": self.detail,
            "updated_at": self.updated_at.isoformat(),
        }


@dataclass(slots=True)
class RuntimeState:
    """Live status of one meeting session.

    Cheap to read and safe to poll: a status endpoint hitting this must never
    touch the browser or the network.
    """

    meeting_id: str
    session_id: str
    session_state: SessionState = SessionState.CREATED
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    ended_at: datetime | None = None
    participant_count: int = 0
    last_heartbeat: datetime | None = None
    last_error: str = ""

    browser: ComponentStatus = field(default_factory=lambda: ComponentStatus("browser"))
    platform: ComponentStatus = field(default_factory=lambda: ComponentStatus("platform"))
    recording: ComponentStatus = field(default_factory=lambda: ComponentStatus("recording"))
    transcription: ComponentStatus = field(default_factory=lambda: ComponentStatus("transcription"))
    websocket: ComponentStatus = field(default_factory=lambda: ComponentStatus("websocket"))

    # ------------------------------------------------------------------
    # Transitions
    # ------------------------------------------------------------------

    def transition(self, state: SessionState, *, error: str = "") -> None:
        """Move the session to a new state, logging the change."""
        if state is self.session_state:
            return

        previous = self.session_state
        self.session_state = state
        if error:
            self.last_error = error
        if state.is_terminal:
            self.ended_at = datetime.now(timezone.utc)

        logger.info(
            "Session state changed",
            extra={
                "meeting_id": self.meeting_id,
                "session_id": self.session_id,
                "from_state": previous.value,
                "to_state": state.value,
                **({"error": error} if error else {}),
            },
        )

    def beat(self) -> None:
        """Record a heartbeat. See :mod:`app.runtime.heartbeat`."""
        self.last_heartbeat = datetime.now(timezone.utc)

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    @property
    def uptime_seconds(self) -> float:
        end = self.ended_at or datetime.now(timezone.utc)
        return (end - self.started_at).total_seconds()

    @property
    def components(self) -> list[ComponentStatus]:
        return [self.browser, self.platform, self.recording, self.transcription, self.websocket]

    @property
    def is_healthy(self) -> bool:
        """True when the session is live and nothing essential has failed.

        The websocket is excluded deliberately: audio buffers locally while it
        is down, so a dropped connection degrades the session rather than
        breaking it.
        """
        if self.session_state.is_terminal:
            return False
        essential = (self.browser, self.platform, self.recording, self.transcription)
        return not any(component.state is ComponentState.FAILED for component in essential)

    def as_dict(self) -> dict[str, Any]:
        return {
            "meeting_id": self.meeting_id,
            "session_id": self.session_id,
            "session_state": self.session_state.value,
            "started_at": self.started_at.isoformat(),
            "ended_at": self.ended_at.isoformat() if self.ended_at else None,
            "uptime_seconds": round(self.uptime_seconds, 1),
            "participant_count": self.participant_count,
            "last_heartbeat": self.last_heartbeat.isoformat() if self.last_heartbeat else None,
            "last_error": self.last_error,
            "healthy": self.is_healthy,
            "components": [component.as_dict() for component in self.components],
        }
