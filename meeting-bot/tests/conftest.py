"""Shared fixtures.

The fakes here are the practical payoff of the interfaces in ``app``: a meeting
session can be exercised with no browser, no socket and no network, because
every collaborator it reaches is an abstraction with a test double.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

import pytest

from app.clients.cw_utils import ResumableUploadTarget
from app.core.config import Settings
from app.meeting_platform.base import ChunkSink, MeetingPlatform
from app.meeting_platform.models import (
    AudioPlaybackRequest,
    CaptionLine,
    ChatMessage,
    JoinRequest,
    JoinResult,
    MeetingRoomState,
    Participant,
    PlatformName,
    RecordingHandle,
)
from app.recording.models import AudioChunk


@pytest.fixture
def settings(monkeypatch: pytest.MonkeyPatch) -> Settings:
    """Settings built from a known environment, isolated from the developer's own.

    Every ``MEETING_``/``REDIS_``/… variable is cleared so a local ``.env`` or
    exported shell variable cannot change a test's outcome.
    """
    for prefix in (
        "APP_", "ENV", "ENVIRONMENT", "LOG_", "BROWSER_", "HEADLESS", "PROFILE_DIR",
        "MEETING_", "RECORDING_", "TRANSCRIPTION_", "WEBSOCKET_", "CW_", "BACKEND_URL",
        "MAIL_", "REDIS_", "PROJECT_", "DEFAULT_USER_", "AUDIO_QUEUE_", "WAIT_TIME_",
    ):
        for key in [name for name in list(__import__("os").environ) if name.startswith(prefix)]:
            monkeypatch.delenv(key, raising=False)

    monkeypatch.setenv("ENVIRONMENT", "local")
    monkeypatch.setenv("CW_UTILS_URL", "https://cw.test.invalid")
    monkeypatch.setenv("REDIS_ENABLED", "false")
    monkeypatch.setenv("PROJECT_ID", "project-test")
    monkeypatch.setenv("PROJECT_NAME", "Test Project")
    monkeypatch.setenv("DEFAULT_USER_NAME", "Test User")
    monkeypatch.setenv("DEFAULT_USER_EMAIL", "test@example.com")

    # Production timings make a test suite unusably slow: a 1s caption poll and a
    # 2s finalize grace period turn each session test into seconds of sleeping.
    monkeypatch.setenv("TRANSCRIPTION_POLL_INTERVAL_SECONDS", "0.01")
    monkeypatch.setenv("MEETING_PARTICIPANT_POLL_INTERVAL_SECONDS", "0.05")
    monkeypatch.setenv("RECORDING_FINALIZE_GRACE_PERIOD_SECONDS", "0")
    # The fake platform reports a single participant, which reads as "the bot is
    # alone". A long grace period keeps auto-leave from firing mid-test; the
    # eviction behaviour itself is covered in test_participant_monitor.py.
    monkeypatch.setenv("MEETING_SOLO_GRACE_PERIOD_SECONDS", "3600")

    # Nested settings groups read the environment themselves, so building the
    # root object picks up the values above without an env file.
    return Settings(_env_file=None)


# --------------------------------------------------------------------------
# Fakes
# --------------------------------------------------------------------------


class FakePlatform(MeetingPlatform):
    """A meeting platform with no browser behind it.

    Scriptable: set ``caption_script`` to a list of snapshots and each call to
    ``get_captions`` returns the next one.
    """

    name = PlatformName.GOOGLE_MEET

    def __init__(self) -> None:
        self.room_state = MeetingRoomState.IN_MEETING
        self.participants: list[Participant] = [Participant("bot", "Bot")]
        self.caption_script: list[list[CaptionLine]] = []
        self.chat_script: list[ChatMessage] = []
        self.captions_enabled = False
        self.chat_open = False
        self.mic_on = False
        self.camera_on = True
        self.left = False
        self.recording = False
        self.played: list[AudioPlaybackRequest] = []
        self.sink: ChunkSink | None = None
        self._caption_index = 0

    async def join(self, request: JoinRequest) -> JoinResult:
        return JoinResult(admitted=True, state=MeetingRoomState.IN_MEETING, waited_seconds=0.1)

    async def leave(self) -> None:
        self.left = True

    async def get_room_state(self) -> MeetingRoomState:
        return self.room_state

    async def get_participants(self) -> list[Participant]:
        return list(self.participants)

    @property
    def captions_consumed(self) -> int:
        """Snapshots served so far, so a test can wait on progress rather than sleep."""
        return self._caption_index

    async def get_captions(self) -> list[CaptionLine]:
        if self._caption_index >= len(self.caption_script):
            return []
        snapshot = self.caption_script[self._caption_index]
        self._caption_index += 1
        return snapshot

    async def get_chat_messages(self) -> list[ChatMessage]:
        return list(self.chat_script)

    async def mute_microphone(self) -> bool:
        self.mic_on = False
        return True

    async def unmute_microphone(self) -> bool:
        self.mic_on = True
        return True

    async def is_microphone_on(self) -> bool:
        return self.mic_on

    async def disable_camera(self) -> bool:
        self.camera_on = False
        return True

    async def enable_captions(self) -> bool:
        self.captions_enabled = True
        return True

    async def open_chat_panel(self) -> bool:
        self.chat_open = True
        return True

    async def play_audio(self, request: AudioPlaybackRequest) -> bool:
        self.played.append(request)
        return True

    async def start_recording(self, meeting_id: str, *, chunk_duration_ms: int) -> RecordingHandle:
        self.recording = True
        return RecordingHandle(meeting_id=meeting_id, chunk_duration_ms=chunk_duration_ms)

    async def stop_recording(self) -> None:
        self.recording = False

    async def bind_chunk_sink(self, sink: ChunkSink) -> None:
        self.sink = sink


class FakeAudioService:
    """Stands in for :class:`~app.clients.audio_service.AudioServiceClient`.

    Faithful to the real contract in the way that matters: sending while
    disconnected raises :class:`WebSocketNotConnectedError`, exactly as the
    transport does. A fake that silently accepted those sends would hide the
    buffering behaviour it exists to test.
    """

    def __init__(self, *, connected: bool = True) -> None:
        self.is_connected = connected
        self.sent: list[dict[str, Any]] = []
        self.transcripts: list[dict[str, Any]] = []
        self.recording_ended: list[Any] = []

        #: Start failing once this many sends have succeeded. Models a link that
        #: goes down partway through a drain and stays down.
        self.fail_from: int | None = None

    async def send_audio_chunk(self, payload: dict[str, Any]) -> None:
        from app.core.exceptions import WebSocketNotConnectedError

        if not self.is_connected:
            raise WebSocketNotConnectedError("fake audio service is not connected")
        if self.fail_from is not None and len(self.sent) >= self.fail_from:
            raise RuntimeError("simulated send failure")
        self.sent.append(payload)

    async def send_transcript_segment(self, payload: dict[str, Any]) -> None:
        self.transcripts.append(payload)

    async def notify_recording_ended(self, event: Any, *, timeout_seconds: float = 30.0) -> None:
        self.recording_ended.append(event)
        return None


class FakeCWClient:
    """Stands in for :class:`~app.clients.cw_utils.CWUtilsClient`."""

    def __init__(self) -> None:
        self.confirmed: list[dict[str, Any]] = []
        self.artifacts: list[dict[str, Any]] = []
        self.upload_targets = 0
        self.fail_target = False

    async def create_resumable_upload(
        self, *, project_id: str, filename: str, content_type: str
    ) -> ResumableUploadTarget:
        if self.fail_target:
            raise RuntimeError("simulated signed-url failure")
        self.upload_targets += 1
        return ResumableUploadTarget(
            upload_url=f"https://storage.test.invalid/upload/{filename}",
            public_url=f"https://storage.test.invalid/public/{filename}",
        )

    async def confirm_upload(self, **kwargs: Any) -> dict[str, Any]:
        self.confirmed.append(kwargs)
        return {"uploaded_files": [{"name": "recording.webm"}]}

    async def generate_meeting_artifact(self, **kwargs: Any) -> dict[str, Any]:
        self.artifacts.append(kwargs)
        return {"status": "queued"}

    def project_url(self, project_id: str) -> str:
        return f"https://cw.test.invalid/projects/{project_id}"


class FakeStorage:
    """Stands in for the resumable-upload client, recording each block."""

    def __init__(self) -> None:
        self.blocks: list[tuple[int, bool]] = []
        self.data = bytearray()
        self.fail_next = 0

    async def upload_block(self, state: Any, data: bytes, *, is_final: bool, meeting_id: str = "") -> None:
        from app.core.exceptions import ChunkUploadError

        if self.fail_next > 0:
            self.fail_next -= 1
            raise ChunkUploadError("simulated storage failure")

        self.blocks.append((len(data), is_final))
        self.data.extend(data)
        state.uploaded_bytes += len(data)
        state.block_count += 1
        if is_final:
            state.completed = True


@pytest.fixture
def fake_platform() -> FakePlatform:
    return FakePlatform()


@pytest.fixture
def fake_audio_service() -> FakeAudioService:
    return FakeAudioService()


@pytest.fixture
def fake_cw_client() -> FakeCWClient:
    return FakeCWClient()


@pytest.fixture
def fake_storage() -> FakeStorage:
    return FakeStorage()


# --------------------------------------------------------------------------
# Builders
# --------------------------------------------------------------------------


def make_chunk(sequence: int, *, meeting_id: str = "meeting-1", size: int = 1024) -> AudioChunk:
    """An audio chunk with deterministic, distinguishable content."""
    return AudioChunk(
        meeting_id=meeting_id,
        chunk_id=f"{meeting_id}-{sequence}",
        data=bytes([sequence % 256]) * size,
        sequence=sequence,
        captured_at=datetime.now(timezone.utc),
        project_id="project-test",
    )


def caption(speaker: str, text: str) -> CaptionLine:
    return CaptionLine(speaker=speaker, text=text)


async def wait_for(condition, *, timeout: float = 2.0, interval: float = 0.01) -> bool:
    """Poll until ``condition()`` is true, or the timeout expires.

    Preferred over a fixed ``asyncio.sleep`` when waiting on a background loop:
    a sleep long enough to be reliable is also long enough to make the suite
    slow, and one short enough to be fast is flaky under load.
    """
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if condition():
            return True
        await asyncio.sleep(interval)
    return condition()
