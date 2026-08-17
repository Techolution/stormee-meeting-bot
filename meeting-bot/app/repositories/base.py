"""Durable meeting state.

Records the meaningful transitions of a meeting — joined, recording started,
left — so that a question like "did this meeting record?" can be answered after
the pod is gone.

The interface is defined before any storage choice so that persistence stays
optional. A deployment without Redis gets the in-memory implementation and
loses history on restart; nothing else in the application changes, and no code
path is conditional on whether persistence exists.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class MeetingLifecycleEvent(str, Enum):
    """The durable events worth recording.

    Deliberately coarse. These describe what happened to a *meeting*, not what
    a component is doing — that is runtime state and belongs in
    :mod:`app.runtime.state`.
    """

    INITIALIZED = "initialized"
    JOINING = "joining"
    IN_MEETING = "in_meeting"
    RECORDING_STARTED = "recording_started"
    RECORDING_STOPPED = "recording_stopped"
    TRANSCRIPTION_STARTED = "transcription_started"
    TRANSCRIPTION_STOPPED = "transcription_stopped"
    PARTICIPANTS_CHANGED = "participants_changed"
    LEFT = "left"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class MeetingStateRecord:
    """One recorded transition."""

    event: MeetingLifecycleEvent
    recorded_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "state": self.event.value,
            "timestamp": self.recorded_at.isoformat(),
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> MeetingStateRecord:
        """Rebuild a record from storage.

        Unknown or malformed values become ``FAILED`` rather than raising: a
        history read must not blow up because an older process wrote an event
        this build does not know about.
        """
        try:
            event = MeetingLifecycleEvent(payload.get("state", ""))
        except ValueError:
            event = MeetingLifecycleEvent.FAILED

        raw_time = payload.get("timestamp")
        try:
            recorded_at = datetime.fromisoformat(raw_time) if raw_time else datetime.now(timezone.utc)
        except (TypeError, ValueError):
            recorded_at = datetime.now(timezone.utc)

        metadata = payload.get("metadata")
        return cls(
            event=event,
            recorded_at=recorded_at,
            metadata=metadata if isinstance(metadata, dict) else {},
        )


class MeetingStateRepository(ABC):
    """Stores meeting lifecycle transitions.

    Implementations must degrade rather than raise. Losing a state write is
    unfortunate; failing a meeting because a state store is unreachable is
    worse. Methods therefore report success as a boolean and log the reason.
    """

    @property
    @abstractmethod
    def is_available(self) -> bool:
        """Whether the backing store is usable right now."""

    @abstractmethod
    async def record(
        self,
        meeting_id: str,
        event: MeetingLifecycleEvent,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        """Append a transition and make it the current state."""

    @abstractmethod
    async def current(self, meeting_id: str) -> MeetingStateRecord | None:
        """The most recent transition, or ``None``."""

    @abstractmethod
    async def history(self, meeting_id: str, *, limit: int = 100) -> list[MeetingStateRecord]:
        """Transitions for a meeting, newest first."""

    @abstractmethod
    async def delete(self, meeting_id: str) -> bool:
        """Remove everything stored for a meeting."""

    async def close(self) -> None:
        """Release any resources. Default is a no-op."""
        return None
