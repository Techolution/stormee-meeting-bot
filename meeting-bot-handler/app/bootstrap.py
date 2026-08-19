"""Application dependency wiring.

Everything with a lifetime is constructed once, here, and torn down in reverse:
one HTTP client shared by every outbound call, one Kubernetes client, one
session store. Building these per request leaked a connection pool per call and
lost session state between them.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

import httpx

from app.application.bot_client import BotClient
from app.application.bot_handler import BotHandler
from app.application.bot_service_resolver import BotServiceResolver
from app.application.session_service import SessionService
from app.core.config import Settings, get_settings
from app.kubernetes.client import KubernetesClient
from app.kubernetes.pod_pool import BotPodPool
from app.repositories.in_memory_session_repository import InMemorySessionRepository
from app.repositories.session_repository import SessionRepository

logger = logging.getLogger(__name__)


@dataclass
class Container:
    """The application's long-lived objects."""

    settings: Settings
    http_client: httpx.AsyncClient
    kubernetes: KubernetesClient
    pod_pool: BotPodPool
    repository: SessionRepository
    session_service: SessionService
    resolver: BotServiceResolver
    bot_handler: BotHandler

    async def aclose(self) -> None:
        await self.bot_handler.aclose()
        await self.http_client.aclose()


def create_container(
    settings: Optional[Settings] = None,
    repository: Optional[SessionRepository] = None,
) -> Container:
    settings = settings or get_settings()

    http_client = httpx.AsyncClient(timeout=settings.bot_request_timeout_seconds)

    kubernetes = KubernetesClient(
        namespace=settings.bot_namespace,
        kubeconfig=settings.kubeconfig,
        enabled=settings.kubernetes_enabled,
    )
    pod_pool = BotPodPool(kubernetes=kubernetes, http_client=http_client, settings=settings)

    if not kubernetes.available:
        logger.warning(
            "Bot pod discovery is off (%s). Sessions will be dispatched to "
            "BOT_SERVICE_URL=%s",
            kubernetes.load_error or "kubernetes disabled",
            settings.bot_service_url or "<unset>",
        )

    repository = repository or InMemorySessionRepository()
    session_service = SessionService(repository)
    resolver = BotServiceResolver(
        pod_pool=pod_pool, static_service_url=settings.bot_service_url
    )

    bot_handler = BotHandler(
        session_service=session_service,
        bot_resolver=resolver,
        http_client=http_client,
        settings=settings,
    )

    return Container(
        settings=settings,
        http_client=http_client,
        kubernetes=kubernetes,
        pod_pool=pod_pool,
        repository=repository,
        session_service=session_service,
        resolver=resolver,
        bot_handler=bot_handler,
    )


def create_bot_client(
    service_url: Optional[str] = None,
    http_client: Optional[httpx.AsyncClient] = None,
) -> BotClient:
    """Create a BotClient bound to one pod. Used by tooling and tests."""
    settings = get_settings()
    return BotClient(
        service_url=service_url or settings.bot_service_url,
        http_client=http_client,
        api_prefix=settings.bot_api_prefix,
        timeout=settings.bot_request_timeout_seconds,
    )
