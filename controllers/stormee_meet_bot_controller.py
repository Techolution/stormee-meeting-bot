from fastapi import HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional

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


async def login_controller(request: MeetingUrlRequest):
    """Create a MeetBot for the meeting and join the specified meeting URL."""
    try:
        meeting_url = request.meetingUrl
        meeting_id = request.meetingId
        if not meeting_url:
            raise HTTPException(status_code=400, detail="meetingUrl is required")
        if not meeting_id:
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

        print(f"Started join for meeting {meeting_id}")
        return JSONResponse(content={"message": "Meeting join started", "meetingId": meeting_id})
    except HTTPException:
        raise
    except Exception as err:
        print(f"Error joining meeting: {err}")
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
        print(f"Captions started for {meeting_id}")
        return JSONResponse(content={"message": "Captions started", "meetingId": meeting_id})
    except HTTPException:
        raise
    except Exception as err:
        print(f"Error starting captions: {err}")
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
        print(f"Error stopping captions: {err}")
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
        print(f"Error playing audio: {err}")
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
        print(f"Error pausing audio: {err}")
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
        print(f"Error starting audio recording: {err}")
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
        print(f"Error stopping audio recording: {err}")
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
        print(f"Error starting chat scraping: {err}")
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
        print(f"Error stopping chat scraping: {err}")
        raise HTTPException(status_code=500, detail="Failed to stop chat scraping")

async def exit_meeting_controller(request: MeetingActionRequest):
    """Exit the meeting and remove the bot instance."""
    try:
        meeting_id = request.meetingId
        await remove_bot(meeting_id)
        return JSONResponse(content={"message": "Exited the meeting", "meetingId": meeting_id})
    except Exception as err:
        print(f"Error exiting the meeting: {err}")
        raise HTTPException(status_code=500, detail="Failed to exit the meeting")