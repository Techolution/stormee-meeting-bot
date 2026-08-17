"""Tests for the context buffer."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.context.buffer import InMemoryContextBuffer
from app.context.models import ContextItem, ContextQuery

pytestmark = pytest.mark.asyncio


def item(content: str, *, kind: str = "transcript", minutes_ago: int = 0) -> ContextItem:
    return ContextItem(
        kind=kind,
        content=content,
        created_at=datetime.now(timezone.utc) - timedelta(minutes=minutes_ago),
    )


async def test_items_are_returned_in_arrival_order() -> None:
    buffer = InMemoryContextBuffer()

    await buffer.append(item("first"))
    await buffer.extend([item("second"), item("third")])

    assert [entry.content for entry in await buffer.recent()] == ["first", "second", "third"]
    assert await buffer.size() == 3


async def test_limit_returns_the_most_recent_in_chronological_order() -> None:
    """The useful shape for building a prompt: newest content, still in order."""
    buffer = InMemoryContextBuffer()
    for index in range(5):
        await buffer.append(item(f"item-{index}"))

    recent = await buffer.recent(ContextQuery(limit=2))

    assert [entry.content for entry in recent] == ["item-3", "item-4"]


async def test_cap_discards_oldest_rather_than_growing_without_bound() -> None:
    """A long meeting must not slowly consume the pod's memory."""
    buffer = InMemoryContextBuffer(max_items=3)

    for index in range(6):
        await buffer.append(item(f"item-{index}"))

    contents = [entry.content for entry in await buffer.recent()]
    assert contents == ["item-3", "item-4", "item-5"]
    assert buffer.evicted_count == 3


async def test_filtering_by_kind() -> None:
    buffer = InMemoryContextBuffer()
    await buffer.append(item("spoken", kind="transcript"))
    await buffer.append(item("typed", kind="chat"))

    results = await buffer.recent(ContextQuery(kind="chat"))

    assert [entry.content for entry in results] == ["typed"]


async def test_filtering_by_time() -> None:
    buffer = InMemoryContextBuffer()
    await buffer.append(item("old", minutes_ago=10))
    await buffer.append(item("new", minutes_ago=0))

    cutoff = datetime.now(timezone.utc) - timedelta(minutes=5)
    results = await buffer.recent(ContextQuery(since=cutoff))

    assert [entry.content for entry in results] == ["new"]


async def test_clear_resets_everything() -> None:
    buffer = InMemoryContextBuffer()
    await buffer.append(item("something"))

    await buffer.clear()

    assert await buffer.size() == 0
    assert buffer.evicted_count == 0


async def test_invalid_capacity_is_rejected() -> None:
    with pytest.raises(ValueError):
        InMemoryContextBuffer(max_items=0)
