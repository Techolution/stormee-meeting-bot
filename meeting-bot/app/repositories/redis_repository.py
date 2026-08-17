"""Redis-backed meeting-state store.

Two keys per meeting:

  ``meeting:{id}:state``    the current transition, as JSON
  ``meeting:{id}:history``  a list of transitions, newest first

Both carry a TTL so a pod that dies mid-meeting cannot leak keys forever, and
the history list is trimmed on write so a long meeting cannot grow without
bound.

Redis calls are synchronous and therefore run in a worker thread. Blocking the
event loop on a network round trip would stall the caption poller and the audio
capture callback — the two things that must not stall.

Availability is rechecked rather than latched: the previous implementation
tested the connection once at construction and disabled itself permanently if
Redis happened to be starting up, so a bot launched during a rollout logged
nothing for its entire life.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

import redis
from redis.exceptions import RedisError

from app.core.config import RedisSettings
from app.repositories.base import (
    MeetingLifecycleEvent,
    MeetingStateRecord,
    MeetingStateRepository,
)

logger = logging.getLogger(__name__)

#: Wait this long after a failure before probing Redis again.
_RECHECK_INTERVAL_SECONDS = 30.0


class RedisStateRepository(MeetingStateRepository):
    """Meeting state persisted in Redis."""

    def __init__(self, settings: RedisSettings) -> None:
        self._settings = settings
        self._client: redis.Redis | None = None
        self._available = False
        self._next_recheck_at = 0.0
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    @property
    def is_available(self) -> bool:
        return self._available

    async def connect(self) -> bool:
        """Open the connection and verify it. Safe to call repeatedly.

        Returns:
            True if Redis is usable. False is not fatal — the caller falls back
            to in-memory state.
        """
        async with self._lock:
            return await self._ensure_connection()

    async def _ensure_connection(self) -> bool:
        """Connect if needed, honouring the recheck backoff."""
        if self._available and self._client is not None:
            return True

        if time.monotonic() < self._next_recheck_at:
            return False

        try:
            client = redis.Redis(
                host=self._settings.host,
                port=self._settings.port,
                db=self._settings.db,
                password=self._settings.password or None,
                decode_responses=True,
                socket_connect_timeout=self._settings.socket_timeout_seconds,
                socket_timeout=self._settings.socket_timeout_seconds,
                socket_keepalive=True,
                retry_on_timeout=True,
            )
            await asyncio.to_thread(client.ping)
        except (RedisError, OSError) as error:
            self._available = False
            self._client = None
            self._next_recheck_at = time.monotonic() + _RECHECK_INTERVAL_SECONDS
            logger.warning(
                "Redis unavailable; meeting state will not be persisted",
                extra={
                    "host": self._settings.host,
                    "port": self._settings.port,
                    "reason": str(error),
                    "retry_in_seconds": _RECHECK_INTERVAL_SECONDS,
                },
            )
            return False

        self._client = client
        self._available = True
        self._next_recheck_at = 0.0
        logger.info(
            "Connected to Redis",
            extra={
                "host": self._settings.host,
                "port": self._settings.port,
                "db": self._settings.db,
                "state_ttl_seconds": self._settings.state_ttl_seconds,
            },
        )
        return True

    def _mark_unavailable(self, error: Exception, operation: str) -> None:
        self._available = False
        self._next_recheck_at = time.monotonic() + _RECHECK_INTERVAL_SECONDS
        logger.warning(
            "Redis operation failed; marking store unavailable",
            extra={"operation": operation, "reason": str(error)},
        )

    # ------------------------------------------------------------------
    # Keys
    # ------------------------------------------------------------------

    @staticmethod
    def _state_key(meeting_id: str) -> str:
        return f"meeting:{meeting_id}:state"

    @staticmethod
    def _history_key(meeting_id: str) -> str:
        return f"meeting:{meeting_id}:history"

    # ------------------------------------------------------------------
    # Operations
    # ------------------------------------------------------------------

    async def record(
        self,
        meeting_id: str,
        event: MeetingLifecycleEvent,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        if not await self._ensure_connection() or self._client is None:
            return False

        record = MeetingStateRecord(event=event, metadata=metadata or {})
        payload = json.dumps(record.as_dict(), default=str)
        ttl = self._settings.state_ttl_seconds
        history_key = self._history_key(meeting_id)

        def _write() -> None:
            assert self._client is not None
            # One round trip: current state, history append, trim, and both TTLs.
            pipe = self._client.pipeline()
            pipe.setex(self._state_key(meeting_id), ttl, payload)
            pipe.lpush(history_key, payload)
            pipe.ltrim(history_key, 0, self._settings.history_max_entries - 1)
            pipe.expire(history_key, ttl)
            pipe.execute()

        try:
            await asyncio.to_thread(_write)
        except (RedisError, OSError) as error:
            self._mark_unavailable(error, "record")
            return False

        logger.debug(
            "Meeting state recorded",
            extra={"meeting_id": meeting_id, "event": event.value, "store": "redis"},
        )
        return True

    async def current(self, meeting_id: str) -> MeetingStateRecord | None:
        if not await self._ensure_connection() or self._client is None:
            return None

        try:
            raw = await asyncio.to_thread(self._client.get, self._state_key(meeting_id))
        except (RedisError, OSError) as error:
            self._mark_unavailable(error, "current")
            return None

        if not raw:
            return None
        return _decode(raw, meeting_id)

    async def history(self, meeting_id: str, *, limit: int = 100) -> list[MeetingStateRecord]:
        if not await self._ensure_connection() or self._client is None:
            return []

        try:
            entries = await asyncio.to_thread(
                self._client.lrange, self._history_key(meeting_id), 0, max(limit - 1, 0)
            )
        except (RedisError, OSError) as error:
            self._mark_unavailable(error, "history")
            return []

        records = [_decode(entry, meeting_id) for entry in entries or []]
        return [record for record in records if record is not None]

    async def delete(self, meeting_id: str) -> bool:
        if not await self._ensure_connection() or self._client is None:
            return False

        try:
            await asyncio.to_thread(
                self._client.delete, self._state_key(meeting_id), self._history_key(meeting_id)
            )
        except (RedisError, OSError) as error:
            self._mark_unavailable(error, "delete")
            return False

        logger.debug("Meeting state deleted", extra={"meeting_id": meeting_id})
        return True

    async def close(self) -> None:
        if self._client is None:
            return
        try:
            await asyncio.to_thread(self._client.close)
            logger.debug("Redis connection closed")
        except Exception as error:  # noqa: BLE001 - shutdown must not fail on this
            logger.debug("Error closing Redis connection", extra={"reason": str(error)})
        finally:
            self._client = None
            self._available = False


def _decode(raw: str | bytes, meeting_id: str) -> MeetingStateRecord | None:
    """Parse a stored record, tolerating anything unparseable."""
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError):
        logger.warning("Discarded unreadable state record", extra={"meeting_id": meeting_id})
        return None
    if not isinstance(payload, dict):
        return None
    return MeetingStateRecord.from_dict(payload)
