"""Shared fixtures.

The fakes here are the practical payoff of the interfaces in ``app``: a meeting
session can be exercised with no browser, no socket and no network, because
every collaborator it reaches is an abstraction with a test double.
"""

from __future__ import annotations

import asyncio
import struct
from datetime import datetime, timezone
from typing import Any

import pytest
from pydantic_settings import BaseSettings

import app.core.config as config_module
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


@pytest.fixture(autouse=True)
def _ignore_dotenv(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stop every settings model from reading the developer's ``.env``.

    ``Settings(_env_file=None)`` only disables the file for the *root* model;
    each nested group is built by its own ``default_factory`` and reads the file
    again. Pydantic copies the shared ``SettingsConfigDict`` into each class at
    definition time, so the key has to be cleared on every model rather than on
    the constant they were built from.

    Autouse because a single test constructing a settings object without this is
    enough to make the suite's result depend on local configuration — which is
    how a green CI run and a red local run come to disagree.
    """
    for name in dir(config_module):
        candidate = getattr(config_module, name)
        if (
            isinstance(candidate, type)
            and issubclass(candidate, BaseSettings)
            and candidate is not BaseSettings
        ):
            monkeypatch.setitem(candidate.model_config, "env_file", None)


@pytest.fixture
def settings(monkeypatch: pytest.MonkeyPatch) -> Settings:
    """Settings built from a known environment, isolated from the developer's own.

    Two separate sources have to be shut out, and missing either makes the suite
    depend on the machine it runs on:

    * **Exported variables** — cleared below.
    * **The ``.env`` file** — disabled by the autouse fixture. Clearing the
      environment does not stop pydantic reading the file, and every nested
      settings group reads it independently of the root object.
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


class FakeMailClient:
    """Stands in for :class:`~app.clients.mail.MailClient`."""

    def __init__(self, *, enabled: bool = True) -> None:
        self.enabled = enabled
        self.sent: list[dict[str, Any]] = []

    async def send_meeting_file_uploaded(self, **kwargs: Any) -> None:
        self.sent.append(kwargs)


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


# --------------------------------------------------------------------------
# WebM builders
# --------------------------------------------------------------------------
#
# The recording pipeline re-frames a live WebM stream, so testing it needs
# bytes shaped like the ones Chrome's MediaRecorder actually produces: a
# ``Segment`` and ``Cluster``s written with unknown sizes, and audio carried in
# ``SimpleBlock``s whose timestamps are offsets from their cluster.
#
# ``read_webm`` is the inverse, and doubles as a validity check: a segment that
# does not parse raises here rather than failing an assertion further down.

_UNKNOWN_SIZE = b"\x01\xff\xff\xff\xff\xff\xff\xff"
_CLUSTER_ID = b"\x1f\x43\xb6\x75"
_TIMECODE_ID = b"\xe7"
_SIMPLE_BLOCK_ID = b"\xa3"


def _ebml_size(size: int) -> bytes:
    for length in range(1, 9):
        if size < (1 << (7 * length)) - 1:
            return (size | (1 << (7 * length))).to_bytes(length, "big")
    raise ValueError(f"size {size} does not fit an EBML vint")


def _ebml_element(element_id: bytes, payload: bytes) -> bytes:
    return element_id + _ebml_size(len(payload)) + payload


def webm_init_bytes() -> bytes:
    """The initialisation data every playable WebM file has to start with."""
    return (
        _ebml_element(b"\x1a\x45\xdf\xa3", b"\x42\x86\x81\x01")  # EBML header
        + b"\x18\x53\x80\x67"  # Segment, left open the way a live writer does
        + _UNKNOWN_SIZE
        + _ebml_element(b"\x15\x49\xa9\x66", b"\x2a\xd7\xb1\x83\x0f\x42\x40")  # Info
        + _ebml_element(b"\x16\x54\xae\x6b", b"\xae\x83\xd7\x81\x01")  # Tracks
    )


def make_webm_stream(
    clusters: list[tuple[int, list[int]]],
    *,
    known_cluster_sizes: bool = False,
) -> bytes:
    """Build a live WebM stream.

    Args:
        clusters: One ``(cluster_timecode, [block_timestamp, ...])`` pair per
            cluster, all in absolute milliseconds. Every block gets a payload
            derived from its timestamp, so a test can tell which blocks came
            out the other end.
        known_cluster_sizes: Write clusters with a declared length instead of
            the unknown size Chrome uses. Both are legal and the parser has to
            handle each.
    """
    stream = bytearray(webm_init_bytes())
    for timecode, timestamps in clusters:
        body = bytearray(_ebml_element(_TIMECODE_ID, _unsigned(timecode)))
        for timestamp in timestamps:
            offset = timestamp - timecode
            payload = b"\x81" + struct.pack(">h", offset) + b"\x80" + _block_payload(timestamp)
            body.extend(_ebml_element(_SIMPLE_BLOCK_ID, payload))
        if known_cluster_sizes:
            stream.extend(_CLUSTER_ID + _ebml_size(len(body)) + body)
        else:
            stream.extend(_CLUSTER_ID + _UNKNOWN_SIZE + body)
    return bytes(stream)


def read_webm(data: bytes) -> tuple[bytes, list[tuple[int, bytes]]]:
    """Split a WebM file into its init bytes and its audio blocks.

    Returns:
        ``(init_bytes, [(absolute_timestamp, payload), ...])``.

    Raises:
        ValueError: If the bytes are not a well-formed WebM file. Segments are
            supposed to be playable on their own, so failing to parse one is a
            test failure worth reporting as an error rather than a mismatch.
    """
    position, limit = 0, len(data)
    init_end = None
    timecode = 0
    blocks: list[tuple[int, bytes]] = []

    while position < limit:
        element_id, size, header = _read_header(data, position)
        payload_start = position + header

        if element_id == 0x18538067:  # Segment: descend rather than skip
            position = payload_start
            continue
        if element_id == 0x1F43B675:  # Cluster
            if init_end is None:
                init_end = position
            position = payload_start
            continue
        if size is None:
            raise ValueError(f"unknown size on element {element_id:#x} at {position}")
        if element_id == 0xE7:
            timecode = int.from_bytes(data[payload_start : payload_start + size], "big")
        elif element_id == 0xA3:
            offset = struct.unpack_from(">h", data, payload_start + 1)[0]
            blocks.append((timecode + offset, data[payload_start + 4 : payload_start + size]))
        position = payload_start + size

    if init_end is None:
        raise ValueError("file contains no cluster, so it carries no audio")
    return data[:init_end], blocks


def _block_payload(timestamp: int) -> bytes:
    return b"audio-" + timestamp.to_bytes(4, "big")


def _unsigned(value: int) -> bytes:
    return value.to_bytes(max((value.bit_length() + 7) // 8, 1), "big")


def _read_header(data: bytes, position: int) -> tuple[int, int | None, int]:
    id_length = _vint_length(data[position])
    element_id = int.from_bytes(data[position : position + id_length], "big")
    size_start = position + id_length
    size_length = _vint_length(data[size_start])
    raw = int.from_bytes(data[size_start : size_start + size_length], "big")
    value = raw & ((1 << (7 * size_length)) - 1)
    unknown = value == (1 << (7 * size_length)) - 1
    return element_id, (None if unknown else value), id_length + size_length


def _vint_length(first_byte: int) -> int:
    for length in range(1, 9):
        if first_byte & (0x80 >> (length - 1)):
            return length
    raise ValueError(f"invalid variable-size integer prefix {first_byte:#x}")
