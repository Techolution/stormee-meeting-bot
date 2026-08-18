"""
Durable Bot session persistence.

This repository owns DB access for bot_sessions.
"""


class SessionRepository:
    async def create(self, session):
        raise NotImplementedError

    async def get_by_session_id(self, session_id: str):
        raise NotImplementedError

    async def update(self, session):
        raise NotImplementedError
