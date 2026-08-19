"""Cluster visibility.

Answers the question you ask first when a dispatch fails: can this handler see
the bot pods at all, and is any of them free?
"""

from __future__ import annotations

import logging

from fastapi import APIRouter

from app.api.dependencies import ContainerDep
from app.schemas.status import BotPodListResponse, BotPodView

logger = logging.getLogger(__name__)

router = APIRouter(tags=["cluster"])


@router.get("/bot-pods", response_model=BotPodListResponse, summary="List discovered bot pods")
async def list_bot_pods(container: ContainerDep, probe: bool = True) -> BotPodListResponse:
    """Every bot pod the handler can reach, and whether each can take a meeting.

    ``probe=false`` skips the readiness fan-out and reports discovery only.
    """
    settings = container.settings

    if not container.pod_pool.available:
        return BotPodListResponse(
            namespace=settings.bot_namespace,
            label_selector=settings.bot_label_selector,
            discovery_available=False,
            detail=container.kubernetes.load_error or "Kubernetes discovery is disabled",
            total=0,
            free=0,
            pods=[],
        )

    try:
        pods = await (
            container.pod_pool.candidates() if probe else container.pod_pool.list_pods()
        )
    except Exception as exc:  # noqa: BLE001 - report, do not fail the endpoint
        logger.error("Pod discovery failed: %s", exc)
        return BotPodListResponse(
            namespace=settings.bot_namespace,
            label_selector=settings.bot_label_selector,
            discovery_available=False,
            detail=str(exc),
            total=0,
            free=0,
            pods=[],
        )

    return BotPodListResponse(
        namespace=settings.bot_namespace,
        label_selector=settings.bot_label_selector,
        discovery_available=True,
        total=len(pods),
        free=sum(1 for pod in pods if pod.ready),
        pods=[BotPodView(**pod.as_dict()) for pod in pods],
    )
