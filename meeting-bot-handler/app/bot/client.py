from typing import Any, Dict, Optional
import httpx
from app.clients.meeting_api import MeetingApiClient


class BotClient:
    """Application-level proxy to execute operations on a resolved Bot Service instance."""

    def __init__(self, service_url: str, http_client: httpx.AsyncClient):
        self.service_url = service_url
        self.api_client = MeetingApiClient(base_url=service_url, http_client=http_client)

    async def join(
        self,
        meeting_id: str,
        meeting_url: str,
        user_name: Optional[str] = None,
        user_email: Optional[str] = None,
        project_id: Optional[str] = None,
        project_name: Optional[str] = None,
        meeting_title: Optional[str] = None,
    ) -> Dict[str, Any]:
        return await self.api_client.join_meeting(
            meeting_id=meeting_id,
            meeting_url=meeting_url,
            userName=user_name,
            userEmail=user_email,
            projectId=project_id,
            projectName=project_name,
            meetingTitle=meeting_title,
        )

    async def leave(self, meeting_id: str) -> Dict[str, Any]:
        return await self.api_client.leave_meeting(meeting_id)

    async def start_recording(self, meeting_id: str) -> Dict[str, Any]:
        return await self.api_client.start_recording(meeting_id)

    async def stop_recording(self, meeting_id: str) -> Dict[str, Any]:
        return await self.api_client.stop_recording(meeting_id)

    async def start_transcription(self, meeting_id: str) -> Dict[str, Any]:
        return await self.api_client.start_transcription(meeting_id)

    async def stop_transcription(self, meeting_id: str) -> Dict[str, Any]:
        return await self.api_client.stop_transcription(meeting_id)

    async def get_runtime_status(self, meeting_id: str) -> Dict[str, Any]:
        return await self.api_client.get_bot_status(meeting_id)