"""Session registry.

Tracks the sessions this process is running, keyed by meeting id. Small on
purpose: it holds references and enforces uniqueness, and knows nothing about
what a session does.

Uniqueness is enforced rather than tolerated. The previous implementation
returned the existing bot when asked to join a meeting twice, which quietly
turned a duplicate request into a success and left the caller believing a fresh
join had happened.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterator
from typing import TYPE_CHECKING

from app.core.exceptions import MeetingAlreadyActiveError, MeetingNotFoundError

if TYPE_CHECKING:  # pragma: no cover - import cycle guard
    from app.meeting.meeting_session import MeetingSession

logger = logging.getLogger(__name__)


class SessionRegistry:
    """The meeting sessions running in this process."""

    def __init__(self, *, max_sessions: int = 0) -> None:
        """
        Args:
            max_sessions: Hard cap on concurrent sessions. ``0`` means no cap.
                A bot pod normally runs one meeting; a cap turns a runaway
                dispatcher into a rejected request rather than an OOM kill.
        """
        self._sessions: dict[str, MeetingSession] = {}
        self._max_sessions = max_sessions
        self._lock = asyncio.Lock()

    def __len__(self) -> int:
        return len(self._sessions)

    def __contains__(self, meeting_id: object) -> bool:
        return meeting_id in self._sessions

    def __iter__(self) -> Iterator[MeetingSession]:
        return iter(list(self._sessions.values()))

    @property
    def meeting_ids(self) -> list[str]:
        return sorted(self._sessions)

    @property
    def is_full(self) -> bool:
        return bool(self._max_sessions) and len(self._sessions) >= self._max_sessions

    @staticmethod
    def _normalise_meeting_id(meeting_id: str | int) -> str:
        return str(meeting_id).strip()

    async def add(self, session: MeetingSession) -> None:
        """Register a session.

        Raises:
            MeetingAlreadyActiveError: If this meeting already has a session, or
                the process is at capacity.
        """
        async with self._lock:
            meeting_id = self._normalise_meeting_id(session.meeting_id)
            if meeting_id in self._sessions:
                raise MeetingAlreadyActiveError(meeting_id)
            if self.is_full:
                raise MeetingAlreadyActiveError(
                    f"session limit reached ({self._max_sessions}); cannot start {meeting_id}"
                )

            self._sessions[meeting_id] = session
            logger.info(
                "Session registered",
                extra={
                    "meeting_id": meeting_id,
                    "session_id": session.session_id,
                    "active_sessions": len(self._sessions),
                },
            )

    async def remove(self, meeting_id: str) -> MeetingSession | None:
        """Deregister a session. Returns it, or ``None`` if it was not registered."""
        key = self._normalise_meeting_id(meeting_id)
        async with self._lock:
            session = self._sessions.pop(key, None)
            if session is not None:
                logger.info(
                    "Session deregistered",
                    extra={"meeting_id": key, "active_sessions": len(self._sessions)},
                )
            return session

    def get(self, meeting_id: str) -> MeetingSession | None:
        """Look up a session, or ``None``."""
        return self._sessions.get(self._normalise_meeting_id(meeting_id))

    def require(self, meeting_id: str) -> MeetingSession:
        """Look up a session.

        Raises:
            MeetingNotFoundError: If there is no session for this meeting.
        """
        key = self._normalise_meeting_id(meeting_id)
        session = self._sessions.get(key)
        if session is None:
            raise MeetingNotFoundError(key)
        return session

    def all(self) -> list[MeetingSession]:
        """Snapshot of every session, safe to iterate while sessions end."""
        return list(self._sessions.values())

    async def clear(self) -> list[MeetingSession]:
        """Deregister everything and return it. Used during shutdown."""
        async with self._lock:
            sessions = list(self._sessions.values())
            self._sessions.clear()
            return sessions
