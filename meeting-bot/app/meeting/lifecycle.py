"""Ordered startup and shutdown.

Shutdown order is not arbitrary. Stopping the browser before flushing audio
loses the recording; leaving the meeting before stopping the recorder produces
a trailing chunk with nothing to receive it. The correct order is a property of
the system, so it is declared as data in one place rather than implied by the
order of statements in a long method.

The two directions have different rules, and that difference is the reason this
module exists:

  **Startup** stops at the first critical failure. Continuing past a browser
  that would not launch just produces a longer, more confusing traceback.

  **Shutdown** never stops. Every step runs even if earlier ones failed, and
  every step is bounded by a timeout, because a hung leave-call must not
  prevent the browser from being released — a leaked Chromium process outlives
  the meeting and eventually the pod.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

logger = logging.getLogger(__name__)

StepAction = Callable[[], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class LifecycleStep:
    """One phase of bringing a session up or taking it down."""

    name: str
    action: StepAction

    #: Startup only. A failed critical step aborts the remaining startup.
    critical: bool = True

    #: Upper bound on the step. Shutdown steps must always have one.
    timeout_seconds: float = 30.0


@dataclass(frozen=True, slots=True)
class StepResult:
    """What happened to one step."""

    name: str
    succeeded: bool
    duration_ms: float
    error: str | None = None


class LifecycleRunner:
    """Executes lifecycle steps under the rules described above."""

    def __init__(self, *, meeting_id: str) -> None:
        self._meeting_id = meeting_id

    async def start(self, steps: list[LifecycleStep]) -> list[StepResult]:
        """Run startup steps in order, stopping at the first critical failure.

        Raises:
            Exception: Whatever the failing critical step raised, so the caller
                sees the real cause rather than a wrapper.
        """
        results: list[StepResult] = []

        for step in steps:
            result = await self._run(step, phase="start")
            results.append(result)

            if result.succeeded:
                continue

            if step.critical:
                logger.error(
                    "Startup aborted at a critical step",
                    extra={"meeting_id": self._meeting_id, "step": step.name, "reason": result.error},
                )
                raise _StepFailedError(step.name, result.error or "unknown error")

            logger.warning(
                "Optional startup step failed; continuing",
                extra={"meeting_id": self._meeting_id, "step": step.name, "reason": result.error},
            )

        return results

    async def shutdown(self, steps: list[LifecycleStep]) -> list[StepResult]:
        """Run every shutdown step, in order, regardless of failures.

        Never raises. Shutdown is the last chance to release resources; an
        exception here would strand whatever comes after it.
        """
        results: list[StepResult] = []

        for step in steps:
            result = await self._run(step, phase="shutdown")
            results.append(result)
            if not result.succeeded:
                logger.warning(
                    "Shutdown step failed; continuing",
                    extra={"meeting_id": self._meeting_id, "step": step.name, "reason": result.error},
                )

        failed = [result.name for result in results if not result.succeeded]
        logger.info(
            "Session shutdown complete",
            extra={
                "meeting_id": self._meeting_id,
                "steps": len(results),
                "failed_steps": failed or None,
            },
        )
        return results

    async def _run(self, step: LifecycleStep, *, phase: str) -> StepResult:
        loop = asyncio.get_running_loop()
        started = loop.time()

        try:
            await asyncio.wait_for(step.action(), timeout=step.timeout_seconds)
        except asyncio.TimeoutError:
            return StepResult(
                name=step.name,
                succeeded=False,
                duration_ms=(loop.time() - started) * 1000,
                error=f"timed out after {step.timeout_seconds}s",
            )
        except asyncio.CancelledError:
            raise
        except Exception as error:
            logger.debug(
                "Lifecycle step raised",
                exc_info=error,
                extra={"meeting_id": self._meeting_id, "step": step.name, "phase": phase},
            )
            return StepResult(
                name=step.name,
                succeeded=False,
                duration_ms=(loop.time() - started) * 1000,
                error=str(error),
            )

        duration_ms = (loop.time() - started) * 1000
        logger.debug(
            "Lifecycle step completed",
            extra={
                "meeting_id": self._meeting_id,
                "step": step.name,
                "phase": phase,
                "duration_ms": round(duration_ms, 1),
            },
        )
        return StepResult(name=step.name, succeeded=True, duration_ms=duration_ms)


class _StepFailedError(RuntimeError):
    """Raised when a critical startup step fails."""

    def __init__(self, step: str, reason: str) -> None:
        super().__init__(f"startup step {step!r} failed: {reason}")
        self.step = step
        self.reason = reason
