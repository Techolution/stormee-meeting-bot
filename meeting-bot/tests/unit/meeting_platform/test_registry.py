"""Tests for platform selection.

The registry is what allows a second meeting platform to be added without
touching meeting logic, so these tests pin the contract it offers.
"""

from __future__ import annotations

import pytest

from app.core.config import MeetingSettings
from app.core.exceptions import UnsupportedPlatformError
from app.meeting_platform.google_meet.platform import GoogleMeetPlatform
from app.meeting_platform.models import PlatformName
from app.meeting_platform.registry import (
    create_platform,
    detect_platform,
    register_platform,
    supported_platforms,
)


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://meet.google.com/abc-defg-hij", PlatformName.GOOGLE_MEET),
        ("https://MEET.GOOGLE.COM/abc-defg-hij", PlatformName.GOOGLE_MEET),
        ("https://meet.google.com/abc?authuser=1", PlatformName.GOOGLE_MEET),
        ("https://zoom.us/j/12345", None),
        ("https://teams.microsoft.com/l/meetup-join/x", None),
        ("not-a-url", None),
        ("", None),
    ],
)
def test_platform_detection(url: str, expected: PlatformName | None) -> None:
    assert detect_platform(url) is expected


def test_a_lookalike_host_is_not_matched() -> None:
    """Suffix matching must not accept an attacker-controlled lookalike domain."""
    assert detect_platform("https://meet.google.com.evil.test/abc") is None


def test_google_meet_url_produces_the_google_meet_driver() -> None:
    platform = create_platform(
        "https://meet.google.com/abc-defg-hij",
        _StubBrowser(),  # type: ignore[arg-type]
        MeetingSettings(),
    )

    assert isinstance(platform, GoogleMeetPlatform)
    assert platform.name is PlatformName.GOOGLE_MEET


def test_an_unsupported_url_fails_before_a_browser_is_driven_at_it() -> None:
    with pytest.raises(UnsupportedPlatformError) as error:
        create_platform("https://zoom.us/j/12345", _StubBrowser(), MeetingSettings())  # type: ignore[arg-type]

    assert error.value.status_code == 400
    assert error.value.details["meeting_url"] == "https://zoom.us/j/12345"


def test_a_platform_can_be_registered_without_editing_the_registry() -> None:
    """The extension point that keeps adding Teams or Zoom out of meeting code."""
    sentinel = object()

    def build(_browser, _settings):  # type: ignore[no-untyped-def]
        return sentinel

    register_platform("example.test", PlatformName.GOOGLE_MEET, build)

    assert (
        create_platform("https://example.test/room/1", _StubBrowser(), MeetingSettings())  # type: ignore[arg-type]
        is sentinel
    )


def test_supported_platforms_is_reportable() -> None:
    assert "google_meet" in supported_platforms()


class _StubBrowser:
    """The registry only stores the browser; it never calls it."""

    is_available = True
