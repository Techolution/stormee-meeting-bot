"""
Application dependency wiring.

This is where concrete implementations will be constructed and injected.
"""

from app.application.bot_client import BotClient
from app.application.bot_handler import BotHandler


def create_bot_client() -> BotClient:
    """Create and configure a BotClient instance.
    
    Reads BOT_SERVICE_URL from environment.
    Future: May add caching, pooling, or other configuration.
    """
    return BotClient()


def create_bot_handler(bot_client: BotClient | None = None) -> BotHandler:
    """Create and configure a BotHandler instance.
    
    Args:
        bot_client: Optional BotClient to use. If not provided, creates a new one.
        
    Returns:
        Configured BotHandler instance.
    """
    if bot_client is None:
        bot_client = create_bot_client()
    return BotHandler(bot_client=bot_client)
