"""Liveness and readiness probes.

``/health`` answers "is this process up?" and touches nothing external —
failing it restarts the pod.

``/ready`` answers "can this handler dispatch meetings?". Unlike the bot's
readiness, capacity is not part of it: the handler is a control plane and
multiplexes many sessions. What it does check is the thing that actually stops
dispatch working — whether the Kubernetes API is reachable and bot pods can be
found.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Response, status

from app.api.dependencies import ContainerDep
from app.schemas.status import DependencyStatus, HealthResponse, ReadinessResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse, summary="Liveness probe")
async def health(container: ContainerDep) -> HealthResponse:
    return HealthResponse(
        status="ok",
        service=container.settings.app_name,
        environment=container.settings.environment,
    )


@router.get("/ready", response_model=ReadinessResponse, summary="Readiness probe")
async def ready(response: Response, container: ContainerDep) -> ReadinessResponse:
    settings = container.settings
    dependencies: list[DependencyStatus] = []

    kubernetes_ok = container.kubernetes.available
    dependencies.append(
        DependencyStatus(
            name="kubernetes",
            healthy=kubernetes_ok,
            detail=None if kubernetes_ok else (container.kubernetes.load_error or "disabled"),
        )
    )

    pods_ok = False
    if kubernetes_ok:
        try:
            pods = await container.pod_pool.list_pods()
        except Exception as exc:  # noqa: BLE001 - any failure means "cannot dispatch"
            dependencies.append(
                DependencyStatus(name="bot_pods", healthy=False, detail=str(exc))
            )
        else:
            pods_ok = bool(pods)
            dependencies.append(
                DependencyStatus(
                    name="bot_pods",
                    healthy=pods_ok,
                    detail=f"{len(pods)} pod(s) matching {settings.bot_label_selector}",
                )
            )

    # A statically configured bot service is a complete substitute for
    # discovery: it is how the handler runs outside a cluster.
    static_ok = bool(settings.bot_service_url)
    if static_ok:
        dependencies.append(
            DependencyStatus(
                name="static_bot_service", healthy=True, detail=settings.bot_service_url
            )
        )

    is_ready = pods_ok or static_ok
    if not is_ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return ReadinessResponse(ready=is_ready, dependencies=dependencies)
