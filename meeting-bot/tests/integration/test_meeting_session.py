"""End-to-end session behaviour, with no browser and no network.

Every collaborator a session reaches is behind an interface, so the whole
join → record → transcribe → leave flow runs against fakes. That is the
practical test of whether the abstractions are real: if a session could only be
tested with Chromium running, they would not be.
"""

from __future__ import annotations

import pytest

from app.core.config import Settings
from app.meeting.meeting_session import MeetingSession
from app.meeting.models import MeetingRequest
from app.meeting.session_dependencies import SessionDependencies
from app.recording.models import RecordingStatus
from app.repositories.base import MeetingLifecycleEvent
from app.repositories.memory_repository import InMemoryStateRepository
from app.runtime.state import ComponentState, SessionState
from tests.conftest import FakeCWClient, FakePlatform, FakeStorage, caption, wait_for

pytestmark = pytest.mark.asyncio

BLOCK = 256 * 1024


@pytest.fixture
def session_parts(settings: Settings, monkeypatch: pytest.MonkeyPatch):
    """A session wired to fakes, with the browser and platform stubbed out.

    Patching only the two boundaries that need a real browser keeps the rest of
    the session — lifecycle ordering, state transitions, the recording pipeline —
    genuinely under test.
    """
    platform = FakePlatform()
    cw = FakeCWClient()
    storage = FakeStorage()
    repository = InMemoryStateRepository()

    dependencies = SessionDependencies(
        settings=settings,
        browser_manager=_StubBrowserManager(),
        state_repository=repository,
        cw_client=cw,  # type: ignore[arg-type]
        storage_client=storage,  # type: ignore[arg-type]
        mail_client=None,
        meeting_api_client=None,
    )

    request = MeetingRequest.build(
        meeting_id="meeting-1",
        meeting_url="https://meet.google.com/abc-defg-hij",
        defaults=settings.project,
        user_name="Alice",
        user_email="alice@example.com",
        project_id="project-test",
        meeting_title="Weekly Sync",
    )

    session = MeetingSession(request, dependencies)
    # The platform is normally built from the launched browser; substitute ours.
    monkeypatch.setattr(session, "_create_platform", _install(session, platform))

    return session, platform, cw, storage, repository


def _install(session: MeetingSession, platform: FakePlatform):
    async def create_platform() -> None:
        session._platform = platform

    return create_platform


class _StubBrowser:
    is_available = True
    url = "https://meet.google.com/abc-defg-hij"

    from app.browser.models import SessionMode

    mode = SessionMode.EPHEMERAL

    def __init__(self) -> None:
        self.closed = False

    async def close(self) -> None:
        self.closed = True


class _StubBrowserManager:
    def __init__(self) -> None:
        self.browsers: list[_StubBrowser] = []

    async def launch(self, *, init_scripts: tuple[str, ...] = ()) -> _StubBrowser:
        browser = _StubBrowser()
        self.browsers.append(browser)
        return browser


# --------------------------------------------------------------------------
# Join
# --------------------------------------------------------------------------


async def test_join_brings_the_session_live_and_records_it(session_parts) -> None:
    session, _platform, _cw, _storage, repository = session_parts

    await session.start()

    assert session.state.session_state is SessionState.IN_MEETING
    assert session.is_live
    assert session.state.browser.state is ComponentState.ACTIVE
    assert session.state.platform.state is ComponentState.ACTIVE

    events = [record.event for record in await repository.history("meeting-1")]
    assert MeetingLifecycleEvent.IN_MEETING in events
    assert MeetingLifecycleEvent.JOINING in events

    await session.stop()


async def test_a_failed_join_releases_the_browser(session_parts, monkeypatch) -> None:
    """A failed join must not leak a Chromium process."""
    session, platform, _cw, _storage, repository = session_parts

    async def refuse(_request):
        raise RuntimeError("host never admitted the bot")

    monkeypatch.setattr(platform, "join", refuse)

    with pytest.raises(Exception, match="admitted"):
        await session.start()

    assert session.state.session_state is SessionState.FAILED
    manager = session._deps.browser_manager
    assert manager.browsers and manager.browsers[0].closed is True

    events = [record.event for record in await repository.history("meeting-1")]
    assert MeetingLifecycleEvent.FAILED in events


# --------------------------------------------------------------------------
# Recording
# --------------------------------------------------------------------------


