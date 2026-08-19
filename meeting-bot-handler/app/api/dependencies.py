"""FastAPI dependency definitions.

Everything resolves from the container built during startup, so a request never
constructs infrastructure of its own.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

from app.application.bot_handler import BotHandler
from app.application.session_service import SessionService
from app.bootstrap import Container
from app.core.config import Settings
from app.kubernetes.pod_pool import BotPodPool


def get_container(request: Request) -> Container:
    return request.app.state.container


def get_bot_handler(container: Container = Depends(get_container)) -> BotHandler:
    return container.bot_handler


def get_session_service(container: Container = Depends(get_container)) -> SessionService:
    return container.session_service


def get_pod_pool(container: Container = Depends(get_container)) -> BotPodPool:
    return container.pod_pool


def get_settings_dep(container: Container = Depends(get_container)) -> Settings:
    return container.settings


ContainerDep = Annotated[Container, Depends(get_container)]
BotHandlerDep = Annotated[BotHandler, Depends(get_bot_handler)]
SessionServiceDep = Annotated[SessionService, Depends(get_session_service)]
PodPoolDep = Annotated[BotPodPool, Depends(get_pod_pool)]
SettingsDep = Annotated[Settings, Depends(get_settings_dep)]
