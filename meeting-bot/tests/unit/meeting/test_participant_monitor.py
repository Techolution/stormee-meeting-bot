"""Tests for participant monitoring and self-eviction.

The grace period is the behaviour that matters: a momentary drop to one
participant is routine, and leaving on it would abandon live meetings.
"""

from __future__ import annotations

import asyncio

import pytest

from app.meeting.participant_monitor import ParticipantMonitor
from app.meeting_platform.models import Participant
from tests.conftest import FakePlatform

pytestmark = pytest.mark.asyncio


def people(count: int) -> list[Participant]:
    return [Participant(f"id-{index}", f"Person {index}") for index in range(count)]


async def test_count_changes_are_reported(fake_platform: FakePlatform) -> None:
    fake_platform.participants = people(2)
    changes: list[tuple[int, int]] = []
    monitor = ParticipantMonitor(
        platform=fake_platform, meeting_id="m", poll_interval_seconds=0.01
    )
    monitor.on_count_change(lambda previous, current: _record(changes, previous, current))

    await monitor.start()
    fake_platform.participants = people(4)
    await asyncio.sleep(0.05)
    await monitor.stop()

    assert (2, 4) in changes
    assert monitor.count == 4


async def test_bot_leaves_after_the_grace_period_expires(
    fake_platform: FakePlatform,
) -> None:
    fake_platform.participants = people(1)
    left: list[bool] = []
    monitor = ParticipantMonitor(
        platform=fake_platform,
        meeting_id="m",
        poll_interval_seconds=0.01,
        solo_grace_period_seconds=0,
    )
    monitor.on_alone(lambda: _flag(left))

    await monitor.start()
    await asyncio.sleep(0.08)
    await monitor.stop()

    assert left == [True]


async def test_a_brief_dip_to_one_does_not_trigger_a_leave(
    fake_platform: FakePlatform,
) -> None:
    """This is the case a naive check gets wrong: reconnects look like an empty room."""
    fake_platform.participants = people(1)
    left: list[bool] = []
    monitor = ParticipantMonitor(
        platform=fake_platform,
        meeting_id="m",
        poll_interval_seconds=0.01,
        solo_grace_period_seconds=60,  # far longer than the test runs
    )
    monitor.on_alone(lambda: _flag(left))

    await monitor.start()
    await asyncio.sleep(0.03)
    fake_platform.participants = people(3)  # everyone comes back
    await asyncio.sleep(0.05)
    await monitor.stop()

    assert left == []
    assert monitor.count == 3


async def test_auto_leave_can_be_disabled(fake_platform: FakePlatform) -> None:
    fake_platform.participants = people(1)
    left: list[bool] = []
    monitor = ParticipantMonitor(
        platform=fake_platform,
        meeting_id="m",
        poll_interval_seconds=0.01,
        solo_grace_period_seconds=0,
        auto_leave_when_alone=False,
    )
    monitor.on_alone(lambda: _flag(left))

    await monitor.start()
    await asyncio.sleep(0.06)
    await monitor.stop()

    assert left == []


async def test_a_zero_reading_is_treated_as_unrendered_not_empty(
    fake_platform: FakePlatform,
) -> None:
    """The bot is always present, so zero means the tiles have not drawn yet."""
    fake_platform.participants = people(3)
    changes: list[tuple[int, int]] = []
    monitor = ParticipantMonitor(
        platform=fake_platform, meeting_id="m", poll_interval_seconds=0.01
    )
    monitor.on_count_change(lambda previous, current: _record(changes, previous, current))

    await monitor.start()
    fake_platform.participants = []
    await asyncio.sleep(0.05)
    await monitor.stop()

    assert changes == []
    assert monitor.count == 3


async def _record(sink: list[tuple[int, int]], previous: int, current: int) -> None:
    sink.append((previous, current))


async def _flag(sink: list[bool]) -> None:
    sink.append(True)
