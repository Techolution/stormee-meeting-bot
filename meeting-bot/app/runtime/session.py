"""Session registry.

Tracks the sessions this process is running, keyed by session id. Small on
purpose: it holds references and enforces uniqueness, and knows nothing about
what a session does.

Uniqueness is enforced rather than tolerated. The previous implementation
returned the existing bot when asked to join a meeting twice, which quietly
turned a duplicate request into a success and left the caller believing a fresh
join had happened.

Rejoining the same room creates a new session ID. Exact duplicate active
session IDs are rejected rather than silently rewritten.
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
        # Ids handed out by reserve_meeting_id but not yet registered. A session
        # cannot be constructed until its id is settled (MeetingRequest is
        # frozen), so there is a window between choosing a key and adding the
        # session; without this, two concurrent joins could be handed the same
        # "free" key and the second would fail on add.
        self._reserved: set[str] = set()
        self._max_sessions = max_sessions
        self._lock = asyncio.Lock()

    def __len__(self) -> int:
        return len(self._sessions)

    def __contains__(self, session_id: object) -> bool:
        return session_id in self._sessions

    def __iter__(self) -> Iterator[MeetingSession]:
        return iter(list(self._sessions.values()))

    @property
    def meeting_ids(self) -> list[str]:
        """Backward-compatible name for the registered session ID list."""
        return sorted(self._sessions)

    @property
    def is_full(self) -> bool:
        return bool(self._max_sessions) and len(self._sessions) >= self._max_sessions

    def _is_taken(self, meeting_id: str) -> bool:
        """True when an id is registered or spoken for. Caller holds the lock."""
        return meeting_id in self._sessions or meeting_id in self._reserved

    async def reserve_session_id(self, desired: str) -> str:
        """Reserve an exact session id or reject a duplicate."""
        async with self._lock:
            if self._is_taken(desired):
                raise MeetingAlreadyActiveError(desired)
            self._reserved.add(desired)
            return desired

    async def release_session_id(self, session_id: str) -> None:
        """Give back a reservation that will never be registered.

        Only needed on the failure path between reserving and adding; a
        successful :meth:`add` consumes the reservation itself.
        """
        async with self._lock:
            self._reserved.discard(session_id)

    async def add(self, session: MeetingSession) -> None:
        """Register a session.

        Raises:
            MeetingAlreadyActiveError: If this meeting already has a session, or
                the process is at capacity.
        """
        async with self._lock:
            session_id = session.session_id
            if session_id in self._sessions:
                raise MeetingAlreadyActiveError(session_id)
            if self.is_full:
                raise MeetingAlreadyActiveError(
                    f"session limit reached ({self._max_sessions}); cannot start {session_id}"
                )

            self._reserved.discard(session_id)
            self._sessions[session_id] = session
            logger.info(
                "Session registered",
                extra={
                    "session_id": session.session_id,
                    "active_sessions": len(self._sessions),
                },
            )

    async def remove(self, session_id: str) -> MeetingSession | None:
        """Deregister a session. Returns it, or ``None`` if it was not registered."""
        async with self._lock:
            session = self._sessions.pop(session_id, None)
            if session is not None:
                logger.info(
                    "Session deregistered",
                    extra={"session_id": session_id, "active_sessions": len(self._sessions)},
                )
            return session

    def get(self, session_id: str) -> MeetingSession | None:
        """Look up a session, or ``None``."""
        return self._sessions.get(session_id)

    def require(self, meeting_id: str) -> MeetingSession:
        """Look up a session.

        Raises:
            MeetingNotFoundError: If there is no session for this meeting.
        """
        session = self._sessions.get(meeting_id)
        if session is None:
            raise MeetingNotFoundError(meeting_id)
        return session

    def all(self) -> list[MeetingSession]:
        """Snapshot of every session, safe to iterate while sessions end."""
        return list(self._sessions.values())

    async def clear(self) -> list[MeetingSession]:
        """Deregister everything and return it. Used during shutdown."""
        async with self._lock:
            sessions = list(self._sessions.values())
            self._sessions.clear()
            # A join still between reserving and adding is being cancelled too,
            # and its id would otherwise outlive the registry it belongs to.
            self._reserved.clear()
            return sessions
