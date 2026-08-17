"""Tests for the reconnection policy."""

from __future__ import annotations

import pytest

from app.websocket.reconnection import ErrorKind, ReconnectionPolicy, classify_error


def test_delay_grows_exponentially() -> None:
    policy = ReconnectionPolicy(initial_delay_ms=1_000, backoff_factor=2.0, jitter_ratio=0.0)

    delays = []
    for _ in range(4):
        delays.append(policy.next_delay_seconds())
        policy.record_attempt()

    assert delays == [1.0, 2.0, 4.0, 8.0]


def test_delay_is_capped() -> None:
    policy = ReconnectionPolicy(
        initial_delay_ms=1_000, backoff_factor=10.0, max_delay_ms=5_000, jitter_ratio=0.0
    )

    for _ in range(5):
        policy.record_attempt()

    assert policy.next_delay_seconds() == 5.0


def test_jitter_spreads_delays_without_escaping_the_cap() -> None:
    """Jitter stops many pods reconnecting in a synchronised burst."""
    policy = ReconnectionPolicy(
        initial_delay_ms=1_000, backoff_factor=1.0, max_delay_ms=1_000, jitter_ratio=0.5
    )

    samples = {round(policy.next_delay_seconds(), 4) for _ in range(50)}

    assert len(samples) > 1, "jitter should produce varying delays"
    assert all(0.5 <= sample <= 1.5 for sample in samples)


def test_retries_stop_at_the_attempt_ceiling() -> None:
    policy = ReconnectionPolicy(max_attempts=3)

    for _ in range(3):
        assert policy.should_retry() is True
        policy.record_attempt()

    assert policy.should_retry() is False
    assert policy.is_exhausted is True


def test_permanent_errors_are_not_retried() -> None:
    """Retrying a bad URL repeats the same failure and hides it from the operator."""
    policy = ReconnectionPolicy(max_attempts=10)

    assert policy.should_retry(ErrorKind.PERMANENT) is False


def test_reset_clears_attempt_history() -> None:
    policy = ReconnectionPolicy(initial_delay_ms=1_000, jitter_ratio=0.0)
    for _ in range(3):
        policy.record_attempt()

    policy.reset()

    assert policy.attempts == 0
    assert policy.next_delay_seconds() == 1.0


@pytest.mark.parametrize(
    "message,expected",
    [
        ("connection reset by peer", ErrorKind.TRANSIENT),
        ("read timeout", ErrorKind.TRANSIENT),
        ("Invalid URL 'not-a-url'", ErrorKind.PERMANENT),
        ("401 Unauthorized", ErrorKind.PERMANENT),
        ("name or service not known", ErrorKind.PERMANENT),
        ("something nobody anticipated", ErrorKind.TRANSIENT),
    ],
)
def test_error_classification(message: str, expected: ErrorKind) -> None:
    """Unrecognised errors are treated as transient: a wasted retry beats a lost meeting."""
    assert classify_error(RuntimeError(message)) is expected


def test_invalid_configuration_is_rejected() -> None:
    with pytest.raises(ValueError):
        ReconnectionPolicy(initial_delay_ms=0)
    with pytest.raises(ValueError):
        ReconnectionPolicy(backoff_factor=0.5)
    with pytest.raises(ValueError):
        ReconnectionPolicy(jitter_ratio=1.0)
