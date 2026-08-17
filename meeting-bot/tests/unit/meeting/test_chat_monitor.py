"""Tests for chat collection and command dispatch."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from app.meeting.chat_monitor import ChatMonitor
from app.meeting_platform.models import ChatMessage
from tests.conftest import FakePlatform

pytestmark = pytest.mark.asyncio


def message(text: str, *, message_id: str = "messages/1", sender: str = "Alice") -> ChatMessage:
    return ChatMessage(
        message_id=message_id,
        sender=sender,
        text=text,
        received_at=datetime.now(timezone.utc),
    )


async def _run_briefly(monitor: ChatMonitor, seconds: float = 0.05) -> None:
    await monitor.start()
    await asyncio.sleep(seconds)
    await monitor.stop()


async def test_messages_are_collected_once_each(fake_platform: FakePlatform) -> None:
    """The platform returns the whole panel each poll; each message counts once."""
    fake_platform.chat_script = [
        message("hello", message_id="messages/1"),
        message("world", message_id="messages/2"),
    ]
    monitor = ChatMonitor(
        platform=fake_platform, meeting_id="m", poll_interval_seconds=0.01
    )

    await _run_briefly(monitor)

    assert [m.text for m in monitor.messages] == ["hello", "world"]
    assert monitor.message_count == 2


async def test_registered_command_is_executed(fake_platform: FakePlatform) -> None:
    fake_platform.chat_script = [message("stormee start recording")]
    fired: list[str] = []
    monitor = ChatMonitor(
        platform=fake_platform, meeting_id="m", poll_interval_seconds=0.01
    )
    monitor.register_command("start recording", lambda _m: _append(fired, "start"))

    await _run_briefly(monitor)

    assert fired == ["start"]


async def test_longest_matching_command_wins(fake_platform: FakePlatform) -> None:
    """'start caption recording' must not be shadowed by 'start recording'."""
    fake_platform.chat_script = [message("stormee start caption recording")]
    fired: list[str] = []
    monitor = ChatMonitor(
        platform=fake_platform, meeting_id="m", poll_interval_seconds=0.01
    )
    monitor.register_command("start recording", lambda _m: _append(fired, "audio"))
    monitor.register_command("start caption recording", lambda _m: _append(fired, "caption"))

    await _run_briefly(monitor)

    assert fired == ["caption"]


async def test_messages_without_the_prefix_are_not_commands(
    fake_platform: FakePlatform,
) -> None:
    """Ordinary conversation must not trigger the bot."""
    fake_platform.chat_script = [message("should we start recording now?")]
    fired: list[str] = []
    monitor = ChatMonitor(
        platform=fake_platform, meeting_id="m", poll_interval_seconds=0.01
    )
    monitor.register_command("start recording", lambda _m: _append(fired, "start"))

    await _run_briefly(monitor)

    assert fired == []
    assert monitor.message_count == 1


async def test_commands_can_be_disabled(fake_platform: FakePlatform) -> None:
    fake_platform.chat_script = [message("stormee start recording")]
    fired: list[str] = []
    monitor = ChatMonitor(
        platform=fake_platform,
        meeting_id="m",
        commands_enabled=False,
        poll_interval_seconds=0.01,
    )
    monitor.register_command("start recording", lambda _m: _append(fired, "start"))

    await _run_briefly(monitor)

    assert fired == []


async def test_a_failing_command_does_not_stop_monitoring(
    fake_platform: FakePlatform,
) -> None:
    """A mistyped or broken command must not take the session down."""
    fake_platform.chat_script = [message("stormee explode", message_id="messages/1")]
    monitor = ChatMonitor(
        platform=fake_platform, meeting_id="m", poll_interval_seconds=0.01
    )
    monitor.register_command("explode", lambda _m: _raise())

    await monitor.start()
    await asyncio.sleep(0.03)
    fake_platform.chat_script.append(message("still here", message_id="messages/2"))
    await asyncio.sleep(0.03)
    await monitor.stop()

    assert monitor.message_count == 2


async def test_case_is_ignored_when_matching_commands(
    fake_platform: FakePlatform,
) -> None:
    fake_platform.chat_script = [message("Stormee START Recording")]
    fired: list[str] = []
    monitor = ChatMonitor(
        platform=fake_platform, meeting_id="m", poll_interval_seconds=0.01
    )
    monitor.register_command("start recording", lambda _m: _append(fired, "start"))

    await _run_briefly(monitor)

    assert fired == ["start"]


async def _append(sink: list[str], value: str) -> None:
    sink.append(value)


async def _raise() -> None:
    raise RuntimeError("command failed")
