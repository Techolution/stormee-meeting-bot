"""Application dependency wiring.

This is where concrete implementations are constructed and injected.
"""

from __future__ import annotations

import httpx
from app.application.bot_client import BotClient
from app.application.bot_handler import BotHandler
from app.application.bot_service_resolver import BotServiceResolver
from app.application.session_service import SessionService
from app.repositories.in_memory_session_repository import InMemorySessionRepository

# Singleton in-memory repository to preserve session state across requests during runtime
_IN_MEMORY_REPO = InMemorySessionRepository()


def create_bot_client(service_url: str | None = None, http_client: httpx.AsyncClient | None = None) -> BotClient:
    """Create and configure a BotClient instance."""
    return BotClient(service_url=service_url, http_client=http_client)


def create_bot_handler(
    http_client: httpx.AsyncClient | None = None,
) -> BotHandler:
    """Create and configure a BotHandler instance.

    Args:
        http_client: Optional httpx.AsyncClient to use for downstream requests.

    Returns:
        Configured BotHandler instance.
    """
    session_service = SessionService(_IN_MEMORY_REPO)
    bot_resolver = BotServiceResolver()

    return BotHandler(
        session_service=session_service,
        bot_resolver=bot_resolver,
        http_client=http_client,
    )