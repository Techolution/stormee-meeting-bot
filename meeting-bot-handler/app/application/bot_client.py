"""
HTTP client for communicating with the Meeting Bot service.

This module handles **all direct HTTP communication** with the meeting-bot API.
It knows about:
- HTTP endpoints
- HTTP methods (GET, POST, etc.)
- Request URLs, bodies, and payloads
- Timeouts and httpx responses
- HTTP status codes and error handling

It does NOT know about:
- DB access
- Kubernetes logic
- Redis
- state-transition decisions
- business logic or orchestration
"""

from __future__ import annotations

import httpx
import os
from typing import Any


class BotClient:
    """HTTP client for the Meeting Bot service.
    
    Handles all direct communication with the meeting-bot API.
    Each method corresponds to one Bot API endpoint.
    """

    def __init__(self, service_url: str | None = None):
        """Initialize the BotClient with the bot service URL from environment.
        
        Args:
            service_url: Optional override for BOT_SERVICE_URL environment variable.
                        If not provided, reads from environment with default http://localhost:8000
        """
        if service_url is None:
            service_url = os.getenv(
                "BOT_SERVICE_URL",
                "http://localhost:8000"
            )
        self.service_url = service_url.rstrip("/")
        self._http_client = httpx.AsyncClient(timeout=30.0)

    async def join_meeting(self, meeting_id: str) -> dict[str, Any]:
        """Join a meeting.
        
        Calls: POST /meetings/join
        
        Args:
            meeting_id: The meeting identifier to join.
            
        Returns:
            The Bot API response as a dictionary.
            
        Raises:
            httpx.HTTPStatusError: If the request fails with a non-2xx status.
        """
        payload = {"meetingId": meeting_id}
        url = f"{self.service_url}/meetings/join"
        response = await self._http_client.post(url, json=payload)
        response.raise_for_status()
        return response.json()

    async def start_recording(self, meeting_id: str) -> dict[str, Any]:
        """Start recording for a meeting.
        
        Calls: POST /recordings/start
        
        Args:
            meeting_id: The meeting identifier to start recording for.
            
        Returns:
            The Bot API response as a dictionary.
            
        Raises:
            httpx.HTTPStatusError: If the request fails with a non-2xx status.
        """
        payload = {"meetingId": meeting_id}
        url = f"{self.service_url}/recordings/start"
        response = await self._http_client.post(url, json=payload)
        response.raise_for_status()
        return response.json()

    async def stop_recording(self, meeting_id: str) -> dict[str, Any]:
        """Stop recording for a meeting.
        
        Calls: POST /recordings/stop
        
        Args:
            meeting_id: The meeting identifier to stop recording for.
            
        Returns:
            The Bot API response as a dictionary.
            
        Raises:
            httpx.HTTPStatusError: If the request fails with a non-2xx status.
        """
        payload = {"meetingId": meeting_id}
        url = f"{self.service_url}/recordings/stop"
        response = await self._http_client.post(url, json=payload)
        response.raise_for_status()
        return response.json()

    async def start_transcription(self, meeting_id: str) -> dict[str, Any]:
        """Start transcription for a meeting.
        
        Calls: POST /transcription/start
        
        Args:
            meeting_id: The meeting identifier to start transcription for.
            
        Returns:
            The Bot API response as a dictionary.
            
        Raises:
            httpx.HTTPStatusError: If the request fails with a non-2xx status.
        """
        payload = {"meetingId": meeting_id}
        url = f"{self.service_url}/transcription/start"
        response = await self._http_client.post(url, json=payload)
        response.raise_for_status()
        return response.json()

    async def stop_transcription(self, meeting_id: str) -> dict[str, Any]:
        """Stop transcription for a meeting.
        
        Calls: POST /transcription/stop
        
        Args:
            meeting_id: The meeting identifier to stop transcription for.
            
        Returns:
            The Bot API response as a dictionary.
            
        Raises:
            httpx.HTTPStatusError: If the request fails with a non-2xx status.
        """
        payload = {"meetingId": meeting_id}
        url = f"{self.service_url}/transcription/stop"
        response = await self._http_client.post(url, json=payload)
        response.raise_for_status()
        return response.json()

    async def leave_meeting(self, meeting_id: str) -> dict[str, Any]:
        """Leave a meeting.
        
        Calls: POST /meetings/leave
        
        Args:
            meeting_id: The meeting identifier to leave.
            
        Returns:
            The Bot API response as a dictionary.
            
        Raises:
            httpx.HTTPStatusError: If the request fails with a non-2xx status.
        """
        payload = {"meetingId": meeting_id}
        url = f"{self.service_url}/meetings/leave"
        response = await self._http_client.post(url, json=payload)
        response.raise_for_status()
        return response.json()

    async def get_meeting_status(self, meeting_id: str) -> dict[str, Any]:
        """Get the status of a meeting session.
        
        Calls: GET /meetings/{meeting_id}/status
        
        Args:
            meeting_id: The meeting identifier to get status for.
            
        Returns:
            The Bot API response as a dictionary containing session status.
            
        Raises:
            httpx.HTTPStatusError: If the request fails with a non-2xx status.
        """
        url = f"{self.service_url}/meetings/{meeting_id}/status"
        response = await self._http_client.get(url)
        response.raise_for_status()
        return response.json()

    async def close(self) -> None:
        """Close the HTTP client connection."""
        await self._http_client.aclose()

    async def __aenter__(self) -> BotClient:
        """Context manager entry."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Context manager exit, closing the HTTP client."""
        await self.close()