async def test_recording_flows_from_page_chunk_to_stored_object(session_parts) -> None:
    """The full audio path, driven by the page callback the platform would install."""
    session, platform, cw, storage, _repository = session_parts
    await session.start()

    await session.start_recording()
    assert session.recorder is not None
    assert session.recorder.status is RecordingStatus.RECORDING
    assert platform.recording is True
    assert platform.sink is not None, "recorder must bind a chunk sink before starting"

    # Emit two full blocks' worth of audio the way the browser does.
    for sequence in range(2):
        await platform.sink.on_chunk(
            {
                "meetingId": "meeting-1",
                "chunkId": f"meeting-1-{sequence}",
                "audioBlob": [sequence] * BLOCK,
            }
        )

    await session.stop_recording()

    assert session.recorder.status is RecordingStatus.STOPPED
    assert session.recorder.stats.chunks_captured == 2
    # Two whole blocks, then a final empty flush that closes the object.
    assert storage.blocks[0] == (BLOCK, False)
    assert storage.blocks[-1][1] is True
    assert len(storage.data) == 2 * BLOCK

    # A completed upload is registered and follow-up work is requested.
    assert len(cw.confirmed) == 1
    assert len(cw.artifacts) == 1

    await session.stop()


async def test_recording_twice_is_refused(session_parts) -> None:
    session, _platform, _cw, _storage, _repository = session_parts
    await session.start()
    await session.start_recording()

    from app.core.exceptions import RecordingAlreadyActiveError

    with pytest.raises(RecordingAlreadyActiveError):
        await session.start_recording()

    await session.stop()


async def test_stopping_a_session_finalizes_a_running_recording(session_parts) -> None:
    """The critical shutdown guarantee: audio captured is audio stored."""
    session, platform, cw, storage, _repository = session_parts
    await session.start()
    await session.start_recording()

    assert platform.sink is not None
    await platform.sink.on_chunk(
        {"meetingId": "meeting-1", "chunkId": "meeting-1-0", "audioBlob": [7] * 2048}
    )

    await session.stop()  # no explicit stop_recording

    assert storage.blocks[-1][1] is True, "final block must close the object"
    assert bytes(storage.data) == bytes([7]) * 2048
    assert len(cw.confirmed) == 1
    assert session.state.session_state is SessionState.ENDED


async def test_malformed_page_chunks_do_not_break_a_recording(session_parts) -> None:
    session, platform, _cw, storage, _repository = session_parts
    await session.start()
    await session.start_recording()

    assert platform.sink is not None
    await platform.sink.on_chunk({"audioBlob": [1, 2, 3]})  # no ids — must be ignored
    await platform.sink.on_chunk(
        {"meetingId": "meeting-1", "chunkId": "meeting-1-0", "audioBlob": [9] * 512}
    )

    await session.stop_recording()

    assert bytes(storage.data) == bytes([9]) * 512
    await session.stop()


# --------------------------------------------------------------------------
# Transcription
# --------------------------------------------------------------------------


async def test_transcription_produces_a_deduplicated_transcript(session_parts) -> None:
    session, platform, _cw, _storage, _repository = session_parts
    # Three snapshots of one growing utterance, then a different speaker. This is
    # what polling live captions actually looks like.
    platform.caption_script = [
        [caption("Alice", "Let us")],
        [caption("Alice", "Let us begin")],
        [caption("Alice", "Let us begin the review")],
        [caption("Bob", "Sounds good")],
    ]
    await session.start()

    await session.start_transcription()
    await wait_for(lambda: platform.captions_consumed >= 4)
    segments = await session.stop_transcription()

    texts = [segment.text for segment in segments]
    assert "Let us begin the review" in texts
    assert texts.count("Let us begin the review") == 1, "growing captions must not repeat"
    assert "Sounds good" in texts

    await session.stop()


async def test_transcript_segments_reach_the_context_buffer(session_parts) -> None:
    session, platform, _cw, _storage, _repository = session_parts
    platform.caption_script = [[caption("Alice", "first thing")], [caption("Bob", "second")]]
    await session.start()

    await session.start_transcription()
    await wait_for(lambda: platform.captions_consumed >= 2)
    await session.stop_transcription()

    stored = await session._context.recent()
    assert any("first thing" in item.content for item in stored)

    await session.stop()


async def test_stopping_transcription_that_never_started_is_an_error(session_parts) -> None:
    session, _platform, _cw, _storage, _repository = session_parts
    await session.start()

    from app.core.exceptions import TranscriptionNotActiveError

    with pytest.raises(TranscriptionNotActiveError):
        await session.stop_transcription()

    await session.stop()


# --------------------------------------------------------------------------
# Shutdown
# --------------------------------------------------------------------------


