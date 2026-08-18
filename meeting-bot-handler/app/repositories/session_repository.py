from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional, List

from app.domain.models import BotSession, MeetingRecording, MeetingEvent


class SessionRepository(ABC):
    """Abstract interface for durable bot session and recording storage."""

    @abstractmethod
    async def create(self, session: BotSession) -> BotSession:
        """Persist a new session record."""
        pass

    @abstractmethod
    async def get_by_session_id(self, session_id: str) -> Optional[BotSession]:
        """Fetch a session by session_id."""
        pass

    @abstractmethod
    async def update(self, session: BotSession) -> BotSession:
        """Update an existing session record."""
        pass

    @abstractmethod
    async def add_recording(self, recording: MeetingRecording) -> MeetingRecording:
        """Add a new recording take to a session."""
        pass

    @abstractmethod
    async def update_recording(self, recording: MeetingRecording) -> MeetingRecording:
        """Update an existing recording take."""
        pass

    @abstractmethod
    async def get_active_recording(self, session_id: str) -> Optional[MeetingRecording]:
        """Fetch the currently active/latest recording take for a session."""
        pass

    @abstractmethod
    async def add_event(self, event: MeetingEvent) -> MeetingEvent:
        """Record a session event."""
        pass