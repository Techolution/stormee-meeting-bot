"""Transcription and chat endpoints."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.dependencies import ManagerDep
from app.schemas.transcription import (
    ChatMessageModel,
    ChatResponse,
    StartTranscriptionRequest,
    StopTranscriptionRequest,
    TranscriptResponse,
    TranscriptSegmentModel,
)

router = APIRouter(prefix="/transcription", tags=["Transcription"])


@router.post("/start", response_model=TranscriptResponse, summary="Start transcription")
async def start_transcription(
    payload: StartTranscriptionRequest,
    manager: ManagerDep,
) -> TranscriptResponse:
    """Begin producing a transcript using the configured provider."""
    await manager.start_transcription(payload.meeting_id)
    return TranscriptResponse(message="Transcription started", meeting_id=payload.meeting_id)


@router.post("/stop", response_model=TranscriptResponse, summary="Stop transcription")
async def stop_transcription(
    payload: StopTranscriptionRequest,
    manager: ManagerDep,
) -> TranscriptResponse:
    """Stop transcribing and return the full transcript."""
    segments = await manager.stop_transcription(payload.meeting_id)
    models = [TranscriptSegmentModel(**segment.as_dict()) for segment in segments]

    return TranscriptResponse(
        message="Transcription stopped",
        meeting_id=payload.meeting_id,
        segments=models,
        count=len(models),
    )


@router.get(
    "/{meeting_id}/transcript",
    response_model=TranscriptResponse,
    summary="Get the transcript so far",
)
async def get_transcript(meeting_id: str, manager: ManagerDep) -> TranscriptResponse:
    """Read the transcript without stopping transcription."""
    segments = manager.get_transcript(meeting_id)
    models = [TranscriptSegmentModel(**segment.as_dict()) for segment in segments]

    return TranscriptResponse(
        message="Transcript retrieved",
        meeting_id=meeting_id,
        segments=models,
        count=len(models),
    )


@router.get("/{meeting_id}/chat", response_model=ChatResponse, summary="Get chat messages")
async def get_chat(meeting_id: str, manager: ManagerDep) -> ChatResponse:
    """Read the in-meeting chat messages collected so far.

    Chat is monitored for the whole session, so this is available without
    starting anything.
    """
    messages = manager.get_chat_messages(meeting_id)
    models = [
        ChatMessageModel(
            sender=message.sender,
            text=message.text,
            timestamp=message.received_at.isoformat(),
            message_id=message.message_id,
        )
        for message in messages
    ]

    return ChatResponse(
        message="Chat messages retrieved",
        meeting_id=meeting_id,
        chat_segments=models,
        count=len(models),
    )
