"""Composition root.

The one place that decides which concrete implementation satisfies each
interface. Every other module receives its collaborators; only this one
constructs them.

Keeping wiring here is what makes the dependency arrows in the rest of the
codebase real. If a domain module imported a concrete client directly, the
interface between them would be decorative.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from app.browser.browser_manager import BrowserManager
from app.clients.cw_utils import CWUtilsClient
from app.clients.mail import MailClient
from app.clients.meeting_api import MeetingAPIClient
from app.clients.object_storage import ResumableUploadClient
from app.core.config import Settings
from app.meeting.meeting_manager import MeetingManager
from app.meeting.session_dependencies import SessionDependencies
from app.meeting_platform.google_meet.scripts import init_scripts
from app.repositories import create_state_repository
from app.repositories.base import MeetingStateRepository

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ApplicationContext:
    """Everything constructed at startup, held for the process lifetime."""

    settings: Settings
    manager: MeetingManager
    state_repository: MeetingStateRepository
    cw_client: CWUtilsClient
    storage_client: ResumableUploadClient
    mail_client: MailClient | None
    meeting_api_client: MeetingAPIClient | None

    async def aclose(self) -> None:
        """Release every resource, in reverse order of construction.

        Best-effort: shutdown must complete even if a client misbehaves.
        """
        await self.manager.shutdown()

        for name, closer in (
            ("cw_client", self.cw_client.aclose),
            ("storage_client", self.storage_client.aclose),
            ("mail_client", self.mail_client.aclose if self.mail_client else None),
            ("meeting_api_client", self.meeting_api_client.aclose if self.meeting_api_client else None),
            ("state_repository", self.state_repository.close),
        ):
            if closer is None:
                continue
            try:
                await closer()
            except Exception as error:  # noqa: BLE001 - never block shutdown
                logger.warning("Error closing resource", extra={"resource": name, "reason": str(error)})


async def build_application_context(settings: Settings) -> ApplicationContext:
    """Construct the object graph for a running process.

    Validates what can be validated up front — notably that the browser scripts
    are present — so a packaging mistake fails at startup rather than at the
    first meeting.
    """
    _verify_browser_scripts()
    _warn_about_unconfigured_integrations(settings)

    state_repository = await create_state_repository(settings.redis)

    cw_client = CWUtilsClient(settings.cw_utils)
    storage_client = ResumableUploadClient(
        timeout_seconds=settings.recording.upload_timeout_seconds
    )
    mail_client = MailClient(settings.mail) if settings.mail.enabled else None
    meeting_api_client = (
        MeetingAPIClient(settings.meeting_api) if settings.meeting_api.enabled else None
    )

    dependencies = SessionDependencies(
        settings=settings,
        browser_manager=BrowserManager.from_settings(settings.browser),
        state_repository=state_repository,
        cw_client=cw_client,
        storage_client=storage_client,
        mail_client=mail_client,
        meeting_api_client=meeting_api_client,
    )

    # A bot pod drives one browser; running two meetings in one process means
    # two Chromium instances competing for the same memory budget.
    manager = MeetingManager(dependencies, max_concurrent_sessions=1)

    logger.info("Application context ready", extra=settings.describe())

    return ApplicationContext(
        settings=settings,
        manager=manager,
        state_repository=state_repository,
        cw_client=cw_client,
        storage_client=storage_client,
        mail_client=mail_client,
        meeting_api_client=meeting_api_client,
    )


def _verify_browser_scripts() -> None:
    """Fail fast if the browser-side JavaScript is missing from the build.

    These files are loaded from disk, so an incomplete image would otherwise
    surface as a failed join minutes into a meeting.
    """
    scripts = init_scripts()
    if not all(script.strip() for script in scripts):
        raise RuntimeError("browser init scripts are missing or empty; check the package build")


def _warn_about_unconfigured_integrations(settings: Settings) -> None:
    """Say plainly, once, which optional integrations are inactive.

    Silent degradation is the hardest kind of misconfiguration to diagnose.
    """
    if not settings.websocket.enabled:
        logger.warning(
            "No audio service configured (WEBSOCKET_URL); recordings will upload directly to storage"
        )
    if not settings.cw_utils.enabled:
        logger.warning(
            "No CW backend configured (CW_UTILS_URL); recordings cannot be stored or registered"
        )
    if not settings.meeting_api.enabled:
        logger.info("No Meeting API configured (MEETING_API_URL); status callbacks are disabled")
    if not settings.project.default_project_id:
        logger.info("No default project configured; every join request must supply projectId")
