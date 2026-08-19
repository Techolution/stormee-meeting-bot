"""Bot session lifecycle endpoints.

Routes are thin: validate, delegate, shape the response. Failures propagate as
domain exceptions and are turned into the error envelope by the handlers
registered in ``app.api.errors`` — a route that swallowed them into a 500 would
throw away the distinction between "no such session", "pod busy" and "cluster
down", which is the only thing a caller can act on.

Status codes follow what actually happened. 202 where the bot has merely
accepted a command and the work continues asynchronously; 200 where the
operation is complete when the response is written.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Query, status

from app.api.dependencies import BotHandlerDep, SessionServiceDep
from app.domain.models import BotSession
from app.schemas.bot import (
    CreateSessionRequest,
    PlayAudioRequest,
    SessionActionResponse,
    SessionResponse,
)
from app.schemas.commands import ChatResponse, TranscriptResponse
from app.schemas.status import SessionStatusResponse

router = APIRouter(prefix="/bot-sessions", tags=["bot-sessions"])


def _to_response(session: BotSession) -> SessionResponse:
    return SessionResponse(
        session_id=session.session_id,
        meeting_id=session.meeting_id,
        meeting_url=session.meeting_url,
        meeting_status=session.meeting_status.value,
        bot_status=session.bot_status.value,
        recording_status=session.active_recording_status.value,
        transcription_status=session.transcription_status.value,
        last_error=session.last_error,
        created_at=session.created_at,
        started_at=session.started_at,
        updated_at=session.updated_at,
    )


@router.post(
    "",
    response_model=SessionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a bot session",
)
async def create_session(
    request: CreateSessionRequest,
    handler: BotHandlerDep,
    sessions: SessionServiceDep,
) -> SessionResponse:
    """Register a meeting and return the session id every later call uses.

    No pod is claimed here. Set ``auto_start`` to dispatch immediately.
    """
    session = BotSession(
        session_id=uuid.uuid4().hex,
        meeting_id=request.meeting_id,
        meeting_url=request.meeting_url,
        scheduled_at=request.scheduled_at,
        service_url=request.bot_service_url,
        user_name=request.user_name,
        user_email=request.user_email,
        project_id=request.project_id,
        project_name=request.project_name,
        meeting_title=request.meeting_title,
    )
    created = await sessions.create_session(session)

    if request.auto_start:
        await handler.start_bot(created.session_id)
        created = await sessions.require_session(created.session_id)

    return _to_response(created)


@router.get("", response_model=list[SessionResponse], summary="List sessions")
async def list_sessions(
    sessions: SessionServiceDep,
    active_only: bool = Query(default=False, description="Exclude finished sessions"),
) -> list[SessionResponse]:
    records = await sessions.list_sessions(active_only=active_only)
    return [_to_response(record) for record in records]


@router.get("/{session_id}", response_model=SessionResponse, summary="Get session record")
async def get_session(session_id: str, sessions: SessionServiceDep) -> SessionResponse:
    """The durable record, read from storage without touching the pod."""
    return _to_response(await sessions.require_session(session_id))


@router.post(
    "/{session_id}/start",
    response_model=SessionActionResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Start a bot session",
)
async def start_session(session_id: str, handler: BotHandlerDep) -> SessionActionResponse:
    """Claim a bot pod and send it into the meeting.

    Returns once a pod has accepted the join. Admission by the meeting host can
    take minutes, so poll the session's status for the outcome.
    """
    result = await handler.start_bot(session_id)
    return SessionActionResponse(
        message="Bot dispatch accepted",
        session_id=session_id,
        meeting_status=result["meeting_status"],
        bot_status=result["bot_status"],
        detail=result.get("detail"),
    )


@router.post(
    "/{session_id}/recording/start",
    response_model=SessionActionResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Start recording",
)
async def start_recording(session_id: str, handler: BotHandlerDep) -> SessionActionResponse:
    result = await handler.start_recording(session_id)
    return SessionActionResponse(
        message="Recording start accepted",
        session_id=session_id,
        recording_status=result["recording_status"],
        recording_id=result.get("recording_id"),
        detail=result.get("detail"),
    )


@router.post(
    "/{session_id}/recording/stop",
    response_model=SessionActionResponse,
    summary="Stop recording",
)
async def stop_recording(session_id: str, handler: BotHandlerDep) -> SessionActionResponse:
    """Stop capturing and finalize the upload.

    A 200 here means the recording is durable: the bot returns only once the
    object is closed.
    """
    result = await handler.stop_recording(session_id)
    return SessionActionResponse(
        message="Recording stopped",
        session_id=session_id,
        recording_status=result["recording_status"],
        detail=result.get("detail"),
    )


@router.post(
    "/{session_id}/transcription/start",
    response_model=SessionActionResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Start transcription",
)
async def start_transcription(session_id: str, handler: BotHandlerDep) -> SessionActionResponse:
    result = await handler.start_transcription(session_id)
    return SessionActionResponse(
        message="Transcription start accepted",
        session_id=session_id,
        transcription_status=result["transcription_status"],
        detail=result.get("detail"),
    )


@router.post(
    "/{session_id}/transcription/stop",
    response_model=SessionActionResponse,
    summary="Stop transcription",
)
async def stop_transcription(session_id: str, handler: BotHandlerDep) -> SessionActionResponse:
    result = await handler.stop_transcription(session_id)
    return SessionActionResponse(
        message="Transcription stopped",
        session_id=session_id,
        transcription_status=result["transcription_status"],
        detail=result.get("detail"),
    )


@router.get(
    "/{session_id}/transcript",
    response_model=TranscriptResponse,
    summary="Get the transcript so far",
)
async def get_transcript(
    session_id: str, handler: BotHandlerDep, sessions: SessionServiceDep
) -> TranscriptResponse:
    session = await sessions.require_session(session_id)
    payload = await handler.get_transcript(session_id)
    return TranscriptResponse(
        session_id=session_id,
        meeting_id=session.meeting_id,
        count=payload.get("count", 0),
        segments=payload.get("segments", []),
    )


@router.get("/{session_id}/chat", response_model=ChatResponse, summary="Get chat messages")
async def get_chat(
    session_id: str, handler: BotHandlerDep, sessions: SessionServiceDep
) -> ChatResponse:
    session = await sessions.require_session(session_id)
    payload = await handler.get_chat(session_id)
    return ChatResponse(
        session_id=session_id,
        meeting_id=session.meeting_id,
        count=payload.get("count", 0),
        chat_segments=payload.get("chatSegments", []),
    )


@router.post("/{session_id}/audio/play", response_model=SessionActionResponse, summary="Play audio")
async def play_audio(
    session_id: str, request: PlayAudioRequest, handler: BotHandlerDep
) -> SessionActionResponse:
    detail = await handler.play_audio(session_id, request.audio_url, request.volume)
    return SessionActionResponse(message="Audio played", session_id=session_id, detail=detail)


@router.post("/{session_id}/audio/mute", response_model=SessionActionResponse, summary="Mute the bot")
async def mute(session_id: str, handler: BotHandlerDep) -> SessionActionResponse:
    detail = await handler.mute(session_id)
    return SessionActionResponse(message="Bot muted", session_id=session_id, detail=detail)


@router.post("/{session_id}/audio/unmute", response_model=SessionActionResponse, summary="Unmute the bot")
async def unmute(session_id: str, handler: BotHandlerDep) -> SessionActionResponse:
    detail = await handler.unmute(session_id)
    return SessionActionResponse(message="Bot unmuted", session_id=session_id, detail=detail)


@router.post("/{session_id}/leave", response_model=SessionActionResponse, summary="Leave the meeting")
async def leave_session(session_id: str, handler: BotHandlerDep) -> SessionActionResponse:
    """Leave the meeting and release the pod. Finalizes a running recording."""
    result = await handler.leave(session_id)
    return SessionActionResponse(
        message="Left meeting",
        session_id=session_id,
        meeting_status=result["meeting_status"],
        detail=result.get("detail"),
    )


@router.post("/{session_id}/stop", response_model=SessionActionResponse, summary="Stop the session")
async def stop_session(session_id: str, handler: BotHandlerDep) -> SessionActionResponse:
    result = await handler.stop(session_id)
    return SessionActionResponse(
        message="Session stopped",
        session_id=session_id,
        meeting_status=result["meeting_status"],
        detail=result.get("detail"),
    )


@router.get(
    "/{session_id}/status",
    response_model=SessionStatusResponse,
    summary="Get session status",
)
async def get_session_status(
    session_id: str,
    handler: BotHandlerDep,
    include_runtime: bool = Query(
        default=True, description="Also ask the pod what it is doing right now"
    ),
) -> SessionStatusResponse:
    """Durable state, enriched with the pod's live view when it is reachable."""
    return SessionStatusResponse(**await handler.get_status(session_id, include_runtime))
