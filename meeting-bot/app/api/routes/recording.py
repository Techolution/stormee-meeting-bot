"""Recording endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Body

from app.api.dependencies import ManagerDep
from app.recording.session_finalizer import SessionFinalizer, SessionFinalizationEvent
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


@router.post(
    "/sessions/finalize",
    response_model=dict,
    summary="Finalize Opus session and construct WebM container",
)
async def finalize_session(
    payload: dict = Body(...),
) -> dict:
    """Finalize a 5-minute Opus recording session and construct WebM container.
    
    Called by the frontend when:
    - 5-minute session boundary is reached
    - Recording is stopped
    
    This endpoint receives the session finalization event, queries the Opus packets
    from the database for that session, constructs a valid WebM container with EBML
    headers and audio track metadata, and uploads the resulting file to GCS.
    
    Args:
        payload: Session finalization event containing:
            - meeting_id: Meeting identifier
            - upload_session_id: Session identifier
            - start_time: Session start time (ISO format)
            - end_time: Session end time (ISO format)
            - sequence_range: {"start": int, "end": int} for packet lookup
            - duration_ms: Session duration in milliseconds
            - chunk_count: Number of chunks in session
            - byte_count: Total bytes in session
            - status: "complete"
    
    Returns:
        Result dict containing:
        - success: bool
        - session_id: Session identifier
        - webm_path: GCS path to WebM file (if successful)
        - size_bytes: WebM file size (if successful)
        - duration_ms: Actual duration of WebM (if successful)
        - packet_count: Number of Opus packets (if successful)
        - error: Error message (if failed)
    """
    try:
        # Parse event from payload
        from datetime import datetime
        
        event = SessionFinalizationEvent(
            meeting_id=payload.get("meetingId"),
            upload_session_id=payload.get("uploadSessionId"),
            start_time=datetime.fromisoformat(payload.get("startTime", "")),
            end_time=datetime.fromisoformat(payload.get("endTime", "")),
            sequence_range=payload.get("sequenceRange", {}),
            duration_ms=payload.get("durationMs", 0),
            chunk_count=payload.get("chunkCount", 0),
            byte_count=payload.get("byteCount", 0),
            status=payload.get("status", "complete"),
        )
        
        # Create finalizer and process session
        finalizer = SessionFinalizer()
        result = await finalizer.finalize_session(event)
        
        return result
    
    except Exception as error:
        return {
            "success": False,
            "error": str(error),
            "session_id": payload.get("uploadSessionId", "unknown"),
        }
