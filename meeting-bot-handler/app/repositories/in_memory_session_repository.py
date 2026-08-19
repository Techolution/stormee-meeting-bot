from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Dict, List, Optional

from app.domain.enums import RecordingStatus
from app.domain.models import BotSession, MeetingRecording, MeetingEvent
from app.repositories.session_repository import SessionRepository


class InMemorySessionRepository(SessionRepository):
    """In-memory thread-safe implementation of SessionRepository for development and testing."""

    def __init__(self) -> None:
        self._sessions: Dict[str, BotSession] = {}
        self._recordings: Dict[str, MeetingRecording] = {}
        self._events: Dict[str, List[MeetingEvent]] = {}
        self._lock = asyncio.Lock()

    async def create(self, session: BotSession) -> BotSession:
        async with self._lock:
            self._sessions[session.session_id] = session
            if session.session_id not in self._events:
                self._events[session.session_id] = []
            return session

    async def get_by_session_id(self, session_id: str) -> Optional[BotSession]:
        async with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                return None
            
            # Attach related entities
            session.recordings = [
                r for r in self._recordings.values() if r.session_id == session_id
            ]
            session.events = self._events.get(session_id, [])
            return session

    async def get_by_meeting_id(self, meeting_id: str) -> Optional[BotSession]:
        async with self._lock:
            matches = [s for s in self._sessions.values() if s.meeting_id == meeting_id]
            if not matches:
                return None
            return max(matches, key=lambda s: s.created_at or datetime.min.replace(tzinfo=timezone.utc))

    async def list_sessions(self, active_only: bool = False) -> List[BotSession]:
        async with self._lock:
            sessions = list(self._sessions.values())
            if active_only:
                sessions = [s for s in sessions if not s.is_terminal]
            return sorted(
                sessions,
                key=lambda s: s.created_at or datetime.min.replace(tzinfo=timezone.utc),
                reverse=True,
            )

    async def update(self, session: BotSession) -> BotSession:
        async with self._lock:
            self._sessions[session.session_id] = session
            return session

    async def add_recording(self, recording: MeetingRecording) -> MeetingRecording:
        async with self._lock:
            self._recordings[recording.recording_id] = recording
            return recording

    async def update_recording(self, recording: MeetingRecording) -> MeetingRecording:
        async with self._lock:
            self._recordings[recording.recording_id] = recording
            return recording

    async def get_active_recording(self, session_id: str) -> Optional[MeetingRecording]:
        async with self._lock:
            recs = [
                r for r in self._recordings.values()
                if r.session_id == session_id and r.status in (RecordingStatus.STARTING, RecordingStatus.RECORDING)
            ]
            return recs[-1] if recs else None

    async def add_event(self, event: MeetingEvent) -> MeetingEvent:
        async with self._lock:
            if event.session_id not in self._events:
                self._events[event.session_id] = []
            self._events[event.session_id].append(event)
            return event