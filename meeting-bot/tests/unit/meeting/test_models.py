"""Tests for the public meeting/session identifier formats."""

from __future__ import annotations

import re

from app.core.config import ProjectSettings
from app.meeting.models import MeetingRequest, new_recording_meeting_id


def test_join_mints_session_id_from_meeting_code() -> None:
    request = MeetingRequest.build(
        meeting_url="https://meet.google.com/abc-defg-hij",
        defaults=ProjectSettings(),
    )

    assert re.fullmatch(r"abc-defg-hij_[0-9a-f]{32}", request.session_id)
    assert request.meeting_id == request.session_id


def test_recording_mints_meeting_id_from_code_and_india_datetime() -> None:
    meeting_id = new_recording_meeting_id("abc-defg-hij")

    assert re.fullmatch(r"abc-defg-hij_\d{8}T\d{12}IST", meeting_id)


def test_join_preserves_caller_supplied_session_id() -> None:
    request = MeetingRequest.build(
        meeting_url="https://meet.google.com/abc-defg-hij",
        defaults=ProjectSettings(),
        session_id="caller-session",
    )

    assert request.session_id == "caller-session"
    assert request.meeting_id == "caller-session"
