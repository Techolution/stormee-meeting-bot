"""
In-memory SessionRepository implementation for development and tests.

Stores `BotSession` objects by `session_id` in a dict. Not durable.
"""
from __future__ import annotations

from typing import Dict
from datetime import datetime

from app.repositories.session_repository import SessionRepository
from app.domain.models import BotSession


class InMemorySessionRepository(SessionRepository):
    def __init__(self) -> None:
        self._store: Dict[str, BotSession] = {}

    async def create(self, session: BotSession) -> BotSession:
        now = datetime.utcnow()
        if session.created_at is None:
            session.created_at = now
        self._store[session.session_id] = session
        return session

    async def get_by_session_id(self, session_id: str) -> BotSession | None:
        return self._store.get(session_id)

    async def update(self, session: BotSession) -> BotSession:
        session.updated_at = datetime.utcnow()
        self._store[session.session_id] = session
        return session
