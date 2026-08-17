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
from app.meeting.meeting_manager import MeetingManager
from app.repositories.base import MeetingStateRepository


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
