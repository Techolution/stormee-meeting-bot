from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, Optional
import httpx

logger = logging.getLogger(__name__)


class MeetingAPIError(Exception):
    """Raised when the worker bot API returns an error response."""

    def __init__(self, code: str, message: str, details: Dict[str, Any], status_code: int, request_id: str):
        self.code = code
        self.message = message
        self.details = details
        self.status_code = status_code
        self.request_id = request_id
        super().__init__(f"[{status_code}] {code}: {message} (Request ID: {request_id})")


class MeetingApiClient:
    """Low-level HTTP client wrapper for worker bot API instances."""

    def __init__(self, base_url: str, http_client: httpx.AsyncClient):
        # Base path defaults to /api/meet if not provided in URL
        self.base_url = base_url.rstrip("/")
        if not self.base_url.endswith("/api/meet"):
            self.base_url = f"{self.base_url}/api/meet"
        self.http_client = http_client

    def _build_headers(self, request_id: Optional[str] = None) -> Dict[str, str]:
        return {
            "Content-Type": "application/json",
            "X-Request-ID": request_id or str(uuid.uuid4()),
        }

    async def _request(
        self,
        method: str,
        path: str,
        json_data: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        request_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        url = f"{self.base_url}{path}"
        headers = self._build_headers(request_id)

        try:
            response = await self.http_client.request(
                method=method,
                url=url,
                json=json_data,
                params=params,
                headers=headers,
                timeout=15.0,
            )
        except httpx.RequestError as exc:
            logger.error(f"HTTP network error contacting Bot Worker at {url}: {exc}")
            raise

        if response.is_error:
            try:
                err_body = response.json()
                raise MeetingAPIError(
                    code=err_body.get("code", "unknown_error"),
                    message=err_body.get("message", response.text),
                    details=err_body.get("details", {}),
                    status_code=response.status_code,
                    request_id=err_body.get("requestId", headers["X-Request-ID"]),
                )
            except ValueError:
                response.raise_for_status()

        return response.json() if response.content else {}

    # Lifecycle Endpoints
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
        payload = {
            "meetingId": meeting_id,
            "meetingUrl": meeting_url,
            "userName": user_name,
            "userEmail": user_email,
            "projectId": project_id,
            "projectName": project_name,
            "meetingTitle": meeting_title,
        }
        # Filter out None values so backend defaults can take effect
        filtered_payload = {k: v for k, v in payload.items() if v is not None}
        return await self._request("POST", "/meetings/join", json_data=filtered_payload)

    async def leave_meeting(self, meeting_id: str) -> Dict[str, Any]:
        return await self._request("POST", "/meetings/leave", json_data={"meetingId": meeting_id})

    # Recording Endpoints
    async def start_recording(self, meeting_id: str) -> Dict[str, Any]:
        return await self._request("POST", "/recordings/start", json_data={"meetingId": meeting_id})

    async def stop_recording(self, meeting_id: str) -> Dict[str, Any]:
        return await self._request("POST", "/recordings/stop", json_data={"meetingId": meeting_id})

    async def get_recording_status(self, meeting_id: str) -> Dict[str, Any]:
        return await self._request("GET", f"/recordings/{meeting_id}/status")

    # Transcription Endpoints
    async def start_transcription(self, meeting_id: str) -> Dict[str, Any]:
        return await self._request("POST", "/transcription/start", json_data={"meetingId": meeting_id})

    async def stop_transcription(self, meeting_id: str) -> Dict[str, Any]:
        return await self._request("POST", "/transcription/stop", json_data={"meetingId": meeting_id})

    # Status & Health
    async def get_bot_status(self, meeting_id: str) -> Dict[str, Any]:
        return await self._request("GET", f"/meetings/{meeting_id}/status")

    async def get_readiness(self) -> Dict[str, Any]:
        return await self._request("GET", "/ready")