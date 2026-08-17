"""Liveness heartbeat.

A bot pod can fail in a way that keeps the HTTP server answering: the browser
crashes, the page navigates away, the meeting ends without anyone telling us.
The process looks healthy and occupies a pod slot indefinitely.

The heartbeat closes that gap. It periodically asks the session whether it is
still genuinely in a meeting, refreshes the participant count, and hands the
answer to a callback that can end a stalled session.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

from app.core.tasks import TaskSupervisor
from app.runtime.state import RuntimeState

logger = logging.getLogger(__name__)

#: Returns True while the session is still viable.
LivenessProbe = Callable[[], Awaitable[bool]]

#: Invoked once when the probe reports the session is gone.
OnDeadCallback = Callable[[], Awaitable[None]]

_HEARTBEAT_TASK = "heartbeat"


class Heartbeat:
    """Periodically checks that a session is still alive."""

    def __init__(
        self,
        *,
        state: RuntimeState,
        probe: LivenessProbe,
        interval_seconds: float = 15.0,
        failure_threshold: int = 3,
        on_dead: OnDeadCallback | None = None,
    ) -> None:
        """
        Args:
            state: Runtime state to stamp on each beat.
            probe: Liveness check. Should be cheap and must not raise for a
                transient failure.
            interval_seconds: Delay between beats.
            failure_threshold: Consecutive failures before the session is
                declared dead. Greater than one because a single failed probe
                is usually a page mid-navigation, not a dead meeting.
            on_dead: Called once when the threshold is crossed.
        """
        self._state = state
        self._probe = probe
        self._interval = interval_seconds
        self._failure_threshold = failure_threshold
        self._on_dead = on_dead

        self._tasks = TaskSupervisor(f"heartbeat:{state.meeting_id}")
        self._consecutive_failures = 0

    @property
    def is_running(self) -> bool:
        return self._tasks.is_running(_HEARTBEAT_TASK)

    def start(self) -> None:
        """Begin beating. No-op if already running."""
        if self.is_running:
            return
        self._consecutive_failures = 0
        self._tasks.spawn(_HEARTBEAT_TASK, self._loop())
        logger.debug(
            "Heartbeat started",
            extra={"meeting_id": self._state.meeting_id, "interval_seconds": self._interval},
        )

    async def stop(self) -> None:
        """Stop beating."""
        await self._tasks.cancel_all()
        logger.debug("Heartbeat stopped", extra={"meeting_id": self._state.meeting_id})

    async def _loop(self) -> None:
        """Probe liveness on an interval until cancelled.

        Called by: nothing. Spawned as a background task by :meth:`start` — see
        docs/ENTRY_POINTS.md §5. On sustained failure this ends the session.
        """
        while True:
            await asyncio.sleep(self._interval)

            try:
                alive = await self._probe()
            except asyncio.CancelledError:
                raise
            except Exception as error:  # noqa: BLE001 - a failed probe counts as a miss
                alive = False
                logger.debug(
                    "Heartbeat probe raised",
                    extra={"meeting_id": self._state.meeting_id, "reason": str(error)},
                )

            if alive:
                self._state.beat()
                self._consecutive_failures = 0
                continue

            self._consecutive_failures += 1
            logger.warning(
                "Heartbeat probe reported the session is not alive",
                extra={
                    "meeting_id": self._state.meeting_id,
                    "consecutive_failures": self._consecutive_failures,
                    "threshold": self._failure_threshold,
                },
            )

            if self._consecutive_failures < self._failure_threshold:
                continue

            logger.error(
                "Session declared dead by heartbeat",
                extra={"meeting_id": self._state.meeting_id},
            )
            if self._on_dead is not None:
                await self._on_dead()
            return
