"""Platform selection.

The meeting URL decides which implementation drives the browser. Keeping that
decision here means :class:`~app.meeting.meeting_manager.MeetingManager` never
names a concrete platform, and adding one is a registration rather than an edit
to meeting logic.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from urllib.parse import urlparse

from app.browser.browser import Browser
from app.core.config import MeetingSettings
from app.core.exceptions import UnsupportedPlatformError
from app.meeting_platform.base import MeetingPlatform
from app.meeting_platform.google_meet.platform import GoogleMeetPlatform
from app.meeting_platform.models import PlatformName

logger = logging.getLogger(__name__)

PlatformFactory = Callable[[Browser, MeetingSettings], MeetingPlatform]


def _build_google_meet(browser: Browser, settings: MeetingSettings) -> MeetingPlatform:
    return GoogleMeetPlatform(
        browser,
        admission_timeout_seconds=settings.admission_timeout_seconds,
        admission_poll_interval_seconds=settings.admission_poll_interval_seconds,
    )


#: Hostname suffix -> platform. Checked as a suffix so regional and short-link
#: hosts resolve to the same implementation.
_HOST_REGISTRY: dict[str, tuple[PlatformName, PlatformFactory]] = {
    "meet.google.com": (PlatformName.GOOGLE_MEET, _build_google_meet),
}


def register_platform(host_suffix: str, name: PlatformName, factory: PlatformFactory) -> None:
    """Register an implementation for a host.

    Exposed so a deployment or a test can add a platform without editing this
    module.
    """
    _HOST_REGISTRY[host_suffix.lower()] = (name, factory)
    logger.debug("Registered meeting platform", extra={"host": host_suffix, "platform": name.value})


def detect_platform(meeting_url: str) -> PlatformName | None:
    """Identify the platform for a URL, or ``None`` if none matches."""
    host = (urlparse(meeting_url).hostname or "").lower()
    if not host:
        return None
    for suffix, (name, _factory) in _HOST_REGISTRY.items():
        if host == suffix or host.endswith(f".{suffix}"):
            return name
    return None


def create_platform(
    meeting_url: str,
    browser: Browser,
    settings: MeetingSettings,
) -> MeetingPlatform:
    """Build the platform implementation for a meeting URL.

    Raises:
        UnsupportedPlatformError: If the URL matches no registered platform.
    """
    host = (urlparse(meeting_url).hostname or "").lower()
    for suffix, (name, factory) in _HOST_REGISTRY.items():
        if host == suffix or host.endswith(f".{suffix}"):
            logger.info("Selected meeting platform", extra={"platform": name.value, "host": host})
            return factory(browser, settings)

    raise UnsupportedPlatformError(meeting_url)


def supported_platforms() -> list[str]:
    """Platform identifiers this build can drive."""
    return sorted({name.value for name, _ in _HOST_REGISTRY.values()})
