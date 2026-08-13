import logging
from fastapi import HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional
from utilities.error_handler import log_exception

# Get module-level logger
logger = logging.getLogger(__name__)

from services.stormee_meet_bot_service import (
    create_bot_for,
    get_bot,
    remove_bot,
)

# Request models
class MeetingUrlRequest(BaseModel):
    meetingUrl: str
    meetingId: str
    userName: Optional[str] = None
    userEmail: Optional[str] = None
    projectId: Optional[str] = None
    projectName: Optional[str] = None
    meetingTitle: Optional[str] = None

class RecordingRequest(BaseModel):
    meetingId: str

class MeetingActionRequest(BaseModel):
    meetingId: str

class PlayAudioRequest(BaseModel):
    meetingId: str
    audioData: list  # List of integers (0-255) representing audio bytes
    volume: float = 0.7  # Volume level (0.0 to 1.0)


async def login_controller(request: MeetingUrlRequest):
    """Create a MeetBot for the meeting and join the specified meeting URL."""
    try:
        meeting_url = request.meetingUrl
        meeting_id = request.meetingId
        
        logger.debug(
            f"Login request received [meeting_id={meeting_id}, "
            f"user_name={request.userName}, user_email={request.userEmail}]"
        )
        
        if not meeting_url:
            logger.warning(f"Login validation failed for meeting {meeting_id}: meetingUrl is required")
            raise HTTPException(status_code=400, detail="meetingUrl is required")
        if not meeting_id:
            logger.warning("Login validation failed: meetingId is required")
            raise HTTPException(status_code=400, detail="meetingId is required")

        # Create bot and start join in background
        await create_bot_for(
            meeting_id,
            meeting_url,
            user_name=request.userName,
            user_email=request.userEmail,
            project_id=request.projectId,
            project_name=request.projectName,
            meeting_title=request.meetingTitle,
        )

        logger.info(f"Meeting join initialized for {meeting_id}")
        return JSONResponse(content={"message": "Meeting join started", "meetingId": meeting_id})
    except HTTPException:
        raise
    except Exception as err:
        context = {
            'meeting_id': request.meetingId,
            'user_email': request.userEmail,
            'user_name': request.userName,
        }
        logger.error(
            f"Failed to initiate meeting join for {request.meetingId}"
        )
        log_exception(logger, logging.ERROR, "Meeting join initialization failed", err, context)
        raise HTTPException(status_code=500, detail="Failed to join meeting")


async def start_captions_controller(request: MeetingActionRequest):
    """Start caption scraping for a specific meeting bot."""
    try:
        meeting_id = request.meetingId
        if not meeting_id:
            raise HTTPException(status_code=400, detail="meetingId is required")

        bot = get_bot(meeting_id)
        if not bot:
            raise HTTPException(status_code=404, detail="No bot found for meetingId")

        import asyncio
        asyncio.create_task(bot.start_captions())
        logger.info(f"Captions started for {meeting_id}")
        return JSONResponse(content={"message": "Captions started", "meetingId": meeting_id})
    except HTTPException:
        raise
    except Exception as err:
        logger.error(f"Error starting captions: {err}")
        raise HTTPException(status_code=500, detail="Failed to start captions")


async def stop_captions_controller(request: MeetingActionRequest):
    """Stop caption scraping for a specific meeting bot and return captions."""
    try:
        meeting_id = request.meetingId
        bot = get_bot(meeting_id)
        if not bot:
            raise HTTPException(status_code=404, detail="No bot found for meetingId")

        captions = await bot.stop_captions()
        return JSONResponse(content={
            "message": "Captions stopped",
            "captions": captions,
            "meetingId": meeting_id
        })
    except Exception as err:
        logger.error(f"Error stopping captions: {err}")
        raise HTTPException(status_code=500, detail="Failed to stop captions")


async def start_audio_controller(request: MeetingActionRequest):
    """Enable bot microphone for the given meeting bot."""
    try:
        meeting_id = request.meetingId
        bot = get_bot(meeting_id)
        if not bot:
            raise HTTPException(status_code=404, detail="No bot found for meetingId")

        await bot.play_audio()
        return JSONResponse(content={"message": "Audio played", "meetingId": meeting_id})
    except HTTPException:
        raise
    except Exception as err:
        logger.error(f"Error playing audio: {err}")
        raise HTTPException(status_code=500, detail="Failed to play audio")


async def stop_audio_controller(request: MeetingActionRequest):
    """Disable bot microphone for the given meeting bot."""
    try:
        meeting_id = request.meetingId
        bot = get_bot(meeting_id)
        if not bot:
            raise HTTPException(status_code=404, detail="No bot found for meetingId")

        await bot.pause_audio()
        return JSONResponse(content={"message": "Audio paused", "meetingId": meeting_id})
    except Exception as err:
        logger.error(f"Error pausing audio: {err}")
        raise HTTPException(status_code=500, detail="Failed to pause audio")


