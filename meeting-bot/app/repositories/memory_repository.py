"""In-memory meeting-state store.

The default when Redis is not configured or not reachable. History is lost on
restart, which is acceptable for local development and for deployments where
the upstream Meeting API is the real system of record.

Having a working implementation here — rather than a disabled flag checked at
every call site — is what keeps the "is persistence enabled?" question out of
the rest of the codebase.
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict, deque
from typing import Any

from app.repositories.base import (
    MeetingLifecycleEvent,
    MeetingStateRecord,
    MeetingStateRepository,
)

logger = logging.getLogger(__name__)


class InMemoryStateRepository(MeetingStateRepository):
    """Bounded per-meeting history held in the process."""

    def __init__(self, *, history_limit: int = 500) -> None:
        self._history: dict[str, deque[MeetingStateRecord]] = defaultdict(
            lambda: deque(maxlen=history_limit)
        )
        self._lock = asyncio.Lock()

    @property
    def is_available(self) -> bool:
        return True

    async def record(
        self,
        meeting_id: str,
        event: MeetingLifecycleEvent,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        record = MeetingStateRecord(event=event, metadata=metadata or {})
        async with self._lock:
            self._history[meeting_id].append(record)

        logger.debug(
            "Meeting state recorded",
            extra={"meeting_id": meeting_id, "event": event.value, "store": "memory"},
        )
        return True

    async def current(self, meeting_id: str) -> MeetingStateRecord | None:
        async with self._lock:
            entries = self._history.get(meeting_id)
            return entries[-1] if entries else None

    async def history(self, meeting_id: str, *, limit: int = 100) -> list[MeetingStateRecord]:
        async with self._lock:
            entries = list(self._history.get(meeting_id, ()))
        return list(reversed(entries))[:limit]

    async def delete(self, meeting_id: str) -> bool:
        async with self._lock:
            existed = self._history.pop(meeting_id, None) is not None
        return existed
