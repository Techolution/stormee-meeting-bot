"""Bot session lifecycle endpoints.

These endpoints allow clients to control the lifecycle of bot meetings:
- Start a bot session (join meeting)
- Start/stop recording
- Start/stop transcription
- Get session status
- Leave meeting
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status, Depends
from pydantic import BaseModel, Field

from app.bootstrap import create_bot_handler
from app.application.bot_handler import BotHandler


router = APIRouter(
    prefix="/bot-sessions",
    tags=["bot-sessions"],
)


# Request/Response Models
class SessionActionRequest(BaseModel):
    """Base request for session actions."""
    session_id: str = Field(..., min_length=1, description="The session/meeting ID")


class SessionActionResponse(BaseModel):
    """Base response for session actions."""
    message: str
    session_id: str


class SessionStatusResponse(BaseModel):
    """Response for session status."""
    session_id: str
    status: dict


# Create session request/response
class CreateSessionRequest(BaseModel):
    meeting_id: str = Field(..., min_length=1)
    meeting_url: str = Field(..., description="Google Meet URL")
    scheduled_at: str | None = None
    bot_service_url: str | None = Field(default=None, description="Target worker pod URL")
    
    # User and Project Context for Meeting Bot
    user_name: str | None = Field(default=None, description="Display name for the bot")
    user_email: str | None = Field(default=None, description="Recipient for ready notifications")
    project_id: str | None = Field(default=None, description="Determines where recording is filed")
    project_name: str | None = Field(default=None, description="Used in email notifications")
    meeting_title: str | None = Field(default=None, description="Display name for the artifact")


class CreateSessionResponse(BaseModel):
    session_id: str
    meeting_id: str
    status: str
    created_at: str | None = None


def get_bot_handler() -> BotHandler:
    """Dependency to get BotHandler instance."""
    return create_bot_handler()


@router.post(
    "/{session_id}/start",
    response_model=SessionActionResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Start a bot session",
)
async def start_session(
    session_id: str,
    handler: BotHandler = Depends(get_bot_handler),
) -> SessionActionResponse:
    """Start a bot session by joining a meeting.
    
    This endpoint initiates the bot joining the meeting specified by session_id.
    """
    try:
        await handler.start_bot(session_id)
        return SessionActionResponse(
            message="Session started successfully",
            session_id=session_id,
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to start session: {str(e)}",
        )


@router.post(
    "",
    response_model=CreateSessionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a bot session",
)
async def create_session(
    request: CreateSessionRequest,
    handler: BotHandler = Depends(get_bot_handler),
) -> CreateSessionResponse:
    """Create a durable bot session record.

    The created session will be used for all subsequent lifecycle operations
    addressed by `session_id`.
    """
    if handler._session_service is None:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Session service not configured")

    # Generate a simple session id. In production use a stronger id generator.
    import uuid

    session_id = uuid.uuid4().hex
    from app.domain.models import BotSession
    from app.domain.enums import BotSessionStatus

    session = BotSession(
        session_id=session_id,
        meeting_id=request.meeting_id,
        status=BotSessionStatus.PENDING,
    )

    created = await handler._session_service.create_session(session)

    return CreateSessionResponse(
        session_id=created.session_id,
        meeting_id=created.meeting_id,
        status=created.status.value,
        created_at=created.created_at.isoformat() if created.created_at else None,
    )


@router.post(
    "/{session_id}/recording/start",
    response_model=SessionActionResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Start recording for a session",
)
async def start_recording(
    session_id: str,
    handler: BotHandler = Depends(get_bot_handler),
) -> SessionActionResponse:
    """Start recording audio for a session.
    
    This endpoint begins capturing the meeting's audio for the specified session.
    """
    try:
        await handler.start_recording(session_id)
        return SessionActionResponse(
            message="Recording started successfully",
            session_id=session_id,
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to start recording: {str(e)}",
        )


@router.post(
    "/{session_id}/recording/stop",
    response_model=SessionActionResponse,
    status_code=status.HTTP_200_OK,
    summary="Stop recording for a session",
)
async def stop_recording(
    session_id: str,
    handler: BotHandler = Depends(get_bot_handler),
) -> SessionActionResponse:
    """Stop recording audio for a session.
    
    This endpoint stops capturing and finalizes the recording for the specified session.
    """
    try:
        await handler.stop_recording(session_id)
        return SessionActionResponse(
            message="Recording stopped successfully",
            session_id=session_id,
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to stop recording: {str(e)}",
        )


@router.post(
    "/{session_id}/transcription/start",
    response_model=SessionActionResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Start transcription for a session",
)
async def start_transcription(
    session_id: str,
    handler: BotHandler = Depends(get_bot_handler),
) -> SessionActionResponse:
    """Start transcription for a session.
    
    This endpoint begins producing a transcript for the specified session.
    """
    try:
        await handler.start_transcription(session_id)
        return SessionActionResponse(
            message="Transcription started successfully",
            session_id=session_id,
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to start transcription: {str(e)}",
        )


@router.post(
    "/{session_id}/transcription/stop",
    response_model=SessionActionResponse,
    status_code=status.HTTP_200_OK,
    summary="Stop transcription for a session",
)
async def stop_transcription(
    session_id: str,
    handler: BotHandler = Depends(get_bot_handler),
) -> SessionActionResponse:
    """Stop transcription for a session.
    
    This endpoint stops transcribing for the specified session.
    """
    try:
        await handler.stop_transcription(session_id)
        return SessionActionResponse(
            message="Transcription stopped successfully",
            session_id=session_id,
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to stop transcription: {str(e)}",
        )


@router.post(
    "/{session_id}/leave",
    response_model=SessionActionResponse,
    status_code=status.HTTP_200_OK,
    summary="Leave a session",
)
async def leave_session(
    session_id: str,
    handler: BotHandler = Depends(get_bot_handler),
) -> SessionActionResponse:
    """Leave a session/meeting.
    
    This endpoint causes the bot to leave the meeting for the specified session.
    """
    try:
        await handler.leave(session_id)
        return SessionActionResponse(
            message="Session left successfully",
            session_id=session_id,
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to leave session: {str(e)}",
        )


@router.post(
    "/{session_id}/stop",
    response_model=SessionActionResponse,
    status_code=status.HTTP_200_OK,
    summary="Stop a session",
)
async def stop_session(
    session_id: str,
    handler: BotHandler = Depends(get_bot_handler),
) -> SessionActionResponse:
    """Stop a session.
    
    This endpoint stops the session (equivalent to leaving the meeting).
    """
    try:
        await handler.stop(session_id)
        return SessionActionResponse(
            message="Session stopped successfully",
            session_id=session_id,
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to stop session: {str(e)}",
        )


@router.get(
    "/{session_id}/status",
    response_model=SessionStatusResponse,
    summary="Get session status",
)
async def get_session_status(
    session_id: str,
    handler: BotHandler = Depends(get_bot_handler),
) -> SessionStatusResponse:
    """Get the status of a session.
    
    This endpoint retrieves the current status of the specified session from the bot service.
    """
    try:
        status_data = await handler.get_status(session_id)
        return SessionStatusResponse(
            session_id=session_id,
            status=status_data,
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get session status: {str(e)}",
        )


@router.get(
    "/{session_id}",
    response_model=CreateSessionResponse,
    summary="Get session record",
)
async def get_session(
    session_id: str,
    handler: BotHandler = Depends(get_bot_handler),
) -> CreateSessionResponse:
    """Return the persisted session record (durable state)."""
    if handler._session_service is None:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Session service not configured")

    session = await handler._session_service.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="session not found")

    return CreateSessionResponse(
        session_id=session.session_id,
        meeting_id=session.meeting_id,
        status=session.status.value,
        created_at=session.created_at.isoformat() if session.created_at else None,
    )
