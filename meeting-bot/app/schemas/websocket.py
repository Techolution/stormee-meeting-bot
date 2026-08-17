"""Wire contract with the audio service.

The audio service speaks Socket.IO with camelCase payloads. Rather than let
that convention leak into the domain, the translation happens here: event
names are constants, and each payload has an explicit ``as_wire_payload`` or
``from_wire``. When the audio service changes its contract, this file changes
and nothing else does.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# --------------------------------------------------------------------------
# Event names
# --------------------------------------------------------------------------

#: Bot -> service. One recorded audio chunk.
EVENT_AUDIO_CHUNK = "audioChunk"

#: Bot -> service. Recording finished; flush and confirm. Expects an acknowledgement.
EVENT_RECORDING_ENDED = "recordingEnded"

#: Bot -> service. One transcript segment as it is produced.
EVENT_TRANSCRIPT_SEGMENT = "transcriptSegment"

#: Service -> bot. Play this audio into the meeting's virtual microphone.
EVENT_PLAY_AUDIO = "playAudio"

#: Service -> bot. Leave the meeting.
EVENT_LEAVE_MEETING = "leaveMeeting"

#: Service -> bot. Out-of-band error report.
EVENT_ERROR = "error"


@dataclass(frozen=True, slots=True)
class RecordingEndedEvent:
    """Sent when a recording stops, so the service can finalize its upload."""

    meeting_id: str
    project_id: str | None
    queued_chunks: int
    total_chunks: int
    user_name: str = ""
    user_email: str = ""
    status: str = "stopped"

    def as_wire_payload(self) -> dict[str, Any]:
        return {
            "meetingId": self.meeting_id,
            "projectId": self.project_id,
            "eventType": EVENT_RECORDING_ENDED,
            "status": self.status,
            "queuedChunks": self.queued_chunks,
            "totalChunks": self.total_chunks,
            "artifactUserName": self.user_name,
            "artifactUserEmail": self.user_email,
        }


@dataclass(frozen=True, slots=True)
class RecordingEndedAck:
    """The audio service's answer to :class:`RecordingEndedEvent`."""

    status: str
    meeting_id: str = ""
    uploaded_chunks: int = 0
    uploaded_bytes: int = 0
    buffered_chunks: int = 0
    reason: str = ""

    @property
    def is_complete(self) -> bool:
        """True when the service reported everything persisted with nothing left over."""
        return self.status == "ok" and self.buffered_chunks == 0

    @classmethod
    def from_wire(cls, payload: Any) -> RecordingEndedAck:
        """Parse an acknowledgement defensively.

        The service may answer with anything — including ``None`` on timeout —
        so an unparseable response becomes an ``unknown`` status rather than an
        exception during shutdown.
        """
        if not isinstance(payload, dict):
            return cls(status="unknown", reason=f"unexpected ack type: {type(payload).__name__}")

        return cls(
            status=str(payload.get("status", "unknown")),
            meeting_id=str(payload.get("meetingId", "")),
            uploaded_chunks=_as_int(payload.get("uploaded_chunks")),
            uploaded_bytes=_as_int(payload.get("uploaded_bytes")),
            buffered_chunks=_as_int(payload.get("buffered_chunks")),
            reason=str(payload.get("reason", "")),
        )


@dataclass(frozen=True, slots=True)
class PlayAudioCommand:
    """Service -> bot request to play audio into the meeting."""

    meeting_id: str
    audio_url: str
    volume: float = 0.7

    @classmethod
    def from_wire(cls, payload: Any) -> PlayAudioCommand | None:
        """Parse an inbound command, returning ``None`` when it is unusable."""
        if not isinstance(payload, dict):
            return None
        audio_url = payload.get("audioUrl") or payload.get("audio_url")
        meeting_id = payload.get("meetingId") or payload.get("meeting_id")
        if not audio_url or not meeting_id:
            return None

        try:
            volume = float(payload.get("volume", 0.7))
        except (TypeError, ValueError):
            volume = 0.7

        return cls(
            meeting_id=str(meeting_id),
            audio_url=str(audio_url),
            volume=min(max(volume, 0.0), 1.0),
        )


def _as_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
