"""Concurrency primitives for bot session operations.

Two commands for the same session must not interleave: ``start_recording``
twice would leave a second recording running unrecorded, and ``leave`` racing
``start_recording`` would record into a meeting the bot has left.

This is a per-process lock. It is enough today, where one handler replica owns
dispatch, and is the seam to replace with a database-level lock
(``SELECT ... FOR UPDATE``) when the handler scales out — the call sites do not
change.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import AsyncIterator, Dict


class KeyedLock:
    """One lock per key, created on first use."""

    def __init__(self) -> None:
        self._locks: Dict[str, asyncio.Lock] = {}
        self._guard = asyncio.Lock()

    async def _lock_for(self, key: str) -> asyncio.Lock:
        async with self._guard:
            lock = self._locks.get(key)
            if lock is None:
                lock = asyncio.Lock()
                self._locks[key] = lock
            return lock

    @asynccontextmanager
    async def acquire(self, key: str) -> AsyncIterator[None]:
        lock = await self._lock_for(key)
        async with lock:
            yield

    def release_key(self, key: str) -> None:
        """Forget a key once its session is finished, so the map stays bounded."""
        lock = self._locks.get(key)
        if lock is not None and not lock.locked():
            self._locks.pop(key, None)
