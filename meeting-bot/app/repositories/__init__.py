"""Durable meeting state.

Separate from :mod:`app.runtime`, which holds in-process status. These records
answer questions about a *meeting* and are expected to outlive the pod that
served it.

Persistence is optional by design: :func:`create_state_repository` returns Redis
when it is configured and reachable, and an in-memory store otherwise. No
caller branches on which one it got.
"""

from __future__ import annotations

import logging

from app.core.config import RedisSettings
from app.repositories.base import (
    MeetingLifecycleEvent,
    MeetingStateRecord,
    MeetingStateRepository,
)
from app.repositories.memory_repository import InMemoryStateRepository
from app.repositories.redis_repository import RedisStateRepository

logger = logging.getLogger(__name__)


async def create_state_repository(settings: RedisSettings) -> MeetingStateRepository:
    """Build the best available state repository.

    Falls back to in-memory when Redis is disabled or unreachable, so a Redis
    outage degrades observability rather than stopping meetings.
    """
    if not settings.enabled:
        logger.info("Meeting-state persistence disabled; using in-memory store")
        return InMemoryStateRepository()

    repository = RedisStateRepository(settings)
    if await repository.connect():
        return repository

    logger.warning("Falling back to in-memory meeting-state store")
    return InMemoryStateRepository()


__all__ = [
    "InMemoryStateRepository",
    "MeetingLifecycleEvent",
    "MeetingStateRecord",
    "MeetingStateRepository",
    "RedisStateRepository",
    "create_state_repository",
]
