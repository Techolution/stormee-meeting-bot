"""Accumulated meeting context.

Everything the bot learns during a meeting — transcript today, more later —
lands here. The interface is deliberately small (``append``, ``recent``,
``clear``) so the storage behind it can change without callers noticing.

Today that storage is an in-process deque. A Redis-backed implementation
becomes necessary the moment context must outlive the pod or be shared with
another service, and it slots in behind the same interface.
"""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from collections import deque

from app.context.models import ContextItem, ContextQuery

logger = logging.getLogger(__name__)


class ContextBuffer(ABC):
    """Ordered store of meeting context."""

    @abstractmethod
    async def append(self, item: ContextItem) -> None:
        """Add one item."""

    @abstractmethod
    async def extend(self, items: list[ContextItem]) -> None:
        """Add several items, preserving order."""

    @abstractmethod
    async def recent(self, query: ContextQuery | None = None) -> list[ContextItem]:
        """Read items back, oldest first.

        With a ``limit``, returns the *most recent* N in chronological order —
        the useful shape for building a prompt or rendering a tail.
        """

    @abstractmethod
    async def clear(self) -> None:
        """Discard everything."""

    @abstractmethod
    async def size(self) -> int:
        """Number of items currently held."""


class InMemoryContextBuffer(ContextBuffer):
    """Bounded in-process buffer.

    The bound matters: a long meeting produces a caption segment every second
    or so, and an unbounded list is a slow memory leak in a pod that may live
    for hours. When the cap is reached the oldest items are discarded, which is
    correct for context — recency is what has value.
    """

    def __init__(self, *, max_items: int = 5_000) -> None:
        if max_items <= 0:
            raise ValueError("max_items must be positive")
        self._items: deque[ContextItem] = deque(maxlen=max_items)
        self._max_items = max_items
        self._lock = asyncio.Lock()
        self._evicted = 0

    async def append(self, item: ContextItem) -> None:
        async with self._lock:
            self._note_eviction(1)
            self._items.append(item)

    async def extend(self, items: list[ContextItem]) -> None:
        if not items:
            return
        async with self._lock:
            self._note_eviction(len(items))
            self._items.extend(items)

    def _note_eviction(self, incoming: int) -> None:
        """Log the first eviction so silent context loss is visible."""
        overflow = len(self._items) + incoming - self._max_items
        if overflow <= 0:
            return
        if self._evicted == 0:
            logger.warning(
                "Context buffer is full; oldest items are being discarded",
                extra={"max_items": self._max_items},
            )
        self._evicted += overflow

    async def recent(self, query: ContextQuery | None = None) -> list[ContextItem]:
        async with self._lock:
            items = list(self._items)

        if query is None:
            return items

        filtered = [item for item in items if query.matches(item)]
        if query.limit is not None and query.limit < len(filtered):
            return filtered[-query.limit :]
        return filtered

    async def clear(self) -> None:
        async with self._lock:
            self._items.clear()
            self._evicted = 0

    async def size(self) -> int:
        async with self._lock:
            return len(self._items)

    @property
    def evicted_count(self) -> int:
        """Items dropped to stay within the cap."""
        return self._evicted
