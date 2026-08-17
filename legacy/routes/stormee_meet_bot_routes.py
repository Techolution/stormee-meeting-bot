import time
import uuid
from fastapi import APIRouter, Request, Depends, HTTPException
from utilities.logging_context import RequestContext
from controllers.stormee_meet_bot_controller import (
    exit_meeting_controller,
    login_controller,
    start_captions_controller,
    stop_captions_controller,
    start_audio_controller,
    stop_audio_controller,
    start_recording_controller,
    stop_recording_controller,
    get_recording_status_controller,
    start_chat_scraping_controller,
    stop_chat_scraping_controller,
    play_audio_controller,
    MeetingUrlRequest,
    RecordingRequest,
    MeetingActionRequest,
    PlayAudioRequest,
)
from services.meeting_state_manager import get_state_manager
from fastapi.responses import JSONResponse

router = APIRouter()


async def extract_context(request: Request) -> None:
    """Dependency function to extract and set request context.

    This function extracts the request URL, generates a unique request_id,
    initializes a timer, and attempts to extract meetingId from the request body.
    The context is then set via RequestContext.set_context().

    Args:
        request: FastAPI Request object containing request metadata and body.
    """
    request_url = str(request.url.path)
    request_id = str(uuid.uuid4())
    timer = time.time()
    meeting_id = ''

    # Attempt to extract meetingId from request body
    try:
        body = await request.json()
        if isinstance(body, dict):
            # Try both 'meetingId' and 'meetingUrl' fields
            meeting_id = body.get('meetingId', body.get('meetingUrl', ''))
    except Exception:
        # If request body cannot be parsed, continue with empty meetingId
        pass

    # Set the context
    RequestContext.set_context(
        request_id=request_id,
        timer=timer,
        meetingId=meeting_id,
        request_url=request_url
    )


@router.get("/health", tags=["Utility"], summary="Health check")
async def health_check():
    """
    Health check endpoint
    
    Returns:
        status: Service status (OK)
        message: Service is running
    """
    return {"status": "OK", "message": "Service is running"}


@router.get("/meetings/{meeting_id}/state", tags=["Meeting State"], summary="Get current meeting state")
async def get_meeting_state(meeting_id: str, _: None = Depends(extract_context)):
    """
    Get the current state of a meeting
    
    Args:
        meeting_id: The meeting ID to get state for
    
    Returns:
        Current state with timestamp and metadata
    
    Raises:
        404: Meeting state not found
    """
    state_manager = get_state_manager()
    state = await state_manager.get_state(meeting_id)
    
    if not state:
        raise HTTPException(
            status_code=404,
            detail=f"No state found for meeting {meeting_id}"
        )
    
    return JSONResponse(
        content={
            "meeting_id": meeting_id,
            "state": state
        }
    )


@router.get("/meetings/{meeting_id}/states", tags=["Meeting State"], summary="Get meeting state history")
async def get_meeting_state_history(
    meeting_id: str,
    limit: int = 100,
    _: None = Depends(extract_context)
):
    """
    Get the state history for a meeting
    
    Args:
        meeting_id: The meeting ID to get history for
        limit: Maximum number of history items to return (default: 100)
    
    Returns:
        List of state changes (most recent first)
    """
    state_manager = get_state_manager()
    history = await state_manager.get_state_history(meeting_id, limit=limit)
    
    return JSONResponse(
        content={
            "meeting_id": meeting_id,
            "history": history,
            "count": len(history)
        }
    )


@router.delete("/meetings/{meeting_id}/state", tags=["Meeting State"], summary="Delete meeting state")
async def delete_meeting_state(meeting_id: str, _: None = Depends(extract_context)):
    """
    Delete all state data for a meeting
    
    Args:
        meeting_id: The meeting ID to delete state for
    
    Returns:
        Confirmation message
    """
    state_manager = get_state_manager()
    success = await state_manager.delete_state(meeting_id)
    
    if not success:
        raise HTTPException(
            status_code=500,
            detail="Failed to delete meeting state"
        )
    
    return JSONResponse(
        content={
            "message": f"State deleted for meeting {meeting_id}",
            "meeting_id": meeting_id
        }
    )


@router.post("/signin", tags=["Meeting Control"], summary="Join a Google Meet meeting")
async def signin(request: MeetingUrlRequest, _: None = Depends(extract_context)):
    """
    Join a Google Meet meeting
    
    Args:
        meetingUrl: The Google Meet URL to join (e.g., https://meet.google.com/abc-xyz-def)
    
    Returns:
        message: Meeting joined successfully
    
    Raises:
        400: Invalid input (missing meetingUrl)
        500: Failed to join meeting
    """
    return await login_controller(request)


