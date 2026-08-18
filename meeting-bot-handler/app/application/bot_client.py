from __future__ import annotations

import os
from typing import Any, Dict, Optional
import httpx

from app.clients.meeting_api import MeetingApiClient


class BotClient:
    """Application-level HTTP client proxy for calling worker bot instances."""

    def __init__(
        self,
        service_url: Optional[str] = None,
        http_client: Optional[httpx.AsyncClient] = None,
    ):
        if service_url is None:
            service_url = os.getenv("BOT_SERVICE_URL", "http://localhost:5000/api/meet")

        self.service_url = service_url.rstrip("/")
        self._owned_http_client = http_client is None
        self._http_client = http_client or httpx.AsyncClient(timeout=30.0)
        self.api_client = MeetingApiClient(base_url=self.service_url, http_client=self._http_client)

    async def join_meeting(
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
            user_name=user_name,
            user_email=user_email,
            project_id=project_id,
            project_name=project_name,
            meeting_title=meeting_title,
        )

    async def start_recording(self, meeting_id: str) -> Dict[str, Any]:
        return await self.api_client.start_recording(meeting_id)

    async def stop_recording(self, meeting_id: str) -> Dict[str, Any]:
        return await self.api_client.stop_recording(meeting_id)

    async def start_transcription(self, meeting_id: str) -> Dict[str, Any]:
        return await self.api_client.start_transcription(meeting_id)

    async def stop_transcription(self, meeting_id: str) -> Dict[str, Any]:
        return await self.api_client.stop_transcription(meeting_id)

    async def leave_meeting(self, meeting_id: str) -> Dict[str, Any]:
        return await self.api_client.leave_meeting(meeting_id)

    async def get_meeting_status(self, meeting_id: str) -> Dict[str, Any]:
        return await self.api_client.get_bot_status(meeting_id)

    async def close(self) -> None:
        if self._owned_http_client:
            await self._http_client.aclose()

    async def __aenter__(self) -> BotClient:
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.close()