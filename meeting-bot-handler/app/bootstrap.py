"""
Application dependency wiring.

This is where concrete implementations will be constructed and injected.
"""

from app.application.bot_handler import BotHandler


def create_bot_handler() -> BotHandler:
    # Dependency wiring will be implemented in later phases.
    return BotHandler()