@router.post("/start", tags=["Captions"], summary="Start scraping captions/transcript")
async def start_captions(request: MeetingUrlRequest, _: None = Depends(extract_context)):
    """
    Start scraping captions/transcript
    
    Args:
        meetingUrl: The Google Meet URL
    
    Returns:
        message: Captions started
    
    Raises:
        400: Invalid input
        500: Failed to start captions
    """
    return await start_captions_controller(request)


@router.post("/stop", tags=["Captions"], summary="Stop captions scraping and return the full transcript")
async def stop_captions(request: MeetingActionRequest, _: None = Depends(extract_context)):
    """
    Stop captions scraping and return the full transcript
    
    Returns:
        message: Captions stopped
        captions: Array of caption objects with text and timestamp
    
    Raises:
        500: Failed to stop captions
    """
    return await stop_captions_controller()


@router.post("/audio", tags=["Meeting Control"], summary="Turn on the bot's microphone")
async def enable_audio(request: MeetingActionRequest, _: None = Depends(extract_context)):
    """
    Turn on the bot's microphone
    
    Returns:
        message: Audio played
    
    Raises:
        400: No active meeting
        500: Failed to enable audio
    """
    return await start_audio_controller()


@router.post("/pauseaudio", tags=["Meeting Control"], summary="Mute the bot's microphone")
async def disable_audio(request: MeetingActionRequest, _: None = Depends(extract_context)):
    """
    Mute the bot's microphone
    
    Returns:
        message: Audio paused
    
    Raises:
        500: Failed to pause audio
    """
    return await stop_audio_controller()


@router.post("/record/start", tags=["Recording"], summary="Start recording and streaming the full meeting audio")
async def start_recording(request: RecordingRequest, _: None = Depends(extract_context)):
    """
    Start recording and streaming the full meeting audio
    
    Args:
        meetingId: Unique identifier for this recording session (e.g., GMeet-12345)
    
    Returns:
        message: Audio recording started
        meetingId: The meeting ID
    
    Raises:
        400: Invalid input (missing meetingId)
        500: Failed to start audio recording
    """
    return await start_recording_controller(request)


@router.post("/record/stop", tags=["Recording"], summary="Stop recording, save, and convert the audio file")
async def stop_recording(request: RecordingRequest, _: None = Depends(extract_context)):
    """
    Stop recording, save, and convert the audio file
    
    Returns:
        message: Audio recording stopped
    
    Raises:
        500: Failed to stop audio recording
    """
    return await stop_recording_controller(request)


@router.get("/record/status", tags=["Recording"], summary="Get the current audio recording status (Placeholder)")
async def get_recording_status():
    """
    Get the current audio recording status (Placeholder)
    
    Returns:
        message: Recording status feature not yet implemented
        status: unknown
    """
    return await get_recording_status_controller()


@router.post("/audio/play", tags=["Audio Playback"], summary="Play audio in the active Google Meet meeting")
async def play_audio(request: PlayAudioRequest, _: None = Depends(extract_context)):
    """
    Play audio data through the bot's speakers in the active Google Meet meeting.
    
    Args:
        meetingId: The meeting ID where audio should be played
        audioUrl: Audio Stream url
        volume: Playback volume level (0.0 to 1.0, default 0.7)
    
    Returns:
        message: Audio playback initiated
        meetingId: The meeting ID
        audioSize: Size of audio data in bytes
        volume: Playback volume level
    
    Raises:
        400: Invalid input (missing meetingId, audioUrl, or invalid volume)
        404: No active bot for the meeting
        500: Failed to play audio
    """
    return await play_audio_controller(request)


@router.post("/chat/start", tags=["Chat"], summary="Start scraping and monitoring the meeting chat")
async def start_chat_scraping(request: MeetingActionRequest, _: None = Depends(extract_context)):
    """
    Start scraping and monitoring the meeting chat
    
    Returns:
        message: Chat scraping started
    
    Raises:
        500: Failed to start chat scraping
    """
    return await start_chat_scraping_controller(request)


@router.post("/chat/stop", tags=["Chat"], summary="Stop chat scraping and return collected chat segments")
async def stop_chat_scraping(request: MeetingActionRequest, _: None = Depends(extract_context)):
    """
    Stop chat scraping and return collected chat segments
    
    Returns:
        message: Chat scraping stopped
        chatSegments: Array of chat message objects with sender, text, and timestamp
    
    Raises:
        500: Failed to stop chat scraping
    """
    return await stop_chat_scraping_controller(request)

@router.post("/exit", tags=["Meeting Control"], summary="Exit the Google Meet meeting")
async def exit_meeting(request: MeetingActionRequest, _: None = Depends(extract_context)):
    """
    Exit the Google Meet meeting
    
    Returns:
        message: Meeting exited successfully
    
    Raises:
        500: Failed to exit meeting
    """
    return await exit_meeting_controller(request=request)