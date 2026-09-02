"""Recording endpoints."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.dependencies import ManagerDep
from app.schemas.recording import (
    RecordingActionResponse,
    RecordingStatusResponse,
    StartRecordingRequest,
    StopRecordingRequest,
)

router = APIRouter(prefix="/recordings", tags=["Recording"])


@router.post("/start", response_model=RecordingActionResponse, summary="Start recording")
async def start_recording(
    payload: StartRecordingRequest,
    manager: ManagerDep,
) -> RecordingActionResponse:
    """Begin capturing the meeting's mixed audio.

    Audio is chunked and streamed continuously, so a recording that is
    interrupted still retains everything captured before the interruption.

    Supports incremental segment recording:
    - max_duration_seconds: Automatically upload and generate highlights after this duration
    - generate_incremental_highlights: Request highlights for each segment
    """
    await manager.start_recording(
        payload.meeting_id,
        max_duration_seconds=payload.max_duration_seconds,
        generate_incremental_highlights=payload.generate_incremental_highlights,
        mode_ids=payload.mode_ids,
    )
    return RecordingActionResponse(message="Recording started", meeting_id=payload.meeting_id)


@router.post("/stop", response_model=RecordingActionResponse, summary="Stop recording")
async def stop_recording(
    payload: StopRecordingRequest,
    manager: ManagerDep,
) -> RecordingActionResponse:
    """Stop capturing, flush buffered audio, and finalize the upload.

    Returns once the object is closed and downstream processing has been
    requested, so a success here means the recording is durable.
    """
    await manager.stop_recording(payload.meeting_id)
    return RecordingActionResponse(message="Recording stopped", meeting_id=payload.meeting_id)


@router.get(
    "/{meeting_id}/status",
    response_model=RecordingStatusResponse,
    summary="Get recording status",
)
async def recording_status(meeting_id: str, manager: ManagerDep) -> RecordingStatusResponse:
    """Report capture and upload progress for a meeting."""
    session = manager.require_session(meeting_id)
    recorder = session.recorder

    if recorder is None:
        return RecordingStatusResponse(meeting_id=meeting_id, status="idle")

    stats = recorder.stats
    return RecordingStatusResponse(
        meeting_id=meeting_id,
        status=recorder.status.value,
        chunks_captured=stats.chunks_captured,
        chunks_uploaded=stats.chunks_uploaded,
        chunks_pending=recorder.pending_chunks,
        bytes_uploaded=stats.bytes_uploaded,
        started_at=stats.started_at.isoformat() if stats.started_at else None,
        stopped_at=stats.stopped_at.isoformat() if stats.stopped_at else None,
        transport=recorder.transport,
    )
