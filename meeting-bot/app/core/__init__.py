"""Cross-cutting concerns: configuration, logging, correlation, errors, timing.

Nothing in this package may import from a domain package. The dependency arrow
points inward — domain code depends on ``core``, never the reverse.
"""

from app.core.config import Settings, get_settings
from app.core.exceptions import MeetingBotError
from app.core.logging import configure_logging, get_logger

__all__ = [
    "MeetingBotError",
    "Settings",
    "configure_logging",
    "get_logger",
    "get_settings",
]
