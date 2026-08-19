"""Process-level services shared by every meeting session.

Constructed once at startup and handed to each session. Passing them explicitly
rather than reaching for module-level singletons is what makes a session
testable: a test builds a :class:`SessionDependencies` with fakes and the code
under test never knows the difference.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.browser.browser_manager import BrowserManager
from app.clients.cw_utils import CWUtilsClient
from app.clients.mail import MailClient
from app.clients.meeting_api import MeetingAPIClient
from app.clients.object_storage import ResumableUploadClient
from app.core.config import Settings
from app.repositories.base import MeetingStateRepository
from app.recording.highlights_manager import HighlightsManager

@dataclass(frozen=True, slots=True)
class SessionDependencies:
    """Everything a meeting session needs from outside itself."""

    settings: Settings
    browser_manager: BrowserManager
    state_repository: MeetingStateRepository
    cw_client: CWUtilsClient
    storage_client: ResumableUploadClient
    mail_client: MailClient | None = None
    meeting_api_client: MeetingAPIClient | None = None
    highlights_manager: HighlightsManager | None = None,
