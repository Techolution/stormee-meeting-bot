"""Meeting-layer value objects."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from urllib.parse import urlparse

from app.core.config import ProjectSettings
from app.core.time import INDIA_TIMEZONE
from app.recording.models import RecordingContext


@dataclass(frozen=True, slots=True)
class MeetingRequest:
    """A caller's request for the bot to attend a meeting.

    Immutable. Built once at the API boundary from validated input, with
    configured defaults already applied, so nothing downstream has to ask "was
    this set?" or reach for configuration again.
    """

    session_id: str
    meeting_id: str
    meeting_url: str
    user_name: str
    user_email: str
    project_id: str | None = None
    project_name: str | None = None
    meeting_title: str | None = None
    requested_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @classmethod
    def build(
        cls,
        *,
        meeting_url: str,
        defaults: ProjectSettings,
        session_id: str | None = None,
        user_name: str | None = None,
        user_email: str | None = None,
        project_id: str | None = None,
        project_name: str | None = None,
        meeting_title: str | None = None,
    ) -> MeetingRequest:
        """Create a request, filling unset attribution from configuration.

        Applying defaults here — once, at the edge — is what keeps
        ``getattr(self, 'user_name', fallback)`` out of the code that uses them.

        Args:
            session_id: The caller's own key for this session. Omit it to have
                one minted from the meeting code — the right choice unless the
                caller already has an id of its own to correlate against, since
                it cannot collide with a session already in flight.
        """
        meeting_code = meeting_code_from_url(meeting_url)
        resolved_session_id = session_id or new_session_id(meeting_code)
        return cls(
            # Internally this field is the attendance key used by the session
            # registry. Publicly it is returned as sessionId.
            session_id=resolved_session_id,
            # This legacy internal correlation keeps pre-recording lifecycle
            # state addressable; no public meetingId exists until recording.
            meeting_id=resolved_session_id,
            meeting_url=meeting_url,
            user_name=user_name or defaults.default_user_name,
            user_email=user_email or defaults.default_user_email,
            project_id=project_id or defaults.default_project_id,
            project_name=project_name or defaults.default_project_name,
            meeting_title=meeting_title or f"Meeting {datetime.now(INDIA_TIMEZONE):%Y-%m-%d}",
        )

    def to_recording_context(
        self,
        *,
        meeting_id: str | None = None,
        mode_ids: list[str] | None = None,
    ) -> RecordingContext:
        """Attribution the recording pipeline needs to register its upload."""
        return RecordingContext(
            meeting_id=meeting_id or self.meeting_id,
            session_id=self.session_id,
            project_id=self.project_id,
            project_name=self.project_name,
            meeting_title=self.meeting_title,
            user_name=self.user_name,
            user_email=self.user_email,
            mode_ids=tuple(mode_ids or ()),
        )


def meeting_code_from_url(meeting_url: str) -> str:
    """The meeting's own code, e.g. ``abc-defg-hij`` from a Meet URL.

    Used as the readable stem of a generated id. A bare uuid would be unique
    but would make logs and recording filenames impossible to trace back to a
    meeting by eye, which is the whole reason ids appear in them.
    """
    path = urlparse(meeting_url.strip()).path.strip("/")
    return path.rsplit("/", 1)[-1] if path else "meeting"


def new_session_id(base: str) -> str:
    """Identifier for one continuous attendance of a meeting."""
    return f"{base or 'meeting'}_{uuid.uuid4().hex}"


def new_meeting_id(base: str) -> str:
    """Identifier for a meeting, with an IST datetime suffix."""
    # Microseconds keep back-to-back recordings unique while retaining a
    # readable, chronologically sortable local date/time.
    ts = datetime.now(INDIA_TIMEZONE).strftime("%Y%m%dT%H%M%S%fIST")
    return f"{base or 'meeting'}_{ts}"


def new_recording_meeting_id(base: str) -> str:
    """Identifier for one recording: ``<meeting-code>_<IST date/time>``."""
    return new_meeting_id(base)
