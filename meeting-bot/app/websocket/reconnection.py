"""Reconnection policy.

Isolated from the connection machinery so the backoff schedule can be reasoned
about and tested without a socket. The policy is pure: it knows how long to
wait and when to give up, and nothing about how a connection is made.
"""

from __future__ import annotations

import logging
import random
from enum import Enum

logger = logging.getLogger(__name__)


class ErrorKind(str, Enum):
    """Whether retrying could plausibly help."""

    #: Network blips, timeouts, a service restarting. Retry.
    TRANSIENT = "transient"

    #: Bad URL, rejected handshake, authentication failure. Retrying repeats
    #: the same failure and delays the operator noticing.
    PERMANENT = "permanent"


class ReconnectionPolicy:
    """Exponential backoff with jitter and an attempt ceiling.

    Jitter matters at scale: without it, every bot pod that lost the audio
    service reconnects on the same schedule and lands as a synchronised burst
    the moment it comes back.
    """

    def __init__(
        self,
        *,
        initial_delay_ms: int = 1_000,
        backoff_factor: float = 2.0,
        max_delay_ms: int = 30_000,
        max_attempts: int = 5,
        jitter_ratio: float = 0.2,
    ) -> None:
        if initial_delay_ms <= 0:
            raise ValueError("initial_delay_ms must be positive")
        if backoff_factor < 1.0:
            raise ValueError("backoff_factor must be at least 1.0")
        if not 0.0 <= jitter_ratio < 1.0:
            raise ValueError("jitter_ratio must be in [0.0, 1.0)")

        self._initial_delay_ms = initial_delay_ms
        self._backoff_factor = backoff_factor
        self._max_delay_ms = max_delay_ms
        self._max_attempts = max_attempts
        self._jitter_ratio = jitter_ratio

        self._attempts = 0

    @property
    def attempts(self) -> int:
        """Attempts recorded since the last :meth:`reset`."""
        return self._attempts

    @property
    def max_attempts(self) -> int:
        return self._max_attempts

    @property
    def is_exhausted(self) -> bool:
        return self._attempts >= self._max_attempts

    def record_attempt(self) -> None:
        """Count one failed attempt, lengthening the next delay."""
        self._attempts += 1

    def reset(self) -> None:
        """Forget past failures. Call after a successful connection."""
        if self._attempts:
            logger.debug("Reconnection policy reset", extra={"previous_attempts": self._attempts})
        self._attempts = 0

    def should_retry(self, kind: ErrorKind = ErrorKind.TRANSIENT) -> bool:
        """Whether another attempt is warranted."""
        if kind is ErrorKind.PERMANENT:
            logger.warning(
                "Not retrying after a permanent error",
                extra={"attempts": self._attempts},
            )
            return False
        if self.is_exhausted:
            logger.error(
                "Reconnection attempts exhausted",
                extra={"attempts": self._attempts, "max_attempts": self._max_attempts},
            )
            return False
        return True

    def next_delay_seconds(self) -> float:
        """Delay before the next attempt, in seconds.

        Grows as ``initial * factor ** attempts``, capped at ``max_delay_ms``,
        then jittered by up to ``jitter_ratio`` in either direction.
        """
        raw_ms = self._initial_delay_ms * (self._backoff_factor**self._attempts)
        capped_ms = min(raw_ms, self._max_delay_ms)

        if self._jitter_ratio:
            spread = capped_ms * self._jitter_ratio
            capped_ms = max(0.0, capped_ms + random.uniform(-spread, spread))

        return capped_ms / 1000.0


def classify_error(error: BaseException) -> ErrorKind:
    """Guess whether an error is worth retrying.

    Deliberately conservative: anything not recognised as permanent is treated
    as transient, because giving up on a recoverable failure loses a meeting
    while a wasted retry costs a few seconds.
    """
    text = str(error).lower()
    permanent_markers = (
        "invalid url",
        "unauthorized",
        "forbidden",
        "authentication",
        "not a valid",
        "unsupported protocol",
        "name or service not known",
    )
    if any(marker in text for marker in permanent_markers):
        return ErrorKind.PERMANENT
    return ErrorKind.TRANSIENT
