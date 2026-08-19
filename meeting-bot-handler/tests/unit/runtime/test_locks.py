"""Per-session serialization."""

from __future__ import annotations

import asyncio

from app.runtime.locks import KeyedLock


async def test_operations_on_one_session_do_not_interleave():
    lock = KeyedLock()
    order: list[str] = []

    async def operation(name: str) -> None:
        async with lock.acquire("sess-1"):
            order.append(f"{name}:enter")
            await asyncio.sleep(0.01)
            order.append(f"{name}:exit")

    await asyncio.gather(operation("a"), operation("b"))

    assert order in (
        ["a:enter", "a:exit", "b:enter", "b:exit"],
        ["b:enter", "b:exit", "a:enter", "a:exit"],
    )


async def test_different_sessions_run_concurrently():
    lock = KeyedLock()
    running = 0
    peak = 0

    async def operation(key: str) -> None:
        nonlocal running, peak
        async with lock.acquire(key):
            running += 1
            peak = max(peak, running)
            await asyncio.sleep(0.01)
            running -= 1

    await asyncio.gather(operation("sess-1"), operation("sess-2"))

    assert peak == 2


async def test_a_released_key_is_forgotten():
    lock = KeyedLock()
    async with lock.acquire("sess-1"):
        pass

    lock.release_key("sess-1")

    assert "sess-1" not in lock._locks
