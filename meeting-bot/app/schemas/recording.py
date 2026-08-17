"""HTTP models for recording endpoints."""

from __future__ import annotations

from pydantic import Field

from app.schemas.common import CamelCaseModel


class StartRecordingRequest(CamelCaseModel):
    """Begin capturing meeting audio."""

    meeting_id: str = Field(..., alias="meetingId", min_length=1)


class StopRecordingRequest(CamelCaseModel):
    """Stop capturing and finalize the upload."""

    meeting_id: str = Field(..., alias="meetingId", min_length=1)


class RecordingActionResponse(CamelCaseModel):
    message: str
    meeting_id: str = Field(..., alias="meetingId")


class RecordingStatusResponse(CamelCaseModel):
    """What the recorder is doing right now."""

    meeting_id: str = Field(..., alias="meetingId")
    status: str = Field(..., description="idle | recording | stopping | stopped | failed")
    chunks_captured: int = Field(default=0, alias="chunksCaptured")
    chunks_uploaded: int = Field(default=0, alias="chunksUploaded")
    chunks_pending: int = Field(default=0, alias="chunksPending")
    bytes_uploaded: int = Field(default=0, alias="bytesUploaded")
    started_at: str | None = Field(default=None, alias="startedAt")
    stopped_at: str | None = Field(default=None, alias="stoppedAt")
    transport: str | None = Field(
        default=None,
        description="Where chunks are sent: 'websocket' (audio service) or 'direct' (object storage).",
    )
