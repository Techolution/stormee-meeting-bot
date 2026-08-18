"""SessionService: handles session lifecycle persistence and retrieval.

This is a thin layer over a SessionRepository to encapsulate business operations
around sessions.
"""
from __future__ import annotations

from typing import Optional
from datetime import datetime

from app.repositories.session_repository import SessionRepository
from app.domain.models import BotSession
from app.domain.enums import BotSessionStatus


class SessionService:
    def __init__(self, repo: SessionRepository) -> None:
        self._repo = repo

    async def create_session(self, session: BotSession) -> BotSession:
        session.status = BotSessionStatus.PENDING
        session.created_at = session.created_at or datetime.utcnow()
        return await self._repo.create(session)

    async def get_session(self, session_id: str) -> Optional[BotSession]:
        return await self._repo.get_by_session_id(session_id)

    async def update_session(self, session: BotSession) -> BotSession:
        session.updated_at = datetime.utcnow()
        return await self._repo.update(session)
