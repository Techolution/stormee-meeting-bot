"""Tests for browser launch cleanup.

Every test here is about the same thing: a launch that does not succeed must not
leave a Playwright driver or a Chromium process behind. Three failed attempts
that each leak are enough to exhaust a modest pod, and an orphaned driver
outlives the meeting that started it.
"""

from __future__ import annotations

import asyncio
from typing import ClassVar

import pytest

from app.browser.browser_manager import BrowserManager, _LaunchResources
from app.browser.models import BrowserOptions
from app.core.exceptions import BrowserLaunchError

pytestmark = pytest.mark.asyncio


class _SpyResources(_LaunchResources):
    """Records whether the launch tracker was asked to clean up."""

    #: Shared across a test via the autouse reset fixture below.
    instances: ClassVar[list[_SpyResources]] = []

    def __init__(self) -> None:
        super().__init__()
        self.released = False
        _SpyResources.instances.append(self)

    async def release(self) -> None:
        self.released = True
        await super().release()


class _StubBrowser:
    """Minimal stand-in: `launch` logs `browser.mode.value` on success."""

    def __init__(self) -> None:
        self.mode = type("Mode", (), {"value": "ephemeral"})()


@pytest.fixture(autouse=True)
def _reset_spy() -> None:
    _SpyResources.instances.clear()


@pytest.fixture
def manager(monkeypatch: pytest.MonkeyPatch) -> BrowserManager:
    monkeypatch.setattr("app.browser.browser_manager._LaunchResources", _SpyResources)
    return BrowserManager(
        BrowserOptions(max_attempts=3, retry_delay_seconds=0.0, profile_dir=None)
    )


async def test_a_failed_launch_releases_what_it_opened(
    manager: BrowserManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def boom(_resources, _scripts):  # type: ignore[no-untyped-def]
        raise RuntimeError("chromium is not installed")

    monkeypatch.setattr(manager, "_launch_once", boom)

    with pytest.raises(BrowserLaunchError):
        await manager.launch()

    assert len(_SpyResources.instances) == 3, "should retry up to max_attempts"
    assert all(r.released for r in _SpyResources.instances), "every attempt must clean up"


async def test_a_cancelled_launch_still_releases_what_it_opened(
    manager: BrowserManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The regression: `except Exception` does not catch CancelledError.

    Shutdown cancels an in-flight join, so this is the path taken on SIGTERM
    during a browser launch. Without an explicit handler the partially-launched
    driver is orphaned.
    """
    started = asyncio.Event()

    async def hang(_resources, _scripts):  # type: ignore[no-untyped-def]
        started.set()
        await asyncio.sleep(60)

    monkeypatch.setattr(manager, "_launch_once", hang)

    task = asyncio.create_task(manager.launch())
    await started.wait()
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    assert len(_SpyResources.instances) == 1
    assert _SpyResources.instances[0].released is True


async def test_a_successful_launch_does_not_release(
    manager: BrowserManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ownership transfers to the Browser; the tracker must not close its resources."""
    sentinel = _StubBrowser()

    async def succeed(resources, _scripts):  # type: ignore[no-untyped-def]
        resources.disown()
        return sentinel

    monkeypatch.setattr(manager, "_launch_once", succeed)

    assert await manager.launch() is sentinel
    # release() is a no-op after disown, but it must not even be reached.
    assert _SpyResources.instances[0].released is False


async def test_launch_retries_then_reports_the_underlying_cause(
    manager: BrowserManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    attempts = 0
    sentinel = _StubBrowser()

    async def fail_twice(resources, _scripts):  # type: ignore[no-untyped-def]
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise RuntimeError("transient")
        resources.disown()
        return sentinel

    monkeypatch.setattr(manager, "_launch_once", fail_twice)

    assert await manager.launch() is sentinel
    assert attempts == 3
    # The two failed attempts each cleaned up; the successful one did not.
    assert [r.released for r in _SpyResources.instances] == [True, True, False]


async def test_exhausted_attempts_report_the_last_cause(
    manager: BrowserManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def boom(_resources, _scripts):  # type: ignore[no-untyped-def]
        raise RuntimeError("profile is locked")

    monkeypatch.setattr(manager, "_launch_once", boom)

    with pytest.raises(BrowserLaunchError) as error:
        await manager.launch()

    assert "profile is locked" in error.value.details["cause"]


async def test_cancelling_during_driver_startup_stops_the_driver(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cancellation landing inside driver startup must not orphan the subprocess.

    Starting the driver spawns a Node process. If cancellation interrupts that
    await, the handle is never returned while the process is already running —
    so it outlives the pod unless the start is allowed to finish first.
    """
    from app.browser import browser_manager

    stopped = asyncio.Event()
    started = asyncio.Event()

    class _Driver:
        async def stop(self) -> None:
            stopped.set()

    class _Starter:
        async def start(self) -> _Driver:
            started.set()
            await asyncio.sleep(0.05)  # the subprocess is coming up
            return _Driver()

    monkeypatch.setattr(browser_manager, "async_playwright", lambda: _Starter())

    task = asyncio.create_task(browser_manager._start_driver())
    await started.wait()
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    await asyncio.wait_for(stopped.wait(), timeout=1.0)
    assert stopped.is_set(), "the driver must be stopped, not orphaned"
