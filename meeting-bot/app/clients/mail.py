"""Notification mail client.

Mail is a courtesy, never a dependency: a failure to notify must not fail a
meeting. Every method here therefore reports success as a boolean and logs the
reason on failure rather than raising into the caller's path.

Message bodies live in :mod:`app.clients.templates` so this module stays about
delivery.
"""

from __future__ import annotations

import logging

from app.clients.base import BaseHTTPClient
from app.clients.templates import render_meeting_artifact_ready, render_meeting_file_uploaded
from app.core.config import MailSettings

logger = logging.getLogger(__name__)


class MailClient(BaseHTTPClient):
    """Sends transactional mail through the CW mail relay."""

    service_name = "mail"

    _ENDPOINT_SEND = "/backend/utility/cw-email"

    def __init__(self, settings: MailSettings) -> None:
        super().__init__(
            settings.base_url,
            timeout_seconds=settings.timeout_seconds,
            max_retries=1,
        )
        self._settings = settings

    @property
    def enabled(self) -> bool:
        return self._settings.enabled and self.is_configured

    async def send(
        self,
        *,
        to_email: str,
        subject: str,
        html_body: str,
        cc: str = "",
    ) -> bool:
        """Send one message. Returns False instead of raising when delivery fails."""
        if not self.enabled:
            logger.debug("Mail disabled; skipping send", extra={"subject": subject})
            return False
        if not to_email:
            logger.warning("Mail skipped: no recipient", extra={"subject": subject})
            return False

        try:
            await self.post_json(
                self._ENDPOINT_SEND,
                operation="send_email",
                json={"to_email": to_email, "subject": subject, "body": html_body, "cc": cc},
            )
        except Exception as error:  # noqa: BLE001 - notification must never break a meeting
            logger.warning(
                "Failed to send notification email",
                extra={"to_email": to_email, "subject": subject, "reason": str(error)},
            )
            return False

        logger.info("Notification email sent", extra={"to_email": to_email, "subject": subject})
        return True

    async def send_meeting_file_uploaded(
        self,
        *,
        user_name: str,
        user_email: str,
        project_name: str,
        project_url: str,
        meeting_title: str,
        file_type: str = "recording",
        cc: str | None = None,
    ) -> bool:
        """Tell a user their meeting recording or transcript is available."""
        subject, html = render_meeting_file_uploaded(
            user_name=user_name,
            project_name=project_name,
            project_url=project_url,
            meeting_title=meeting_title,
            file_type=file_type,
        )
        return await self.send(
            to_email=user_email,
            subject=subject,
            html_body=html,
            cc=cc or "",
        )

    async def send_meeting_artifact_ready(
        self,
        *,
        user_name: str,
        user_email: str,
        meeting_title: str,
        artifact_url: str,
        cc: str | None = None,
    ) -> bool:
        """Tell a user the first meeting artifact is ready to open."""
        subject, html = render_meeting_artifact_ready(
            user_name=user_name,
            meeting_title=meeting_title,
            artifact_url=artifact_url,
        )
        return await self.send(
            to_email=user_email,
            subject=subject,
            html_body=html,
            cc=cc or "",
        )
