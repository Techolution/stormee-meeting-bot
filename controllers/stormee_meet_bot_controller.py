from fastapi import HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from services.stormee_meet_bot_service import meet_bot
from typing import Optional

# Request models
class MeetingUrlRequest(BaseModel):
    meetingUrl: str

class RecordingRequest(BaseModel):
    meetingId: str

# Current meeting URL tracker
current_meeting_url: Optional[str] = None


async def login_controller(request: MeetingUrlRequest):
    """Join a Google Meet meeting"""
    global current_meeting_url
    try:
        meeting_url = request.meetingUrl
        if not meeting_url:
            raise HTTPException(status_code=400, detail="meetingUrl is required")
        
        current_meeting_url = meeting_url
        
        # Start join in background
        import asyncio
        asyncio.create_task(meet_bot.join_meeting(meeting_url))
        print("Joined meeting")
        
        return JSONResponse(content={"message": "Meeting joined"})
    except HTTPException:
        raise
    except Exception as err:
        print(f"Error joining meeting: {err}")
        raise HTTPException(status_code=500, detail="Failed to join meeting")


async def start_captions_controller(request: MeetingUrlRequest):
    """Start caption scraping"""
    try:
        meeting_url = request.meetingUrl
        if not meeting_url:
            raise HTTPException(status_code=400, detail="meetingUrl is required")
        
        global current_meeting_url
        current_meeting_url = meeting_url
        
        import asyncio
        asyncio.create_task(meet_bot.start_captions())
        print("Captions started")
        
        return JSONResponse(content={"message": "Captions started"})
    except HTTPException:
        raise
    except Exception as err:
        print(f"Error starting captions: {err}")
        raise HTTPException(status_code=500, detail="Failed to start captions")


async def stop_captions_controller():
    """Stop caption scraping"""
    try:
        captions = await meet_bot.stop_captions()
        return JSONResponse(content={
            "message": "Captions stopped",
            "captions": captions
        })
    except Exception as err:
        print(f"Error stopping captions: {err}")
        raise HTTPException(status_code=500, detail="Failed to stop captions")


async def start_audio_controller():
    """Enable bot microphone"""
    try:
        if not current_meeting_url:
            raise HTTPException(
                status_code=400,
                detail="No active meeting. Join a meeting first."
            )
        
        await meet_bot.play_audio()
        return JSONResponse(content={"message": "Audio played"})
    except HTTPException:
        raise
    except Exception as err:
        print(f"Error playing audio: {err}")
        raise HTTPException(status_code=500, detail="Failed to play audio")


async def stop_audio_controller():
    """Disable bot microphone"""
    try:
        await meet_bot.pause_audio()
        return JSONResponse(content={"message": "Audio paused"})
    except Exception as err:
        print(f"Error pausing audio: {err}")
        raise HTTPException(status_code=500, detail="Failed to pause audio")


async def start_recording_controller(request: RecordingRequest):
    """Start audio recording"""
    try:
        meeting_id = request.meetingId
        if not meeting_id:
            raise HTTPException(status_code=400, detail="meetingId is required")
        
        await meet_bot.start_audio_recording(meeting_id)
        return JSONResponse(content={
            "message": "Audio recording started",
            "meetingId": meeting_id
        })
    except HTTPException:
        raise
    except Exception as err:
        print(f"Error starting audio recording: {err}")
        raise HTTPException(status_code=500, detail="Failed to start audio recording")


async def stop_recording_controller():
    """Stop audio recording"""
    try:
        await meet_bot.stop_audio_recording()
        return JSONResponse(content={"message": "Audio recording stopped"})
    except Exception as err:
        print(f"Error stopping audio recording: {err}")
        raise HTTPException(status_code=500, detail="Failed to stop audio recording")


async def get_recording_status_controller():
    """Get recording status (placeholder)"""
    return JSONResponse(content={
        "message": "Recording status feature not yet implemented",
        "status": "unknown"
    })


async def start_chat_scraping_controller():
    """Start chat scraping"""
    try:
        await meet_bot.start_chat_scraping()
        return JSONResponse(content={"message": "Chat scraping started"})
    except Exception as err:
        print(f"Error starting chat scraping: {err}")
        raise HTTPException(status_code=500, detail="Failed to start chat scraping")


async def stop_chat_scraping_controller():
    """Stop chat scraping"""
    try:
        chat_segments = await meet_bot.stop_chat_scraping()
        return JSONResponse(content={
            "message": "Chat scraping stopped",
            "chatSegments": chat_segments
        })
    except Exception as err:
        print(f"Error stopping chat scraping: {err}")
        raise HTTPException(status_code=500, detail="Failed to stop chat scraping")

async def exit_meeting_controller():
    """Exit the meeting"""
    try:
        await meet_bot.leave_meeting()
        return JSONResponse(content={"message": "Exited the meeting"})
    except Exception as err:
        print(f"Error exiting the meeting: {err}")
        raise HTTPException(status_code=500, detail="Failed to exit the meeting")