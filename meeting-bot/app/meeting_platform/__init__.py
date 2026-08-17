"""Meeting platform abstraction.

The rest of the application programs against :class:`MeetingPlatform` and the
value objects in :mod:`app.meeting_platform.models`. No caller knows which
product is on the other side, which is what allows a second platform to be
added without touching meeting, recording or transcription logic.
"""

from app.meeting_platform.base import ChunkSink, MeetingPlatform
from app.meeting_platform.models import (
    AudioPlaybackRequest,
    CaptionLine,
    ChatMessage,
    DeviceState,
    JoinRequest,
    JoinResult,
    MeetingRoomState,
    Participant,
    PlatformCapabilities,
    PlatformName,
    RecordingHandle,
)
from app.meeting_platform.registry import (
    create_platform,
    detect_platform,
    register_platform,
    supported_platforms,
)

__all__ = [
    "AudioPlaybackRequest",
    "CaptionLine",
    "ChatMessage",
    "ChunkSink",
    "DeviceState",
    "JoinRequest",
    "JoinResult",
    "MeetingPlatform",
    "MeetingRoomState",
    "Participant",
    "PlatformCapabilities",
    "PlatformName",
    "RecordingHandle",
    "create_platform",
    "detect_platform",
    "register_platform",
    "supported_platforms",
]
