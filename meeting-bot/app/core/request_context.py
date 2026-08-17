"""Ambient correlation context for logs and outbound calls.

A single bot pod handles one meeting at a time in practice, but background
tasks, chat commands and HTTP requests all interleave. Threading identifiers
through every call signature would be noise, so they live in ``contextvars``:
async-safe, task-local, and automatically inherited by tasks created inside a
context.

Both the log formatter and the HTTP clients read from here, which is what makes
every log line and every outbound request traceable to the meeting that caused
it.
"""

from __future__ import annotations

import contextvars
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from typing import Any


@dataclass(frozen=True, slots=True)
class CorrelationContext:
    """Identifiers attached to everything happening on the current task."""

    request_id: str = ""
    meeting_id: str = ""
    session_id: str = ""
    request_path: str = ""
    started_at: float = 0.0

    def as_log_fields(self) -> dict[str, str]:
        return {
            "request_id": self.request_id,
            "meeting_id": self.meeting_id,
            "session_id": self.session_id,
            "request_path": self.request_path,
        }

    @property
    def elapsed_ms(self) -> float:
        if not self.started_at:
            return 0.0
        return (time.perf_counter() - self.started_at) * 1000


_EMPTY = CorrelationContext()

_context: contextvars.ContextVar[CorrelationContext] = contextvars.ContextVar(
    "correlation_context", default=_EMPTY
)


def new_request_id() -> str:
    return str(uuid.uuid4())


def get_context() -> CorrelationContext:
    """Return the context for the current task, never ``None``."""
    return _context.get()


def set_context(context: CorrelationContext) -> contextvars.Token:
    """Replace the whole context. Prefer :func:`bind` unless you own the scope."""
    return _context.set(context)


def reset_context(token: contextvars.Token) -> None:
    _context.reset(token)


@contextmanager
def bind(**fields: Any) -> Iterator[CorrelationContext]:
    """Layer additional identifiers onto the current context for a scope.

    Fields left unset are inherited, so a background task started inside a
    request keeps that request's ``request_id`` while adding its own
    ``session_id``.

        with bind(meeting_id=meeting_id, session_id=session.id):
            await session.start()
    """
    current = _context.get()
    known = {key: value for key, value in fields.items() if value is not None}
    updated = replace(current, **known)
    if not updated.request_id:
        updated = replace(updated, request_id=new_request_id())
    if not updated.started_at:
        updated = replace(updated, started_at=time.perf_counter())
    token = _context.set(updated)
    try:
        yield updated
    finally:
        _context.reset(token)


def start_request(
    request_path: str,
    *,
    request_id: str | None = None,
    meeting_id: str = "",
) -> contextvars.Token:
    """Open a fresh context for an inbound HTTP request.

    Returns a token the caller must pass to :func:`reset_context` when the
    request completes.
    """
    return _context.set(
        CorrelationContext(
            request_id=request_id or new_request_id(),
            meeting_id=meeting_id,
            request_path=request_path,
            started_at=time.perf_counter(),
        )
    )
