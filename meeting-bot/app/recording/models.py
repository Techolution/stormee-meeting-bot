"""Recording value objects."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class RecordingStatus(str, Enum):
    """Lifecycle of one recording."""

    IDLE = "idle"
    STARTING = "starting"
    RECORDING = "recording"
    STOPPING = "stopping"
    STOPPED = "stopped"
    FAILED = "failed"

    @property
    def is_active(self) -> bool:
        return self in (RecordingStatus.STARTING, RecordingStatus.RECORDING)


@dataclass(frozen=True, slots=True)
class AudioChunk:
    """One slice of recorded audio.

    The page emits a chunk per ``MediaRecorder`` timeslice. Chunk ids are
    ``"<meeting_id>-<n>"`` with ``n`` counting from zero, and the numeric part
    is what orders the stream: chunks may arrive out of order across a
    reconnect, and concatenating them wrongly corrupts the container.
    """

    meeting_id: str
    chunk_id: str
    data: bytes
    sequence: int
    captured_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    project_id: str | None = None

    @property
    def size_bytes(self) -> int:
        return len(self.data)

    @classmethod
    def from_page_payload(
        cls,
        payload: dict[str, Any],
        *,
        project_id: str | None = None,
    ) -> AudioChunk:
        """Build a chunk from the raw page callback payload.

        The browser sends ``audioBlob`` as a JSON array of byte values, since
        Socket.IO's transport cannot carry a ``Blob`` directly.

        Raises:
            ValueError: If required fields are missing or the id is unparseable.
                A malformed chunk cannot be sequenced, and silently dropping it
                would corrupt the recording.
        """
        meeting_id = payload.get("meetingId")
        chunk_id = payload.get("chunkId")
        if not meeting_id or not chunk_id:
            raise ValueError("chunk payload is missing meetingId or chunkId")

        raw = payload.get("audioBlob") or []
        try:
            data = bytes(raw)
        except (TypeError, ValueError) as error:
            raise ValueError(f"chunk audioBlob is not byte data: {type(raw).__name__}") from error

        return cls(
            meeting_id=str(meeting_id),
            chunk_id=str(chunk_id),
            data=data,
            sequence=parse_sequence(str(chunk_id)),
            project_id=payload.get("projectId") or project_id,
        )

    def as_wire_payload(self) -> dict[str, Any]:
        """Serialise for the audio service, which expects the page's own shape."""
        return {
            "meetingId": self.meeting_id,
            "chunkId": self.chunk_id,
            "timestamp": self.captured_at.isoformat(),
            "audioBlob": list(self.data),
            "projectId": self.project_id,
        }


def parse_sequence(chunk_id: str) -> int:
    """Extract the ordinal from a ``"<meeting_id>-<n>"`` chunk id.

    Raises:
        ValueError: If the trailing segment is not an integer.
    """
    tail = chunk_id.rsplit("-", 1)[-1]
    try:
        return int(tail)
    except ValueError as error:
        raise ValueError(f"cannot derive sequence from chunk id {chunk_id!r}") from error


@dataclass(slots=True)
class RecordingStats:
    """Counters for one recording, surfaced on the status endpoint."""

    chunks_captured: int = 0
    chunks_uploaded: int = 0
    chunks_dropped: int = 0
    bytes_captured: int = 0
    bytes_uploaded: int = 0
    started_at: datetime | None = None
    stopped_at: datetime | None = None

    @property
    def duration_seconds(self) -> float:
        if self.started_at is None:
            return 0.0
        end = self.stopped_at or datetime.now(timezone.utc)
        return (end - self.started_at).total_seconds()

    def as_dict(self) -> dict[str, Any]:
        return {
            "chunks_captured": self.chunks_captured,
            "chunks_uploaded": self.chunks_uploaded,
            "chunks_dropped": self.chunks_dropped,
            "bytes_captured": self.bytes_captured,
            "bytes_uploaded": self.bytes_uploaded,
            "duration_seconds": round(self.duration_seconds, 1),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "stopped_at": self.stopped_at.isoformat() if self.stopped_at else None,
        }


@dataclass(frozen=True, slots=True)
class RecordingContext:
    """Attribution carried with a recording, used when registering the upload."""

    meeting_id: str
    project_id: str | None = None
    project_name: str | None = None
    meeting_title: str | None = None
    user_name: str = ""
    user_email: str = ""
