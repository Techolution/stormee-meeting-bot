"""Unit tests for session creation and start flow.

These tests exercise SessionService and BotHandler interaction for
resolving service URL and making BotClient calls. BotClient and resolver
are mocked so tests do not perform HTTP or Kubernetes operations.
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock
from datetime import datetime

from app.application.bot_handler import BotHandler
from app.application.session_service import SessionService
from app.repositories.in_memory_session_repository import InMemorySessionRepository
from app.application.bot_service_resolver import BotServiceResolver, BotTarget
from app.domain.models import BotSession
from app.domain.enums import BotSessionStatus
from app.application.bot_client import BotClient


@pytest.mark.asyncio
async def test_create_and_start_session_happy_path(monkeypatch):
    repo = InMemorySessionRepository()
    service = SessionService(repo)

    # create a session record
    session = BotSession(session_id="s1", meeting_id="m1", status=BotSessionStatus.PENDING)
    await service.create_session(session)

    # mock resolver to return a service_url
    class FakeResolver(BotServiceResolver):
        async def resolve(self, session_in: BotSession):
            return BotTarget(service_url="http://bot-service.svc", worker_id="w1")

    # mock bot client to assert it's called with meeting_id
    fake_client = MagicMock(spec=BotClient)
    fake_client.join_meeting = AsyncMock(return_value={"ok": True})
    fake_client.close = AsyncMock()

    # monkeypatch BotClient constructor to return our fake_client when given the resolved url
    original_bot_client = BotClient

    def fake_bot_client_ctor(service_url: str | None = None):
        return fake_client

    monkeypatch.setattr("app.application.bot_client.BotClient", fake_bot_client_ctor)

    handler = BotHandler(bot_client=None, session_service=service, resolver=FakeResolver())

    # start the bot for s1
    await handler.start_bot("s1")

    # verify fake client was used
    fake_client.join_meeting.assert_awaited_once_with("m1")

    # verify session marked RUNNING
    updated = await service.get_session("s1")
    assert updated is not None
    assert updated.status == BotSessionStatus.RUNNING
    assert updated.started_at is not None
