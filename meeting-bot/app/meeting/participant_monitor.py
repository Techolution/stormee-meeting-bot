"""Participant monitoring and self-eviction.

A bot left alone in an abandoned meeting will sit there until something kills
the pod. This watches the headcount and leaves when everyone else has gone.

The grace period is the whole design. A momentary drop to one participant is
routine — a reconnect, a tile that has not rendered — so leaving immediately
would abandon live meetings. The monitor requires the count to *stay* at one
for the full period before acting.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

from app.core.tasks import TaskSupervisor
from app.meeting_platform.base import MeetingPlatform

logger = logging.getLogger(__name__)

#: Called with (previous_count, new_count) whenever the headcount changes.
CountChangeHandler = Callable[[int, int], Awaitable[None]]

#: Called when the bot has been alone for the full grace period.
AloneHandler = Callable[[], Awaitable[None]]

_MONITOR_TASK = "participants"


class ParticipantMonitor:
    """Tracks the headcount and reports when the bot is left alone."""

    def __init__(
        self,
        *,
        platform: MeetingPlatform,
        meeting_id: str,
        poll_interval_seconds: float = 2.0,
        solo_grace_period_seconds: int = 120,
        auto_leave_when_alone: bool = True,
    ) -> None:
        self._platform = platform
        self._meeting_id = meeting_id
        self._poll_interval = poll_interval_seconds
        self._grace_period = solo_grace_period_seconds
        self._auto_leave = auto_leave_when_alone

        self._tasks = TaskSupervisor(f"participants:{meeting_id}")
        self._count = 0
        self._on_change: CountChangeHandler | None = None
        self._on_alone: AloneHandler | None = None
        self._alone_since: float | None = None

    # ------------------------------------------------------------------
    # State
    # ------------------------------------------------------------------

    @property
    def count(self) -> int:
        """Most recently observed headcount, including the bot."""
        return self._count

    @property
    def is_running(self) -> bool:
        return self._tasks.is_running(_MONITOR_TASK)

    def on_count_change(self, handler: CountChangeHandler) -> None:
        self._on_change = handler

    def on_alone(self, handler: AloneHandler) -> None:
        self._on_alone = handler

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Take an initial reading and begin monitoring."""
        if self.is_running:
            return

        if not self._platform.capabilities.supports_participant_list:
            logger.info(
                "Participant monitoring unavailable on this platform",
                extra={"meeting_id": self._meeting_id},
            )
            return

        self._count = len(await self._platform.get_participants())
        self._tasks.spawn(_MONITOR_TASK, self._loop())
        logger.info(
            "Participant monitoring started",
            extra={"meeting_id": self._meeting_id, "participant_count": self._count},
        )

    async def stop(self) -> None:
        await self._tasks.cancel_all()

    async def refresh(self) -> int:
        """Read the headcount now, outside the poll cycle."""
        self._count = len(await self._platform.get_participants())
        return self._count

    # ------------------------------------------------------------------
    # Monitoring
    # ------------------------------------------------------------------

    async def _loop(self) -> None:
        """Track the headcount until cancelled.

        Called by: nothing. Spawned as a background task by :meth:`start` — see
        docs/ENTRY_POINTS.md §5. This is one of three paths that can end a
        meeting, via the ``on_alone`` callback.
        """
        loop = asyncio.get_running_loop()

        while True:
            await asyncio.sleep(self._poll_interval)

            try:
                current = len(await self._platform.get_participants())
            except asyncio.CancelledError:
                raise
            except Exception as error:  # noqa: BLE001 - a failed read is not a change
                logger.debug(
                    "Participant poll failed",
                    extra={"meeting_id": self._meeting_id, "reason": str(error)},
                )
                continue

            # A zero reading means the tiles have not rendered, not that the
            # meeting is empty — the bot itself is always present.
            if current == 0:
                continue

            if current != self._count:
                previous, self._count = self._count, current
                logger.debug(
                    "Participant count changed",
                    extra={
                        "meeting_id": self._meeting_id,
                        "previous_count": previous,
                        "participant_count": current,
                    },
                )
                if self._on_change is not None:
                    await self._safely_notify(previous, current)

            if current > 1:
                if self._alone_since is not None:
                    logger.info(
                        "No longer alone in the meeting",
                        extra={"meeting_id": self._meeting_id, "participant_count": current},
                    )
                    self._alone_since = None
                continue

            # Alone. Start or continue the grace period.
            now = loop.time()
            if self._alone_since is None:
                self._alone_since = now
                logger.info(
                    "Bot is alone in the meeting; starting grace period",
                    extra={"meeting_id": self._meeting_id, "grace_period_seconds": self._grace_period},
                )
                continue

            if now - self._alone_since < self._grace_period:
                continue

            logger.info(
                "Grace period elapsed while alone",
                extra={"meeting_id": self._meeting_id, "waited_seconds": round(now - self._alone_since)},
            )
            if self._auto_leave and self._on_alone is not None:
                await self._on_alone()
            return

    async def _safely_notify(self, previous: int, current: int) -> None:
        assert self._on_change is not None
        try:
            await self._on_change(previous, current)
        except Exception as error:
            logger.error("Participant change handler failed", exc_info=error)
