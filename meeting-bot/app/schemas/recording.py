"""HTTP models for recording endpoints."""

from __future__ import annotations

from pydantic import ConfigDict, Field

from app.schemas.common import CamelCaseModel


class StartRecordingRequest(CamelCaseModel):
    """Begin capturing meeting audio.

    Supports incremental segment recording with automatic upload and highlights
    generation at specified duration intervals. Allows custom highlight model
    configuration via highlight model types and categorization mode settings.
    """

    # sessionId selects an existing attendance; meetingId is optional because
    # the worker can mint the recording identity at this boundary.
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "sessionId": "abc-defg-hij_6e16ac69fc014df2a7711d071a32fe09",
                    "meetingId": "abc-defg-hij_20260917T143045IST",
                    "maxDurationSeconds": 300,
                    "generateIncrementalHighlights": True,
                    "modeIds": [],
                }
            ]
        }
    )

    session_id: str = Field(
        ...,
        alias="sessionId",
        min_length=1,
        examples=["abc-defg-hij_6e16ac69fc014df2a7711d071a32fe09"],
    )
    meeting_id: str | None = Field(
        default=None,
        alias="meetingId",
        min_length=1,
        examples=["abc-defg-hij_20260917T143045IST"],
    )
    max_duration_seconds: int | None = Field(
        default=None,
        alias="maxDurationSeconds",
        gt=0,
        description="Optional: Automatically stop recording and upload this segment after this duration. The remaining audio after all segments is uploaded at meeting end.",
    )
    generate_incremental_highlights: bool = Field(
        default=False,
        alias="generateIncrementalHighlights",
        description="If true, request highlights for each segment when max_duration_seconds is set.",
    )
    mode_ids: list[str] = Field(
        default_factory=list,
        alias="modeIds",
        description="Optional: List of highlight categorization mode identifiers for custom highlight generation configuration.",
    )


class StopRecordingRequest(CamelCaseModel):
    """Stop capturing and finalize the upload."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {"meetingId": "abc-defg-hij_20260917T143045IST"}
            ]
        }
    )

    meeting_id: str = Field(
        ...,
        alias="meetingId",
        min_length=1,
        examples=["abc-defg-hij_20260917T143045IST"],
    )


class RecordingActionResponse(CamelCaseModel):
    message: str
    meeting_id: str = Field(..., alias="meetingId")


class StartRecordingResponse(RecordingActionResponse):
    """Identity and display metadata for a newly started recording take."""

    session_id: str = Field(..., alias="sessionId")
    recording_count: int = Field(
        ...,
        alias="recordingCount",
        ge=1,
        description="Visual count of recordings started under this session; it has no lifecycle effect.",
    )


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
