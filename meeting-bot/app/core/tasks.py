"""Supervised background tasks.

Bare ``asyncio.create_task`` has two failure modes this service hit repeatedly:
the task object gets garbage-collected mid-flight because nobody held a
reference, and an exception inside it disappears into a "Task exception was
never retrieved" warning nobody reads.

:class:`TaskSupervisor` owns its tasks, logs their failures, and cancels them
deterministically on shutdown. Every long-running loop in the application —
caption polling, chat polling, participant monitoring, connection supervision —
is created through one.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Coroutine
from typing import Any, TypeVar

T = TypeVar("T")

logger = logging.getLogger(__name__)


class TaskSupervisor:
    """Owns a named set of background tasks and shuts them down together."""

    def __init__(self, owner: str) -> None:
        self._owner = owner
        self._tasks: dict[str, asyncio.Task[Any]] = {}

    @property
    def names(self) -> list[str]:
        return sorted(self._tasks)

    def is_running(self, name: str) -> bool:
        task = self._tasks.get(name)
        return task is not None and not task.done()

    def spawn(self, name: str, coro: Coroutine[Any, Any, T]) -> asyncio.Task[T]:
        """Start ``coro`` under ``name``, replacing any finished task with that name.

        Raises:
            RuntimeError: If a task with this name is still running. Restarting a
                live loop is always a bug, so it fails loudly rather than
                leaking the original.
        """
        existing = self._tasks.get(name)
        if existing is not None and not existing.done():
            coro.close()
            raise RuntimeError(f"task {name!r} is already running for {self._owner}")

        task = asyncio.create_task(coro, name=f"{self._owner}:{name}")
        self._tasks[name] = task
        task.add_done_callback(self._on_task_done)
        logger.debug("Background task started", extra={"task": name, "owner": self._owner})
        return task

    def _on_task_done(self, task: asyncio.Task[Any]) -> None:
        name = (task.get_name() or "").split(":", 1)[-1]
        if task.cancelled():
            logger.debug("Background task cancelled", extra={"task": name, "owner": self._owner})
            return
        error = task.exception()
        if error is not None:
            logger.error(
                "Background task failed",
                exc_info=error,
                extra={"task": name, "owner": self._owner},
            )
        else:
            logger.debug("Background task finished", extra={"task": name, "owner": self._owner})

    async def cancel(self, name: str, *, timeout: float = 5.0) -> None:
        """Cancel one task and wait for it to unwind."""
        task = self._tasks.pop(name, None)
        if task is None or task.done():
            return
        task.cancel()
        await _await_cancelled(task, timeout=timeout, label=f"{self._owner}:{name}")

    async def cancel_all(self, *, timeout: float = 5.0) -> None:
        """Cancel every task and wait for all of them.

        Never raises: shutdown must not be derailed by a task that misbehaves
        on the way out.
        """
        tasks = list(self._tasks.items())
        self._tasks.clear()

        for _, task in tasks:
            if not task.done():
                task.cancel()

        for name, task in tasks:
            await _await_cancelled(task, timeout=timeout, label=f"{self._owner}:{name}")


async def _await_cancelled(task: asyncio.Task[Any], *, timeout: float, label: str) -> None:
    try:
        await asyncio.wait_for(asyncio.shield(task), timeout=timeout)
    except asyncio.CancelledError:
        pass
    except asyncio.TimeoutError:
        logger.warning("Task did not stop within timeout", extra={"task": label, "timeout": timeout})
    except Exception as error:  # noqa: BLE001 - the task already logged; do not mask shutdown
        logger.debug("Task raised while stopping: %s", error, extra={"task": label})


