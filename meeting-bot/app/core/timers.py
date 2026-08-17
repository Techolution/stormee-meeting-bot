"""Timing helpers.

Duration is the field that turns logs into something you can debug with, so
measuring it should cost one line. Everything here uses ``perf_counter`` — a
monotonic clock — so results stay correct across NTP adjustments.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from typing import Any, TypeVar

T = TypeVar("T")

_logger = logging.getLogger(__name__)


class Stopwatch:
    """Monotonic elapsed-time counter.

        watch = Stopwatch()
        ...
        logger.info("done", extra={"duration_ms": watch.elapsed_ms})
    """

    __slots__ = ("_start", "_stopped_at")

    def __init__(self) -> None:
        self._start = time.perf_counter()
        self._stopped_at: float | None = None

    def reset(self) -> None:
        self._start = time.perf_counter()
        self._stopped_at = None

    def stop(self) -> float:
        """Freeze the stopwatch and return the elapsed milliseconds."""
        if self._stopped_at is None:
            self._stopped_at = time.perf_counter()
        return self.elapsed_ms

    @property
    def elapsed_seconds(self) -> float:
        end = self._stopped_at if self._stopped_at is not None else time.perf_counter()
        return end - self._start

    @property
    def elapsed_ms(self) -> float:
        return round(self.elapsed_seconds * 1000, 2)


@contextmanager
def timed(
    operation: str,
    logger: logging.Logger | None = None,
    level: int = logging.DEBUG,
    **fields: Any,
) -> Iterator[Stopwatch]:
    """Log how long a block took, whether or not it raised.

        with timed("browser.launch", logger, meeting_id=meeting_id):
            await browser.launch()
    """
    log = logger or _logger
    watch = Stopwatch()
    try:
        yield watch
    except Exception:
        log.log(
            level if level > logging.DEBUG else logging.WARNING,
            "%s failed",
            operation,
            extra={"operation": operation, "duration_ms": watch.stop(), "outcome": "error", **fields},
        )
        raise
    else:
        log.log(
            level,
            "%s completed",
            operation,
            extra={"operation": operation, "duration_ms": watch.stop(), "outcome": "ok", **fields},
        )


async def wait_until(
    predicate: Callable[[], Awaitable[bool]],
    *,
    timeout_seconds: float,
    poll_interval_seconds: float = 1.0,
    on_poll: Callable[[float], None] | None = None,
) -> bool:
    """Poll ``predicate`` until it returns True or the timeout expires.

    This is the shape of nearly every "wait for the meeting UI to reach a
    state" loop in the codebase — lobby admission, participant tiles appearing,
    a control becoming clickable — so it lives here instead of being rewritten
    at each call site.

    Args:
        predicate: Async check. Exceptions propagate; guard inside if you want
            a flaky probe to count as "not yet".
        timeout_seconds: Total budget.
        poll_interval_seconds: Delay between checks.
        on_poll: Optional callback receiving seconds waited so far, for progress logs.

    Returns:
        True if the predicate succeeded within the budget, False on timeout.
    """
    deadline = time.perf_counter() + timeout_seconds
    while True:
        if await predicate():
            return True

        remaining = deadline - time.perf_counter()
        if remaining <= 0:
            return False

        if on_poll is not None:
            on_poll(timeout_seconds - max(remaining, 0.0))

        await asyncio.sleep(min(poll_interval_seconds, remaining))
