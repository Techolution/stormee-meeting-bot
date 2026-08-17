"""Transcription value objects."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from app.context.models import ContextItem


class TranscriptionStatus(str, Enum):
    """Lifecycle of a transcription provider."""

    IDLE = "idle"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"
    FAILED = "failed"

    @property
    def is_active(self) -> bool:
        return self in (TranscriptionStatus.STARTING, TranscriptionStatus.RUNNING)


class TranscriptSource(str, Enum):
    """Where a segment came from.

    Recorded on every segment so a transcript assembled from more than one
    source stays attributable — which matters as soon as speech-to-text is
    added alongside captions.
    """

    CAPTION = "caption"
    SPEECH_TO_TEXT = "speech_to_text"


@dataclass(frozen=True, slots=True)
class TranscriptSegment:
    """One attributed utterance."""

    speaker: str
    text: str
    source: TranscriptSource = TranscriptSource.CAPTION
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "speaker": self.speaker,
            "text": self.text,
            "source": self.source.value,
            "timestamp": self.created_at.isoformat(),
        }

    def as_context_item(self) -> ContextItem:
        return ContextItem(
            kind="transcript",
            content=self.text,
            speaker=self.speaker,
            created_at=self.created_at,
            metadata={"source": self.source.value, **self.metadata},
        )

    def as_wire_payload(self, meeting_id: str) -> dict[str, Any]:
        """Serialise for the audio service."""
        return {
            "meetingId": meeting_id,
            "speaker": self.speaker,
            "text": self.text,
            "source": self.source.value,
            "timestamp": self.created_at.isoformat(),
        }


@dataclass(slots=True)
class TranscriptionStats:
    """Counters for one transcription run."""

    segments_emitted: int = 0
    duplicates_suppressed: int = 0
    poll_errors: int = 0
    started_at: datetime | None = None
    stopped_at: datetime | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "segments_emitted": self.segments_emitted,
            "duplicates_suppressed": self.duplicates_suppressed,
            "poll_errors": self.poll_errors,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "stopped_at": self.stopped_at.isoformat() if self.stopped_at else None,
        }