async def test_stop_is_idempotent(session_parts) -> None:
    """Shutdown is reachable from several paths; it must be safe to run twice."""
    session, _platform, _cw, _storage, _repository = session_parts
    await session.start()

    await session.stop()
    await session.stop()

    assert session.state.session_state is SessionState.ENDED


async def test_shutdown_leaves_the_meeting_and_closes_the_browser(session_parts) -> None:
    session, platform, _cw, _storage, _repository = session_parts
    await session.start()

    await session.stop()

    assert platform.left is True
    manager = session._deps.browser_manager
    assert manager.browsers[0].closed is True


async def test_shutdown_completes_even_when_leaving_fails(session_parts, monkeypatch) -> None:
    """A stuck leave-call must never strand the browser."""
    session, platform, _cw, _storage, _repository = session_parts
    await session.start()

    async def fail_leave() -> None:
        raise RuntimeError("leave button not found")

    monkeypatch.setattr(platform, "leave", fail_leave)

    await session.stop()

    manager = session._deps.browser_manager
    assert manager.browsers[0].closed is True
    assert session.state.session_state is SessionState.ENDED


async def test_status_snapshot_needs_no_io(session_parts) -> None:
    """The status endpoint polls this; it must never touch the browser or network."""
    session, _platform, _cw, _storage, _repository = session_parts
    await session.start()

    snapshot = session.status_snapshot()

    assert snapshot["meeting_id"] == "meeting-1"
    assert snapshot["session_id"] == session.session_id
    assert snapshot["session_state"] == SessionState.IN_MEETING.value
    assert "websocket" in snapshot
    assert snapshot["healthy"] is True

    await session.stop()


# --------------------------------------------------------------------------
# Streaming transport
# --------------------------------------------------------------------------


@pytest.fixture
def streaming_session_parts(settings: Settings, monkeypatch: pytest.MonkeyPatch):
    """A session with an audio service configured but unreachable.

    Covers the streaming branch of startup, which the default fixture skips
    entirely because no ``WEBSOCKET_URL`` is set. A type error on that branch
    once made every streaming deployment silently fall back to buffering.
    """
    from app.core.config import Settings as SettingsModel

    monkeypatch.setenv("WEBSOCKET_URL", "http://audio.test.invalid:9")
    monkeypatch.setenv("WEBSOCKET_MAX_RECONNECT_ATTEMPTS", "1")
    monkeypatch.setenv("WEBSOCKET_CONNECT_TIMEOUT_SECONDS", "0.2")
    monkeypatch.setenv("WEBSOCKET_AUTO_RECONNECT", "false")
    streaming_settings = SettingsModel(_env_file=None)

    platform = FakePlatform()
    dependencies = SessionDependencies(
        settings=streaming_settings,
        browser_manager=_StubBrowserManager(),
        state_repository=InMemoryStateRepository(),
        cw_client=FakeCWClient(),  # type: ignore[arg-type]
        storage_client=FakeStorage(),  # type: ignore[arg-type]
    )
    request = MeetingRequest.build(
        meeting_id="meeting-ws",
        meeting_url="https://meet.google.com/abc-defg-hij",
        defaults=streaming_settings.project,
        project_id="project-test",
    )

    session = MeetingSession(request, dependencies)
    monkeypatch.setattr(session, "_create_platform", _install(session, platform))
    return session, platform


async def test_an_unreachable_audio_service_degrades_the_session_rather_than_failing_it(
    streaming_session_parts,
) -> None:
    """Audio buffers locally while streaming is down, so the meeting continues."""
    session, _platform = streaming_session_parts

    await session.start()

    assert session.state.session_state is SessionState.IN_MEETING
    assert session.state.websocket.state is ComponentState.DEGRADED
    assert session.state.websocket.detail["connection_state"]
    # The websocket is explicitly excluded from the health calculation.
    assert session.state.is_healthy is True

    await session.stop()


async def test_recording_buffers_when_the_audio_service_is_unreachable(
    streaming_session_parts,
) -> None:
    session, platform = streaming_session_parts
    await session.start()
    await session.start_recording()

    assert session.recorder is not None
    assert session.recorder.transport == "websocket"

    assert platform.sink is not None
    await platform.sink.on_chunk(
        {"meetingId": "meeting-ws", "chunkId": "meeting-ws-0", "audioBlob": [3] * 1024}
    )

    # Captured, and held rather than lost.
    assert session.recorder.stats.chunks_captured == 1
    assert session.recorder.pending_chunks == 1

    await session.stop()
