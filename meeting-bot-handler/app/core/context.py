"""Per-request correlation context.

The bot API honours and echoes ``X-Request-ID``. Carrying the inbound id in a
context variable means every downstream call the handler makes on behalf of a
request lands in the worker's logs under the same id, so one grep spans both
services.
"""

from __future__ import annotations

import uuid
from contextvars import ContextVar

_request_id: ContextVar[str] = ContextVar("request_id", default="")
_session_id: ContextVar[str] = ContextVar("session_id", default="")


def new_request_id() -> str:
    return uuid.uuid4().hex


def get_request_id() -> str:
    return _request_id.get()


def set_request_id(request_id: str) -> None:
    _request_id.set(request_id)


def get_session_id() -> str:
    return _session_id.get()


def set_session_id(session_id: str) -> None:
    _session_id.set(session_id)
