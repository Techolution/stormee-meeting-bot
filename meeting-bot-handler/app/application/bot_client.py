"""Application-facing proxy to one bot pod.

Only HTTP concerns live here: where the pod is, what to send it, and what came
back. No database, no Kubernetes, no state transitions — the destination is
handed in by the caller, which has already resolved it.
"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional, Tuple

import httpx

from app.clients.meeting_api import DEFAULT_API_PREFIX, MeetingApiClient


class BotClient:
    """HTTP client bound to a single bot pod."""

    def __init__(
        self,
        service_url: Optional[str] = None,
        http_client: Optional[httpx.AsyncClient] = None,
        api_prefix: str = DEFAULT_API_PREFIX,
        timeout: float = 30.0,
    ):
        if service_url is None:
            # Local-development fallback only; production callers pass the
            # resolved pod address.
            service_url = os.getenv("BOT_SERVICE_URL", "http://localhost:5000")

        self.service_url = service_url.rstrip("/")
        self._owned_http_client = http_client is None
        self._http_client = http_client or httpx.AsyncClient(timeout=timeout)
        self.api_client = MeetingApiClient(
            base_url=self.service_url,
            http_client=self._http_client,
            api_prefix=api_prefix,
            timeout=timeout,
        )

    # --- Meeting lifecycle ---------------------------------------------------
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

    async def leave_meeting(self, meeting_id: str) -> Dict[str, Any]:
        return await self.api_client.leave_meeting(meeting_id)

    # --- Audio ---------------------------------------------------------------
    async def play_audio(self, meeting_id: str, audio_url: str, volume: float = 0.7) -> Dict[str, Any]:
        return await self.api_client.play_audio(meeting_id, audio_url, volume)

    async def mute(self, meeting_id: str) -> Dict[str, Any]:
        return await self.api_client.mute(meeting_id)

    async def unmute(self, meeting_id: str) -> Dict[str, Any]:
        return await self.api_client.unmute(meeting_id)

    # --- Recording -----------------------------------------------------------
    async def start_recording(self, meeting_id: str) -> Dict[str, Any]:
        return await self.api_client.start_recording(meeting_id)

    async def stop_recording(self, meeting_id: str) -> Dict[str, Any]:
        return await self.api_client.stop_recording(meeting_id)

    async def get_recording_status(self, meeting_id: str) -> Dict[str, Any]:
        return await self.api_client.get_recording_status(meeting_id)

    # --- Transcription and chat ----------------------------------------------
    async def start_transcription(self, meeting_id: str) -> Dict[str, Any]:
        return await self.api_client.start_transcription(meeting_id)

    async def stop_transcription(self, meeting_id: str) -> Dict[str, Any]:
        return await self.api_client.stop_transcription(meeting_id)

    async def get_transcript(self, meeting_id: str) -> Dict[str, Any]:
        return await self.api_client.get_transcript(meeting_id)

    async def get_chat(self, meeting_id: str) -> Dict[str, Any]:
        return await self.api_client.get_chat(meeting_id)

    # --- Status --------------------------------------------------------------
    async def get_meeting_status(self, meeting_id: str) -> Dict[str, Any]:
        return await self.api_client.get_bot_status(meeting_id)

    async def get_service_status(self) -> Dict[str, Any]:
        return await self.api_client.get_service_status()

    async def check_ready(self) -> Tuple[bool, Dict[str, Any]]:
        return await self.api_client.check_ready()

    async def close(self) -> None:
        if self._owned_http_client:
            await self._http_client.aclose()

    async def __aenter__(self) -> BotClient:
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.close()