async def start_recording_controller(request: RecordingRequest):
    """Start audio recording for a particular meeting bot."""
    try:
        meeting_id = request.meetingId
        if not meeting_id:
            raise HTTPException(status_code=400, detail="meetingId is required")

        bot = get_bot(meeting_id)
        if not bot:
            raise HTTPException(status_code=404, detail="No bot found for meetingId")

        await bot.start_audio_recording(meeting_id)
        return JSONResponse(content={
            "message": "Audio recording started",
            "meetingId": meeting_id
        })
    except HTTPException:
        raise
    except Exception as err:
        logger.error(f"Error starting audio recording: {err}")
        raise HTTPException(status_code=500, detail="Failed to start audio recording")


async def stop_recording_controller(request: RecordingRequest):
    """Stop audio recording for a particular meeting bot."""
    try:
        meeting_id = request.meetingId
        bot = get_bot(meeting_id)
        if not bot:
            raise HTTPException(status_code=404, detail="No bot found for meetingId")

        await bot.stop_audio_recording()
        return JSONResponse(content={"message": "Audio recording stopped", "meetingId": meeting_id})
    except Exception as err:
        logger.error(f"Error stopping audio recording: {err}")
        raise HTTPException(status_code=500, detail="Failed to stop audio recording")


async def get_recording_status_controller():
    """Get recording status (placeholder)"""
    return JSONResponse(content={
        "message": "Recording status feature not yet implemented",
        "status": "unknown"
    })


async def start_chat_scraping_controller(request: MeetingActionRequest):
    """Start chat scraping for a specific meeting bot."""
    try:
        meeting_id = request.meetingId
        bot = get_bot(meeting_id)
        if not bot:
            raise HTTPException(status_code=404, detail="No bot found for meetingId")

        import asyncio
        asyncio.create_task(bot.start_chat_scraping())
        return JSONResponse(content={"message": "Chat scraping started", "meetingId": meeting_id})
    except Exception as err:
        logger.error(f"Error starting chat scraping: {err}")
        raise HTTPException(status_code=500, detail="Failed to start chat scraping")


async def stop_chat_scraping_controller(request: MeetingActionRequest):
    """Stop chat scraping for a specific meeting bot and return collected chat segments."""
    try:
        meeting_id = request.meetingId
        bot = get_bot(meeting_id)
        if not bot:
            raise HTTPException(status_code=404, detail="No bot found for meetingId")

        chat_segments = await bot.stop_chat_scraping()
        return JSONResponse(content={
            "message": "Chat scraping stopped",
            "chatSegments": chat_segments,
            "meetingId": meeting_id
        })
    except Exception as err:
        logger.error(f"Error stopping chat scraping: {err}")
        raise HTTPException(status_code=500, detail="Failed to stop chat scraping")

async def exit_meeting_controller(request: MeetingActionRequest):
    """Exit the meeting and remove the bot instance."""
    try:
        meeting_id = request.meetingId
        await remove_bot(meeting_id)
        return JSONResponse(content={"message": "Exited the meeting", "meetingId": meeting_id})
    except Exception as err:
        logger.error(f"Error exiting the meeting: {err}")
        raise HTTPException(status_code=500, detail="Failed to exit the meeting")


async def play_audio_controller(request: PlayAudioRequest):
    """Play audio data in the active meeting."""
    try:
        meeting_id = request.meetingId
        audio_data = request.audioData
        volume = request.volume
        
        logger.debug(
            f"Play audio request received [meeting_id={meeting_id}, "
            f"audio_size={len(audio_data)} bytes, volume={volume}]"
        )
        
        if not meeting_id:
            logger.warning("Play audio validation failed: meetingId is required")
            raise HTTPException(status_code=400, detail="meetingId is required")
        
        if not audio_data:
            logger.warning(f"Play audio validation failed for {meeting_id}: audioData is required")
            raise HTTPException(status_code=400, detail="audioData is required")
        
        # Validate volume range
        if not (0.0 <= volume <= 1.0):
            logger.warning(f"Play audio validation failed for {meeting_id}: volume must be between 0.0 and 1.0")
            raise HTTPException(status_code=400, detail="volume must be between 0.0 and 1.0")
        
        # Get bot instance
        bot = get_bot(meeting_id)
        if not bot:
            logger.error(f"No bot found for meeting {meeting_id}")
            raise HTTPException(status_code=404, detail="No bot found for meetingId")
        
        # Play audio
        result = await bot.play_audio_data(audio_data, volume=volume)
        
        if result:
            logger.info(
                f"Audio playback initiated for {meeting_id} "
                f"[size={len(audio_data)} bytes, volume={volume}]"
            )
            return JSONResponse(content={
                "message": "Audio playback initiated",
                "meetingId": meeting_id,
                "audioSize": len(audio_data),
                "volume": volume
            })
        else:
            logger.error(f"Failed to play audio for {meeting_id}")
            raise HTTPException(status_code=500, detail="Failed to play audio")
    
    except HTTPException:
        raise
    except Exception as err:
        context = {
            'meeting_id': request.meetingId,
            'audio_size': len(request.audioData) if request.audioData else 0,
            'volume': request.volume,
        }
        logger.error(f"Error playing audio for {request.meetingId}")
        log_exception(logger, logging.ERROR, "Audio playback failed", err, context)
        raise HTTPException(status_code=500, detail="Failed to play audio")