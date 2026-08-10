from fastapi import APIRouter
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
    MeetingUrlRequest,
    RecordingRequest,
    MeetingActionRequest,
)

router = APIRouter()


@router.get("/health", tags=["Utility"], summary="Health check")
async def health_check():
    """
    Health check endpoint
    
    Returns:
        status: Service status (OK)
        message: Service is running
    """
    return {"status": "OK", "message": "Service is running"}


@router.post("/signin", tags=["Meeting Control"], summary="Join a Google Meet meeting")
async def signin(request: MeetingUrlRequest):
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
async def start_captions(request: MeetingUrlRequest):
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
async def stop_captions(request: MeetingActionRequest):
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
async def enable_audio(request: MeetingActionRequest):
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
async def disable_audio(request: MeetingActionRequest):
    """
    Mute the bot's microphone
    
    Returns:
        message: Audio paused
    
    Raises:
        500: Failed to pause audio
    """
    return await stop_audio_controller()


@router.post("/record/start", tags=["Recording"], summary="Start recording and streaming the full meeting audio")
async def start_recording(request: RecordingRequest):
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
async def stop_recording(request: RecordingRequest):
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


@router.post("/chat/start", tags=["Chat"], summary="Start scraping and monitoring the meeting chat")
async def start_chat_scraping(request: MeetingActionRequest):
    """
    Start scraping and monitoring the meeting chat
    
    Returns:
        message: Chat scraping started
    
    Raises:
        500: Failed to start chat scraping
    """
    return await start_chat_scraping_controller(request)


@router.post("/chat/stop", tags=["Chat"], summary="Stop chat scraping and return collected chat segments")
async def stop_chat_scraping(request: MeetingActionRequest):
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
async def exit_meeting(request: MeetingActionRequest):
    """
    Exit the Google Meet meeting
    
    Returns:
        message: Meeting exited successfully
    
    Raises:
        500: Failed to exit meeting
    """
    return await exit_meeting_controller(request=request)