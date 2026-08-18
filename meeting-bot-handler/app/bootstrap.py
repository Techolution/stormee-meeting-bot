"""
Application dependency wiring.

This is where concrete implementations will be constructed and injected.
"""

from app.application.bot_client import BotClient
from app.application.bot_handler import BotHandler
from app.application.session_service import SessionService
from app.application.bot_service_resolver import BotServiceResolver
from app.repositories.in_memory_session_repository import InMemorySessionRepository


def create_bot_client(service_url: str | None = None) -> BotClient:
    """Create and configure a BotClient instance.

    The `service_url` is optional and only used for a default client. In
    production the per-session client will be created by the handler using a
    resolved URL.
    """
    return BotClient(service_url=service_url)


def create_bot_handler(
    bot_client: BotClient | None = None,
) -> BotHandler:
    """Create and configure a BotHandler instance.
    
    Args:
        bot_client: Optional BotClient to use. If not provided, creates a new one.
        
    Returns:
        Configured BotHandler instance.
    """
    # Wire simple in-memory session persistence for local/testing runs.
    repo = InMemorySessionRepository()
    session_service = SessionService(repo)
    resolver = BotServiceResolver()

    if bot_client is None:
        bot_client = create_bot_client()

    return BotHandler(bot_client=bot_client, session_service=session_service, resolver=resolver)
