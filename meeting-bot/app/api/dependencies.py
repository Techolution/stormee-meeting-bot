"""FastAPI dependency providers.

Long-lived objects — the manager, the settings, the state repository — are
created once during application startup (see :mod:`app.bootstrap`) and stored
on ``app.state``. These providers hand them to route handlers.

Routes depend on these rather than importing a module-level singleton, so a
test can override a single dependency and exercise a route against fakes.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

from app.core.config import Settings
from app.core.exceptions import ConfigurationError
from app.core.request_context import bind_meeting_id
from app.meeting.meeting_manager import MeetingManager
from app.repositories.base import MeetingStateRepository


async def correlate_meeting(request: Request) -> None:
    """Attach the request's meeting id to the logging context.

    Applied to every route, so each log line produced while handling a request
    carries the meeting it concerns — including the middleware's completion
    line, which runs after the handler.

    The id lives in the path for some routes and in the body for others. Reading
    the body here is safe: FastAPI caches it on the request, so the handler's own
    model parsing still sees it. Doing the same thing in middleware would consume
    the stream before the handler could read it.
    """
    meeting_id = str(request.path_params.get("meeting_id") or "")

    if not meeting_id and request.method in {"POST", "PUT", "PATCH"}:
        try:
            payload = await request.json()
        except Exception:  # noqa: BLE001 - a malformed body is the handler's problem to report
            return
        if isinstance(payload, dict):
            # meetingUrl is the fallback the previous implementation used, for
            # the join request that names the meeting before it has an id.
            meeting_id = str(
                payload.get("meetingId") or payload.get("meeting_id") or payload.get("meetingUrl") or ""
            )

    if meeting_id:
        bind_meeting_id(meeting_id)
        # Also stashed on the ASGI scope: Starlette runs the handler in a
        # separate context, so a contextvar set here never reaches the
        # middleware that logs the request's completion.
        request.state.meeting_id = meeting_id


def get_settings_dep(request: Request) -> Settings:
    """The process configuration."""
    settings = getattr(request.app.state, "settings", None)
    if not isinstance(settings, Settings):  # pragma: no cover - indicates a wiring bug
        raise ConfigurationError("settings are not attached to the application state")
    return settings


def get_meeting_manager(request: Request) -> MeetingManager:
    """The meeting manager.

    Raises:
        ConfigurationError: If startup did not complete. Surfaces as a 500 with
            a clear message rather than an ``AttributeError``.
    """
    manager = getattr(request.app.state, "meeting_manager", None)
    if not isinstance(manager, MeetingManager):  # pragma: no cover - indicates a wiring bug
        raise ConfigurationError("meeting manager is not available; application startup failed")
    return manager


def get_state_repository(request: Request) -> MeetingStateRepository:
    """The durable meeting-state store."""
    repository = getattr(request.app.state, "state_repository", None)
    if not isinstance(repository, MeetingStateRepository):  # pragma: no cover - wiring bug
        raise ConfigurationError("state repository is not available; application startup failed")
    return repository


SettingsDep = Annotated[Settings, Depends(get_settings_dep)]
ManagerDep = Annotated[MeetingManager, Depends(get_meeting_manager)]
StateRepositoryDep = Annotated[MeetingStateRepository, Depends(get_state_repository)]
