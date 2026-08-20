"""Where page audio goes when a meeting is recorded more than once.

Playwright binds a callback name to a page exactly once. Everything here is
about the consequence: the callback installed by the first recording is the one
that stays live, so it must not be tied to that recording's capture.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.meeting_platform.google_meet.platform import GoogleMeetPlatform

pytestmark = pytest.mark.asyncio


class OnceOnlyBrowser:
    """A page that accepts a callback name once, as the real one does.

    :class:`~app.browser.browser.Browser` checks whether the name already
    exists on ``window`` and returns False without re-binding. A test double
    that re-bound freely would hide the very behaviour these tests exist for.
    """

    def __init__(self) -> None:
        self.callback: Any = None
        self.rebinds_refused = 0

    async def expose_function(self, name: str, handler: Any) -> bool:
        if self.callback is not None:
            self.rebinds_refused += 1
            return False
        self.callback = handler
        return True


class Capture:
    """Stands in for AudioCapture: it can be stopped, and then ignores audio."""

    def __init__(self) -> None:
        self.received: list[str] = []
        self.active = True

    async def on_chunk(self, payload: dict) -> None:
        if not self.active:
            return
        self.received.append(payload["chunkId"])


async def test_a_second_recording_still_receives_page_audio() -> None:
    """The bug this guards: recording, stopping, and recording again captured nothing.

    The page kept delivering audio to the first recording's capture, which had
    been stopped, so every chunk was dropped and the second recording produced
    an empty file without reporting an error.
    """
    browser = OnceOnlyBrowser()
    platform = GoogleMeetPlatform(browser)  # type: ignore[arg-type]

    first = Capture()
    await platform.bind_chunk_sink(first)
    await browser.callback({"chunkId": "meeting-1-0"})

    # The meeting is recorded a second time: the first capture stops and a new
    # one takes over, exactly as Recorder.start does.
    first.active = False
    second = Capture()
    await platform.bind_chunk_sink(second)
    await browser.callback({"chunkId": "meeting-1-1"})

    assert browser.rebinds_refused == 1, "the page should refuse the second bind"
    assert first.received == ["meeting-1-0"]
    assert second.received == ["meeting-1-1"], "audio must follow the live recording"


async def test_audio_arriving_before_any_recording_is_dropped_quietly() -> None:
    """The callback outlives every recording, so it can fire with no sink bound."""
    browser = OnceOnlyBrowser()
    platform = GoogleMeetPlatform(browser)  # type: ignore[arg-type]

    capture = Capture()
    await platform.bind_chunk_sink(capture)
    platform._chunk_sink = None  # models the page outliving the recorder

    await browser.callback({"chunkId": "meeting-1-0"})

    assert capture.received == []
