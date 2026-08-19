"""Durable session state: transitions, timestamps, and duplicate handling."""

from __future__ import annotations

import pytest

from app.domain.enums import BotStatus, MeetingStatus, RecordingStatus, TranscriptionStatus
from app.domain.exceptions import SessionAlreadyExistsError, SessionNotFoundError
from app.domain.models import BotSession


def a_session(session_id: str = "sess-1") -> BotSession:
    return BotSession(
        session_id=session_id,
        meeting_id="demo-001",
        meeting_url="https://meet.google.com/abc-defg-hij",
    )


async def test_a_new_session_starts_created_and_pending(session_service):
    created = await session_service.create_session(a_session())

    assert created.meeting_status == MeetingStatus.CREATED
    assert created.bot_status == BotStatus.PENDING
    assert created.created_at is not None


async def test_creating_the_same_session_twice_is_refused(session_service):
    await session_service.create_session(a_session())

    with pytest.raises(SessionAlreadyExistsError):
        await session_service.create_session(a_session())


async def test_require_session_names_the_missing_id(session_service):
    with pytest.raises(SessionNotFoundError) as exc_info:
        await session_service.require_session("nope")

    assert exc_info.value.details["session_id"] == "nope"


async def test_lifecycle_transitions_stamp_their_times(session_service):
    session = await session_service.create_session(a_session())

    await session_service.mark_starting(session)
    assert session.starting_at is not None

    await session_service.mark_started(session, "bot-session-1")
    assert session.meeting_status == MeetingStatus.ACTIVE
    assert session.started_at is not None
    assert session.bot_session_id == "bot-session-1"

    await session_service.mark_leaving(session)
    assert session.leaving_at is not None

    await session_service.mark_completed(session)
    assert session.meeting_status == MeetingStatus.COMPLETED
    assert session.bot_status == BotStatus.STOPPED
    assert session.completed_at is not None


async def test_completion_closes_out_recording_and_transcription(session_service):
    session = await session_service.create_session(a_session())
    await session_service.set_recording_status(session, RecordingStatus.RECORDING)
    await session_service.set_transcription_status(session, TranscriptionStatus.RUNNING)

    await session_service.mark_completed(session)

    # leave finalizes both on the bot side; the record must agree.
    assert session.active_recording_status == RecordingStatus.STOPPED
    assert session.transcription_status == TranscriptionStatus.COMPLETED


async def test_failure_records_the_reason(session_service):
    session = await session_service.create_session(a_session())

    await session_service.mark_failed(session, "admission timed out")

    assert session.meeting_status == MeetingStatus.FAILED
    assert session.last_error == "admission timed out"
    assert session.failed_at is not None


async def test_the_active_recording_take_is_the_open_one(session_service):
    session = await session_service.create_session(a_session())
    first = await session_service.create_recording(session, RecordingStatus.RECORDING)

    active = await session_service.get_active_recording(session.session_id)
    assert active.recording_id == first.recording_id

    first.status = RecordingStatus.STOPPED
    await session_service.update_recording(first)

    assert await session_service.get_active_recording(session.session_id) is None


async def test_assignment_is_recorded_as_an_event(session_service):
    session = await session_service.create_session(a_session())

    await session_service.assign_bot(session, "http://10.0.0.2:5000", pod_name="bot-b")

    stored = await session_service.get_session("sess-1")
    assert stored.service_url == "http://10.0.0.2:5000"
    assert stored.worker_id == "bot-b"
    assert [e.event_type for e in stored.events] == ["session.created", "bot.assigned"]
