"""Orchestration: dispatch, state transitions, idempotency, recovery."""

from __future__ import annotations

import asyncio

import httpx
import pytest

from app.application.bot_service_resolver import BotServiceResolver
from app.domain.enums import BotStatus, MeetingStatus, RecordingStatus, TranscriptionStatus
from app.domain.exceptions import (
    BotServiceNotAssignedError,
    InvalidSessionStateError,
    NoBotPodAvailableError,
    SessionNotFoundError,
)
from app.kubernetes.pod_pool import BotPodPool
from tests.conftest import FakeBot, FakeKubernetesClient, bot_transport, running_pod


class TestDispatch:
    async def test_start_assigns_a_pod_and_records_starting(
        self, handler, created_session, session_service, fake_bot
    ):
        result = await handler.start_bot("sess-1")

        assert result["bot_status"] == BotStatus.STARTING.value
        assert ("POST", "/meetings/join") in fake_bot.calls

        session = await session_service.get_session("sess-1")
        assert session.meeting_status == MeetingStatus.STARTING
        assert session.service_url == "http://bot-pod:5000"
        assert session.starting_at is not None

    async def test_dispatch_skips_a_busy_pod_and_takes_the_next(
        self, make_handler, session_service, settings, created_session
    ):
        busy, free = FakeBot(busy=True), FakeBot()
        http = httpx.AsyncClient(
            transport=bot_transport({"10.0.0.1": busy, "10.0.0.2": free})
        )
        pool = BotPodPool(
            kubernetes=FakeKubernetesClient(
                [running_pod("bot-busy", "10.0.0.1"), running_pod("bot-free", "10.0.0.2")]
            ),
            http_client=http,
            settings=settings,
        )
        handler = make_handler(http, pod_pool=pool, static_service_url=None)

        await handler.start_bot("sess-1")

        session = await session_service.get_session("sess-1")
        assert session.pod_name == "bot-free"
        assert ("POST", "/meetings/join") not in busy.calls

    async def test_dispatch_falls_through_to_the_next_pod_on_a_join_race(
        self, make_handler, session_service, settings, created_session
    ):
        # Both pods probe free, but the first is claimed before the join lands.
        first, second = FakeBot(claimed_after_probe=True), FakeBot()
        http = httpx.AsyncClient(
            transport=bot_transport({"10.0.0.1": first, "10.0.0.2": second})
        )
        pool = BotPodPool(
            kubernetes=FakeKubernetesClient(
                [running_pod("bot-a", "10.0.0.1"), running_pod("bot-b", "10.0.0.2")]
            ),
            http_client=http,
            settings=settings,
        )
        handler = make_handler(http, pod_pool=pool, static_service_url=None)

        await handler.start_bot("sess-1")

        session = await session_service.get_session("sess-1")
        assert session.pod_name == "bot-b"
        assert ("POST", "/meetings/join") in first.calls  # it was tried

    async def test_no_free_pod_is_a_distinct_failure(
        self, make_handler, session_service, settings, created_session
    ):
        busy = FakeBot(busy=True)
        http = httpx.AsyncClient(transport=bot_transport({"10.0.0.1": busy}))
        pool = BotPodPool(
            kubernetes=FakeKubernetesClient([running_pod("bot-busy", "10.0.0.1")]),
            http_client=http,
            settings=settings,
        )
        handler = make_handler(http, pod_pool=pool, static_service_url=None)

        with pytest.raises(NoBotPodAvailableError):
            await handler.start_bot("sess-1")

        session = await session_service.get_session("sess-1")
        assert session.bot_status == BotStatus.PENDING  # nothing was claimed

    async def test_starting_twice_is_refused(self, handler, created_session):
        await handler.start_bot("sess-1")

        with pytest.raises(InvalidSessionStateError):
            await handler.start_bot("sess-1")

    async def test_unknown_session_is_reported_as_such(self, handler):
        with pytest.raises(SessionNotFoundError):
            await handler.start_bot("nope")

    async def test_a_command_before_dispatch_is_refused(
        self, make_handler, http_client, created_session
    ):
        # No discovery, no static bot: there is nowhere to send the command,
        # and saying so beats a 500 from a None URL.
        handler = make_handler(http_client, static_service_url=None)

        with pytest.raises(BotServiceNotAssignedError):
            await handler.start_recording("sess-1")


class TestJoinWatcher:
    async def test_session_becomes_active_once_the_bot_is_admitted(
        self, handler, created_session, session_service, fake_bot
    ):
        await handler.start_bot("sess-1")
        fake_bot.admit()

        await _settle(session_service, "sess-1", BotStatus.RUNNING)

        session = await session_service.get_session("sess-1")
        assert session.meeting_status == MeetingStatus.ACTIVE
        assert session.started_at is not None
        assert session.bot_session_id == "bot-session-1"

    async def test_a_join_that_never_completes_fails_the_session(
        self, handler, created_session, session_service
    ):
        await handler.start_bot("sess-1")  # never admitted

        await _settle(session_service, "sess-1", BotStatus.FAILED)

        session = await session_service.get_session("sess-1")
        assert session.meeting_status == MeetingStatus.FAILED
        assert "never reached the meeting" in session.last_error


