"""Tests for lifecycle ordering.

The two rules under test are the reason the module exists: startup stops at a
critical failure, and shutdown never stops at all.
"""

from __future__ import annotations

import asyncio

import pytest

from app.meeting.lifecycle import LifecycleRunner, LifecycleStep

pytestmark = pytest.mark.asyncio


def _recorder(log: list[str], name: str, *, fail: bool = False, hang: bool = False):
    async def action() -> None:
        log.append(name)
        if hang:
            await asyncio.sleep(10)
        if fail:
            raise RuntimeError(f"{name} failed")

    return action


async def test_startup_runs_steps_in_declared_order() -> None:
    log: list[str] = []
    runner = LifecycleRunner(meeting_id="m")

    await runner.start(
        [
            LifecycleStep("first", _recorder(log, "first")),
            LifecycleStep("second", _recorder(log, "second")),
            LifecycleStep("third", _recorder(log, "third")),
        ]
    )

    assert log == ["first", "second", "third"]


async def test_critical_startup_failure_stops_the_sequence() -> None:
    """Continuing past a failed browser launch only produces a worse error later."""
    log: list[str] = []
    runner = LifecycleRunner(meeting_id="m")

    with pytest.raises(RuntimeError, match="launch"):
        await runner.start(
            [
                LifecycleStep("launch", _recorder(log, "launch", fail=True)),
                LifecycleStep("join", _recorder(log, "join")),
            ]
        )

    assert log == ["launch"]


async def test_optional_startup_failure_is_survivable() -> None:
    """A missing audio service degrades the session; it does not end it."""
    log: list[str] = []
    runner = LifecycleRunner(meeting_id="m")

    results = await runner.start(
        [
            LifecycleStep("connect", _recorder(log, "connect", fail=True), critical=False),
            LifecycleStep("monitors", _recorder(log, "monitors")),
        ]
    )

    assert log == ["connect", "monitors"]
    assert [result.succeeded for result in results] == [False, True]


async def test_shutdown_runs_every_step_despite_failures() -> None:
    """The browser must be released even if leaving the meeting failed."""
    log: list[str] = []
    runner = LifecycleRunner(meeting_id="m")

    results = await runner.shutdown(
        [
            LifecycleStep("stop_recording", _recorder(log, "stop_recording", fail=True)),
            LifecycleStep("leave", _recorder(log, "leave", fail=True)),
            LifecycleStep("close_browser", _recorder(log, "close_browser")),
        ]
    )

    assert log == ["stop_recording", "leave", "close_browser"]
    assert [result.succeeded for result in results] == [False, False, True]


async def test_a_hung_shutdown_step_cannot_block_the_rest() -> None:
    """A leave-call that never returns must not strand the browser."""
    log: list[str] = []
    runner = LifecycleRunner(meeting_id="m")

    results = await runner.shutdown(
        [
            LifecycleStep("leave", _recorder(log, "leave", hang=True), timeout_seconds=0.05),
            LifecycleStep("close_browser", _recorder(log, "close_browser")),
        ]
    )

    assert log == ["leave", "close_browser"]
    assert results[0].succeeded is False
    assert "timed out" in (results[0].error or "")
    assert results[1].succeeded is True


async def test_shutdown_never_raises() -> None:
    runner = LifecycleRunner(meeting_id="m")

    results = await runner.shutdown(
        [LifecycleStep("boom", _recorder([], "boom", fail=True))]
    )

    assert results[0].succeeded is False
