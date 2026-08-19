"""Response models for command-style endpoints."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class CommandResponse(BaseModel):
    session_id: str
    command: str
    status: str


class TranscriptResponse(BaseModel):
    session_id: str
    meeting_id: str
    count: int
    segments: List[Dict[str, Any]]


class ChatResponse(BaseModel):
    session_id: str
    meeting_id: str
    count: int
    chat_segments: List[Dict[str, Any]]


class RecordingStatusResponse(BaseModel):
    session_id: str
    meeting_id: str
    recording_status: str
    runtime: Optional[Dict[str, Any]] = None
