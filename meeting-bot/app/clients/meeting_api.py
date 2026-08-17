"""Client for the upstream Meeting API.

The Meeting API owns *durable* meeting state — what a meeting is, who booked
it, whether it ultimately succeeded. This process owns only *runtime* state:
what the bot is doing right now. Keeping the two apart is deliberate; see
:mod:`app.runtime.state`.

The integration is optional. When ``MEETING_API_URL`` is unset the client
becomes a no-op so the bot can run standalone, in tests, or in a deployment
where nothing upstream cares about status callbacks.
"""

from __future__ import annotations

import logging
from typing import Any

from app.clients.base import BaseHTTPClient
from app.core.config import MeetingAPISettings

logger = logging.getLogger(__name__)


class MeetingAPIClient(BaseHTTPClient):
    """Reports meeting outcomes back to the service that dispatched this bot."""

    service_name = "meeting-api"

    _ENDPOINT_STATUS = "/meetings/{meeting_id}/status"

    def __init__(self, settings: MeetingAPISettings) -> None:
        super().__init__(settings.base_url, timeout_seconds=settings.timeout_seconds, max_retries=2)
        self._settings = settings

    @property
    def enabled(self) -> bool:
        return self._settings.enabled

    async def report_status(
        self,
        meeting_id: str,
        status: str,
        *,
        detail: dict[str, Any] | None = None,
    ) -> bool:
        """Publish the bot's current status for a meeting.

        Called by: :meth:`app.meeting.meeting_session.MeetingSession._record_event`,
        once per durable lifecycle transition.

        Best-effort: a failed callback is logged, never raised. The bot's job is
        to run the meeting, not to guarantee delivery of telemetry.
        """
        if not self.enabled:
            return False

        try:
            await self.post_json(
                self._ENDPOINT_STATUS.format(meeting_id=meeting_id),
                operation="report_status",
                json={"status": status, "detail": detail or {}},
            )
        except Exception as error:  # noqa: BLE001 - telemetry must not break the meeting
            logger.warning(
                "Failed to report meeting status upstream",
                extra={"meeting_id": meeting_id, "status": status, "reason": str(error)},
            )
            return False

        logger.debug("Reported meeting status", extra={"meeting_id": meeting_id, "status": status})
        return True
