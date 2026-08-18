from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional

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
    """Primary durable session entity (meeting_sessions table)."""
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

    # Target Worker Mapping
    service_url: Optional[str] = None
    worker_id: Optional[str] = None
    k8s_job_name: Optional[str] = None

    # Timestamps
    scheduled_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    failed_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    # One-to-Many Relationships
    recordings: List[MeetingRecording] = field(default_factory=list)
    events: List[MeetingEvent] = field(default_factory=list)