"""HTTP models for transcription and chat endpoints."""

from __future__ import annotations

from pydantic import Field

from app.schemas.common import CamelCaseModel


class StartTranscriptionRequest(CamelCaseModel):
    meeting_id: str = Field(..., alias="meetingId", min_length=1)


class StopTranscriptionRequest(CamelCaseModel):
    meeting_id: str = Field(..., alias="meetingId", min_length=1)


class TranscriptSegmentModel(CamelCaseModel):
    """One attributed piece of transcript."""

    speaker: str
    text: str
    timestamp: str
    source: str = Field(default="caption", description="Where the segment came from.")


class TranscriptResponse(CamelCaseModel):
    """The transcript accumulated so far."""

    message: str
    meeting_id: str = Field(..., alias="meetingId")
    segments: list[TranscriptSegmentModel] = Field(default_factory=list)
    count: int = 0


class ChatMessageModel(CamelCaseModel):
    """One message from the in-meeting chat panel."""

    sender: str
    text: str
    timestamp: str
    message_id: str | None = Field(default=None, alias="messageId")


class ChatResponse(CamelCaseModel):
    message: str
    meeting_id: str = Field(..., alias="meetingId")
    chat_segments: list[ChatMessageModel] = Field(default_factory=list, alias="chatSegments")
    count: int = 0
