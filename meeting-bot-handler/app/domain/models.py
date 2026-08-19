from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.domain.enums import BotStatus, MeetingStatus, RecordingStatus, TranscriptionStatus


@dataclass
class MeetingRecording:
    """Represents a single recording take associated with a meeting session."""
    recording_id: str
    session_id: str
    meeting_id: str

    status: RecordingStatus = RecordingStatus.NOT_STARTED

    # Upload and metric tracking from worker GET /recordings/{meetingId}/status
    chunks_captured: int = 0
    chunks_uploaded: int = 0
    chunks_pending: int = 0
    bytes_uploaded: int = 0

    storage_path: Optional[str] = None
    started_at: Optional[datetime] = None
    stopped_at: Optional[datetime] = None
    created_at: Optional[datetime] = None


@dataclass
class MeetingEvent:
    """Represents an audit/timeline event during a session."""
    event_id: str
    session_id: str
    event_type: str
    payload: dict
    created_at: Optional[datetime] = None


@dataclass
class BotSession:
    """Primary durable session entity (meeting_sessions table).

    ``session_id`` is the only identifier a client needs: the pod assignment
    below is internal routing state and is never returned in a public response.
    """
    session_id: str
    meeting_id: str
    meeting_url: str

    # User & Project Context
    user_name: Optional[str] = None
    user_email: Optional[str] = None
    project_id: Optional[str] = None
    project_name: Optional[str] = None
    meeting_title: Optional[str] = None

    # Overall State
    meeting_status: MeetingStatus = MeetingStatus.CREATED
    bot_status: BotStatus = BotStatus.PENDING
    transcription_status: TranscriptionStatus = TranscriptionStatus.NOT_STARTED
    active_recording_status: RecordingStatus = RecordingStatus.NOT_STARTED

    # Target Worker Mapping. Internal; resolved by the BotServiceResolver.
    service_url: Optional[str] = None
    worker_id: Optional[str] = None
    pod_name: Optional[str] = None
    pod_ip: Optional[str] = None
    k8s_job_name: Optional[str] = None

    # The bot's own id for this attendance, returned by POST /meetings/join.
    bot_session_id: Optional[str] = None
    last_error: Optional[str] = None

    # Timestamps
    scheduled_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    starting_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    leaving_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    failed_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    # One-to-Many Relationships
    recordings: List[MeetingRecording] = field(default_factory=list)
    events: List[MeetingEvent] = field(default_factory=list)

    @property
    def is_terminal(self) -> bool:
        return self.meeting_status in (
            MeetingStatus.COMPLETED,
            MeetingStatus.FAILED,
            MeetingStatus.CANCELLED,
        )

    @property
    def is_dispatched(self) -> bool:
        """True once a bot pod has been assigned to this session."""
        return bool(self.service_url)

    def timestamps(self) -> Dict[str, Any]:
        def iso(value: Optional[datetime]) -> Optional[str]:
            return value.isoformat() if value else None

        return {
            "created_at": iso(self.created_at),
            "scheduled_at": iso(self.scheduled_at),
            "starting_at": iso(self.starting_at),
            "started_at": iso(self.started_at),
            "leaving_at": iso(self.leaving_at),
            "completed_at": iso(self.completed_at),
            "failed_at": iso(self.failed_at),
            "updated_at": iso(self.updated_at),
        }
