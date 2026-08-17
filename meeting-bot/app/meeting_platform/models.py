"""Platform-neutral meeting vocabulary.

These types are what a meeting platform returns and what the rest of the
application consumes. Nothing here mentions Google Meet, a DOM node, or a
Playwright locator — that is the point. Adding Teams or Zoom means writing a
new implementation that produces these same types.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class PlatformName(str, Enum):
    """Meeting platforms this bot can drive."""

    GOOGLE_MEET = "google_meet"


class MeetingRoomState(str, Enum):
    """Where the bot stands relative to the meeting room."""

    UNKNOWN = "unknown"
    LOBBY = "lobby"
    IN_MEETING = "in_meeting"
    ENDED = "ended"


class DeviceState(str, Enum):
    """Microphone or camera state as the platform reports it."""

    ON = "on"
    OFF = "off"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class JoinRequest:
    """Everything a platform needs to get into a meeting."""

    meeting_url: str
    display_name: str
    meeting_id: str = ""


@dataclass(frozen=True, slots=True)
class JoinResult:
    """Outcome of a join attempt."""

    admitted: bool
    state: MeetingRoomState
    waited_seconds: float = 0.0
    detail: str = ""


@dataclass(frozen=True, slots=True)
class Participant:
    """One person visible in the meeting."""

    identifier: str
    name: str = ""


@dataclass(frozen=True, slots=True)
class CaptionLine:
    """One caption block as currently rendered by the platform.

    Captions are *live* and mutate in place: the platform rewrites the same
    block as a speaker continues talking. A ``CaptionLine`` is therefore a
    snapshot, not an append-only record — deduplication is the transcription
    provider's job, not the platform's.
    """

    speaker: str
    text: str
    captured_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def is_empty(self) -> bool:
        return not self.text.strip()


@dataclass(frozen=True, slots=True)
class ChatMessage:
    """One message from the in-meeting chat panel."""

    message_id: str
    sender: str
    text: str
    received_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(frozen=True, slots=True)
class AudioPlaybackRequest:
    """Audio the bot should play into the meeting through its virtual microphone."""

    audio_url: str
    volume: float = 0.7

    def __post_init__(self) -> None:
        if not 0.0 <= self.volume <= 1.0:
            raise ValueError(f"volume must be between 0.0 and 1.0, got {self.volume}")


@dataclass(frozen=True, slots=True)
class RecordingHandle:
    """Identifies an in-page recording session started by the platform."""

    meeting_id: str
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    chunk_duration_ms: int = 5_000


@dataclass(frozen=True, slots=True)
class PlatformCapabilities:
    """What a given platform implementation actually supports.

    Callers check these rather than assuming; a platform that cannot produce
    captions should degrade the feature, not crash the meeting.
    """

    supports_captions: bool = True
    supports_chat: bool = True
    supports_participant_list: bool = True
    supports_audio_playback: bool = True
    supports_recording: bool = True


