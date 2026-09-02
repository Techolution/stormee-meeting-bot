"""Meeting-layer value objects."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.core.config import ProjectSettings
from app.recording.models import RecordingContext


@dataclass(frozen=True, slots=True)
class MeetingRequest:
    """A caller's request for the bot to attend a meeting.

    Immutable. Built once at the API boundary from validated input, with
    configured defaults already applied, so nothing downstream has to ask "was
    this set?" or reach for configuration again.
    """

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
        meeting_id: str,
        meeting_url: str,
        defaults: ProjectSettings,
        user_name: str | None = None,
        user_email: str | None = None,
        project_id: str | None = None,
        project_name: str | None = None,
        meeting_title: str | None = None,
    ) -> MeetingRequest:
        """Create a request, filling unset attribution from configuration.

        Applying defaults here — once, at the edge — is what keeps
        ``getattr(self, 'user_name', fallback)`` out of the code that uses them.
        """
        return cls(
            meeting_id=meeting_id,
            meeting_url=meeting_url,
            user_name=user_name or defaults.default_user_name,
            user_email=user_email or defaults.default_user_email,
            project_id=project_id or defaults.default_project_id,
            project_name=project_name or defaults.default_project_name,
            meeting_title=meeting_title or f"Meeting {datetime.now(timezone.utc):%Y-%m-%d}",
        )

    def to_recording_context(self, *, mode_ids: list[str] | None = None) -> RecordingContext:
        """Attribution the recording pipeline needs to register its upload."""
        return RecordingContext(
            meeting_id=self.meeting_id,
            project_id=self.project_id,
            project_name=self.project_name,
            meeting_title=self.meeting_title,
            user_name=self.user_name,
            user_email=self.user_email,
            mode_ids=tuple(mode_ids or ()),
        )


def new_session_id() -> str:
    """Identifier for one attendance of one meeting.

    Distinct from ``meeting_id``: the same meeting rejoined after a failure is
    a new session, and correlating logs across a retry requires telling them
    apart.
    """
    return uuid.uuid4().hex[:16]