class TestRecording:
    async def test_start_then_stop_tracks_a_recording_take(
        self, handler, created_session, session_service
    ):
        await handler.start_bot("sess-1")

        started = await handler.start_recording("sess-1")
        assert started["recording_status"] == RecordingStatus.RECORDING.value

        await handler.stop_recording("sess-1")

        session = await session_service.get_session("sess-1")
        assert session.active_recording_status == RecordingStatus.STOPPED
        take = session.recordings[0]
        assert take.status == RecordingStatus.STOPPED
        # Final counters are reconciled from the bot, not assumed.
        assert take.chunks_uploaded == 48
        assert take.bytes_uploaded == 3145728
        assert take.stopped_at is not None

    async def test_recording_twice_is_refused(self, handler, created_session):
        await handler.start_bot("sess-1")
        await handler.start_recording("sess-1")

        with pytest.raises(InvalidSessionStateError):
            await handler.start_recording("sess-1")

    async def test_stopping_a_recording_that_is_not_running_is_a_no_op(
        self, handler, created_session, fake_bot
    ):
        await handler.start_bot("sess-1")

        result = await handler.stop_recording("sess-1")

        assert result["recording_status"] == RecordingStatus.NOT_STARTED.value
        assert ("POST", "/recordings/stop") not in fake_bot.calls


class TestTranscription:
    async def test_start_and_stop_move_the_status(
        self, handler, created_session, session_service
    ):
        await handler.start_bot("sess-1")

        await handler.start_transcription("sess-1")
        session = await session_service.get_session("sess-1")
        assert session.transcription_status == TranscriptionStatus.RUNNING

        await handler.stop_transcription("sess-1")
        session = await session_service.get_session("sess-1")
        assert session.transcription_status == TranscriptionStatus.COMPLETED

    async def test_stopping_transcription_that_never_started_is_a_no_op(
        self, handler, created_session, fake_bot
    ):
        await handler.start_bot("sess-1")

        await handler.stop_transcription("sess-1")

        assert ("POST", "/transcription/stop") not in fake_bot.calls


class TestLeave:
    async def test_leave_completes_the_session(
        self, handler, created_session, session_service, fake_bot
    ):
        await handler.start_bot("sess-1")

        await handler.leave("sess-1")

        session = await session_service.get_session("sess-1")
        assert session.meeting_status == MeetingStatus.COMPLETED
        assert session.completed_at is not None
        assert ("POST", "/meetings/leave") in fake_bot.calls

    async def test_leaving_twice_is_a_no_op(self, handler, created_session):
        await handler.start_bot("sess-1")
        await handler.leave("sess-1")

        result = await handler.leave("sess-1")

        assert result["meeting_status"] == MeetingStatus.COMPLETED.value

    async def test_leaving_a_session_that_was_never_dispatched_completes_it(
        self, handler, created_session, session_service, fake_bot
    ):
        await handler.leave("sess-1")

        session = await session_service.get_session("sess-1")
        assert session.meeting_status == MeetingStatus.COMPLETED
        assert fake_bot.calls == []

    async def test_a_recording_left_running_is_marked_stopped(
        self, handler, created_session, session_service
    ):
        await handler.start_bot("sess-1")
        await handler.start_recording("sess-1")

        await handler.leave("sess-1")

        session = await session_service.get_session("sess-1")
        assert session.active_recording_status == RecordingStatus.STOPPED


class TestStatus:
    async def test_status_merges_durable_state_with_the_live_pod_view(
        self, handler, created_session, fake_bot
    ):
        await handler.start_bot("sess-1")
        fake_bot.admit()

        status = await handler.get_status("sess-1")

        assert status["runtime"]["session_state"] == "in_meeting"
        # Reading the pod reconciles the record.
        assert status["bot_status"] == BotStatus.RUNNING.value
        assert status["runtime_error"] is None

    async def test_an_unreachable_pod_degrades_the_status_rather_than_failing_it(
        self, make_handler, session_service, created_session
    ):
        offline = FakeBot(offline=True)
        handler = make_handler(
            httpx.AsyncClient(transport=bot_transport({"bot-pod": offline}))
        )
        session = await session_service.get_session("sess-1")
        await session_service.assign_bot(session, "http://bot-pod:5000", pod_name="bot-a")

        status = await handler.get_status("sess-1")

        assert status["runtime"] is None
        assert "unreachable" in status["runtime_error"]

    async def test_runtime_can_be_skipped(self, handler, created_session, fake_bot):
        await handler.start_bot("sess-1")
        calls_before = len(fake_bot.calls)

        status = await handler.get_status("sess-1", include_runtime=False)

        assert status["runtime"] is None
        assert len(fake_bot.calls) == calls_before


class TestRecovery:
    async def test_a_lost_assignment_is_recovered_from_the_cluster(
        self, make_handler, session_service, settings, created_session
    ):
        # The handler restarted and lost the pod assignment; the meeting is
        # still running on a pod that can be found by asking.
        holder = FakeBot()
        holder.meeting_id = "demo-001"
        http = httpx.AsyncClient(transport=bot_transport({"10.0.0.2": holder}))
        pool = BotPodPool(
            kubernetes=FakeKubernetesClient([running_pod("bot-b", "10.0.0.2")]),
            http_client=http,
            settings=settings,
        )
        resolver = BotServiceResolver(pod_pool=pool, static_service_url=None)

        target = await resolver.resolve(await session_service.get_session("sess-1"))

        assert target.pod_name == "bot-b"


async def _settle(session_service, session_id: str, expected: BotStatus, tries: int = 200) -> None:
    """Wait for the background join watcher to reach a conclusion."""
    for _ in range(tries):
        session = await session_service.get_session(session_id)
        if session.bot_status == expected:
            return
        await asyncio.sleep(0.01)
    pytest.fail(f"session stayed at {session.bot_status}, expected {expected}")
