"""HTTP client for one bot pod's API.

This is the only place that knows the bot's wire contract: its ``/api/meet``
base path, its camelCase payloads, and its error envelope. Everything above it
works in snake_case domain terms.

Two rules the bot API imposes, honoured here:

* ``X-Request-ID`` is echoed on every response and appears on every log line the
  bot writes for that request. The handler forwards its own inbound id so one
  id spans both services.
* Failures share one envelope — ``{code, message, details, requestId}`` — and
  callers branch on ``code``. It is forwarded unchanged onto
  :class:`BotOperationError`.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Tuple

import httpx

from app.core.context import get_request_id, new_request_id
from app.domain.exceptions import BotOperationError, BotServiceUnavailableError

logger = logging.getLogger(__name__)

DEFAULT_API_PREFIX = "/api/meet"

#: Bot error codes that mean "this pod cannot take the meeting" rather than
#: "the request was wrong". The handler retries these against another pod.
POD_BUSY_CODES = frozenset({"meeting_already_active"})


class MeetingApiClient:
    """Low-level HTTP client for a single bot pod."""

    def __init__(
        self,
        base_url: str,
        http_client: httpx.AsyncClient,
        api_prefix: str = DEFAULT_API_PREFIX,
        timeout: float = 30.0,
    ):
        prefix = api_prefix.rstrip("/")
        root = base_url.rstrip("/")
        # Accept a base URL given either with or without the API prefix.
        self.base_url = root if root.endswith(prefix) else f"{root}{prefix}"
        self.http_client = http_client
        self.timeout = timeout

    def _build_headers(self, request_id: Optional[str] = None) -> Dict[str, str]:
        return {
            "Content-Type": "application/json",
            "X-Request-ID": request_id or get_request_id() or new_request_id(),
        }

    async def _send(
        self,
        method: str,
        path: str,
        json_data: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        request_id: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> Tuple[httpx.Response, str]:
        url = f"{self.base_url}{path}"
        headers = self._build_headers(request_id)

        try:
            response = await self.http_client.request(
                method=method,
                url=url,
                json=json_data,
                params=params,
                headers=headers,
                timeout=timeout or self.timeout,
            )
        except httpx.HTTPError as exc:
            logger.error("Bot pod unreachable at %s: %s", url, exc)
            raise BotServiceUnavailableError(
                f"Bot pod at {self.base_url} is unreachable: {exc}",
                details={"url": url, "method": method},
            ) from exc

        return response, headers["X-Request-ID"]

    async def _request(
        self,
        method: str,
        path: str,
        json_data: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        request_id: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        response, sent_request_id = await self._send(
            method, path, json_data, params, request_id, timeout
        )

        if response.is_error:
            raise self._to_error(response, sent_request_id, method, path)

        if not response.content:
            return {}
        try:
            return response.json()
        except ValueError:
            return {"raw": response.text}

    def _to_error(
        self, response: httpx.Response, request_id: str, method: str, path: str
    ) -> BotOperationError:
        """Turn the bot's error envelope into a domain exception."""
        code = "internal_error"
        message = response.text
        details: Dict[str, Any] = {}

        try:
            body = response.json()
        except ValueError:
            body = None

        if isinstance(body, dict):
            code = body.get("code", code)
            message = body.get("message", message)
            details = body.get("details") or {}
            request_id = body.get("requestId") or request_id

        logger.warning(
            "Bot pod returned %d %s for %s %s: %s",
            response.status_code,
            code,
            method,
            path,
            message,
        )
        return BotOperationError(
            message=message or f"Bot returned HTTP {response.status_code}",
            code=code,
            status_code=response.status_code,
            request_id=request_id,
            details=details,
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
        payload = {
            "meetingId": meeting_id,
            "meetingUrl": meeting_url,
            "userName": user_name,
            "userEmail": user_email,
            "projectId": project_id,
            "projectName": project_name,
            "meetingTitle": meeting_title,
        }
        # Drop None so the bot's own defaults apply.
        payload = {k: v for k, v in payload.items() if v is not None}
        return await self._request("POST", "/meetings/join", json_data=payload)

    async def leave_meeting(self, meeting_id: str) -> Dict[str, Any]:
        return await self._request("POST", "/meetings/leave", json_data={"meetingId": meeting_id})

    # --- Audio ---------------------------------------------------------------
    async def play_audio(
        self, meeting_id: str, audio_url: str, volume: float = 0.7
    ) -> Dict[str, Any]:
        return await self._request(
            "POST",
            "/meetings/audio/play",
            json_data={"meetingId": meeting_id, "audioUrl": audio_url, "volume": volume},
        )

    async def mute(self, meeting_id: str) -> Dict[str, Any]:
        return await self._request("POST", "/meetings/audio/mute", json_data={"meetingId": meeting_id})

    async def unmute(self, meeting_id: str) -> Dict[str, Any]:
        return await self._request("POST", "/meetings/audio/unmute", json_data={"meetingId": meeting_id})

    # --- Recording -----------------------------------------------------------
    async def start_recording(self, meeting_id: str) -> Dict[str, Any]:
        return await self._request("POST", "/recordings/start", json_data={"meetingId": meeting_id})

    async def stop_recording(self, meeting_id: str) -> Dict[str, Any]:
        # Returns only once the object is closed, which can outlast a normal
        # request timeout on a long meeting.
        return await self._request(
            "POST",
            "/recordings/stop",
            json_data={"meetingId": meeting_id},
            timeout=max(self.timeout, 120.0),
        )

    async def get_recording_status(self, meeting_id: str) -> Dict[str, Any]:
        return await self._request("GET", f"/recordings/{meeting_id}/status")

    # --- Transcription and chat ----------------------------------------------
    async def start_transcription(self, meeting_id: str) -> Dict[str, Any]:
        return await self._request("POST", "/transcription/start", json_data={"meetingId": meeting_id})

    async def stop_transcription(self, meeting_id: str) -> Dict[str, Any]:
        return await self._request("POST", "/transcription/stop", json_data={"meetingId": meeting_id})

    async def get_transcript(self, meeting_id: str) -> Dict[str, Any]:
        return await self._request("GET", f"/transcription/{meeting_id}/transcript")

    async def get_chat(self, meeting_id: str) -> Dict[str, Any]:
        return await self._request("GET", f"/transcription/{meeting_id}/chat")

    # --- Status and health ---------------------------------------------------
    async def get_bot_status(self, meeting_id: str) -> Dict[str, Any]:
        return await self._request("GET", f"/meetings/{meeting_id}/status")

    async def get_service_status(self) -> Dict[str, Any]:
        return await self._request("GET", "/status")

    async def get_health(self) -> Dict[str, Any]:
        return await self._request("GET", "/health")

    async def check_ready(self) -> Tuple[bool, Dict[str, Any]]:
        """Ask whether the pod can take a new meeting.

        A busy pod answers 503 by design, so this reports rather than raises.
        """
        response, _ = await self._send("GET", "/ready")
        try:
            body = response.json()
        except ValueError:
            body = {}
        return response.status_code == httpx.codes.OK, body


#: The client previously exposed its own error type. Kept as an alias so
#: existing ``except MeetingAPIError`` call sites keep working.
MeetingAPIError = BotOperationError
