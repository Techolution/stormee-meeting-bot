"""Request and response models for the bot-session API.

The handler's own API is snake_case — it is an internal control plane, and its
callers are services, not the bot. The camelCase translation happens one layer
down, at the bot boundary.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field, field_validator


class CreateSessionRequest(BaseModel):
    """Register a meeting. No pod is claimed until the session is started."""

    meeting_id: str = Field(..., min_length=1, description="Caller-assigned meeting identifier")
    meeting_url: str = Field(..., description="Absolute meeting URL")
    scheduled_at: Optional[datetime] = None

    # Pins the session to a specific bot pod, bypassing discovery. For local
    # development and for re-attaching to a known pod.
    bot_service_url: Optional[str] = Field(default=None, description="Explicit bot pod URL")

    user_name: Optional[str] = Field(default=None, description="Display name for the bot")
    user_email: Optional[str] = Field(default=None, description="Recipient of the ready notification")
    project_id: Optional[str] = Field(default=None, description="Determines where the recording is filed")
    project_name: Optional[str] = Field(default=None, description="Used in mail")
    meeting_title: Optional[str] = Field(default=None, description="Display name for the artifact")

    # Start the bot immediately instead of waiting for an explicit /start.
    auto_start: bool = False

    @field_validator("meeting_url")
    @classmethod
    def _absolute_url(cls, value: str) -> str:
        candidate = value.strip()
        if not candidate.startswith(("http://", "https://")):
            raise ValueError("meeting_url must be an absolute http(s) URL")
        return candidate


class SessionResponse(BaseModel):
    """The durable session record. Pod assignment is deliberately not exposed."""

    session_id: str
    meeting_id: str
    meeting_url: str
    meeting_status: str
    bot_status: str
    recording_status: str
    transcription_status: str
    last_error: Optional[str] = None
    created_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class SessionActionResponse(BaseModel):
    """Acknowledgement of a lifecycle command."""

    message: str
    session_id: str
    meeting_status: Optional[str] = None
    bot_status: Optional[str] = None
    recording_status: Optional[str] = None
    transcription_status: Optional[str] = None
    recording_id: Optional[str] = None
    detail: Optional[Dict[str, Any]] = None


class PlayAudioRequest(BaseModel):
    audio_url: str = Field(..., description="URL reachable from inside the bot's browser")
    volume: float = Field(default=0.7, ge=0.0, le=1.0)
