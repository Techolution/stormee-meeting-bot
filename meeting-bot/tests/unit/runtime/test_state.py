"""Tests for runtime state and the session registry."""

from __future__ import annotations

import pytest

from app.core.exceptions import MeetingAlreadyActiveError, MeetingNotFoundError
from app.runtime.session import SessionRegistry
from app.runtime.state import ComponentState, RuntimeState, SessionState


def test_terminal_transition_stamps_an_end_time() -> None:
    state = RuntimeState(meeting_id="m", session_id="s")

    state.transition(SessionState.IN_MEETING)
    assert state.ended_at is None

    state.transition(SessionState.ENDED)
    assert state.ended_at is not None
    assert state.session_state.is_terminal


def test_failure_records_the_reason() -> None:
    state = RuntimeState(meeting_id="m", session_id="s")

    state.transition(SessionState.FAILED, error="browser would not start")

    assert state.last_error == "browser would not start"
    assert state.is_healthy is False


def test_a_dropped_websocket_degrades_rather_than_breaks_the_session() -> None:
    """Audio buffers locally while streaming is down, so the session is still viable."""
    state = RuntimeState(meeting_id="m", session_id="s")
    state.transition(SessionState.IN_MEETING)

    state.websocket.set(ComponentState.FAILED, reason="connection refused")

    assert state.is_healthy is True


def test_a_failed_recorder_makes_the_session_unhealthy() -> None:
    state = RuntimeState(meeting_id="m", session_id="s")
    state.transition(SessionState.IN_MEETING)

    state.recording.set(ComponentState.FAILED)

    assert state.is_healthy is False


def test_component_detail_accumulates_across_updates() -> None:
    state = RuntimeState(meeting_id="m", session_id="s")

    state.recording.set(ComponentState.ACTIVE, transport="websocket")
    state.recording.set(ComponentState.STOPPED, chunks=42)

    assert state.recording.detail == {"transport": "websocket", "chunks": 42}


def test_snapshot_is_json_serialisable() -> None:
    import json

    state = RuntimeState(meeting_id="m", session_id="s")
    state.transition(SessionState.IN_MEETING)
    state.beat()

    json.dumps(state.as_dict())  # must not raise


# --------------------------------------------------------------------------
# Registry
# --------------------------------------------------------------------------


class _Session:
    def __init__(self, meeting_id: str) -> None:
        self.meeting_id = meeting_id
        self.session_id = f"session-{meeting_id}"


@pytest.mark.asyncio
async def test_duplicate_join_is_refused_rather_than_silently_reusing() -> None:
    """Returning the existing session would report a fresh join that never happened."""
    registry = SessionRegistry()
    await registry.add(_Session("m1"))  # type: ignore[arg-type]

    with pytest.raises(MeetingAlreadyActiveError):
        await registry.add(_Session("m1"))  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_session_limit_is_enforced() -> None:
    """One browser per pod: a second concurrent meeting would compete for memory."""
    registry = SessionRegistry(max_sessions=1)
    await registry.add(_Session("m1"))  # type: ignore[arg-type]

    with pytest.raises(MeetingAlreadyActiveError, match="limit"):
        await registry.add(_Session("m2"))  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_require_raises_for_an_unknown_meeting() -> None:
    registry = SessionRegistry()

    with pytest.raises(MeetingNotFoundError):
        registry.require("ghost")


@pytest.mark.asyncio
async def test_removing_frees_the_slot() -> None:
    registry = SessionRegistry(max_sessions=1)
    await registry.add(_Session("m1"))  # type: ignore[arg-type]

    await registry.remove("m1")
    await registry.add(_Session("m2"))  # type: ignore[arg-type]

    assert registry.meeting_ids == ["m2"]


@pytest.mark.asyncio
async def test_numeric_meeting_ids_are_normalized_before_lookup() -> None:
    registry = SessionRegistry()
    await registry.add(_Session(1234))  # type: ignore[arg-type]

    assert registry.get("1234") is not None
    assert registry.require(1234) is not None
    assert list(registry._sessions) == ["1234"]


@pytest.mark.asyncio
async def test_clear_returns_everything_for_shutdown() -> None:
    registry = SessionRegistry()
    await registry.add(_Session("m1"))  # type: ignore[arg-type]
    await registry.add(_Session("m2"))  # type: ignore[arg-type]

    cleared = await registry.clear()

    assert {session.meeting_id for session in cleared} == {"m1", "m2"}
    assert len(registry) == 0
