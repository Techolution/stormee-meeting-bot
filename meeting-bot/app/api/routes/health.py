"""Health and readiness probes.

Two endpoints answering two different questions, because Kubernetes uses them
for two different purposes:

  ``/health``  Liveness — is the process alive? Cheap, dependency-free, and
               always true while the event loop runs. Failing this restarts the
               pod, so it must never depend on anything external.

  ``/ready``   Readiness — can this pod take work? Reports whether dependencies
               are reachable. Failing this removes the pod from load balancing
               without killing an in-progress meeting.
"""

from __future__ import annotations

from fastapi import APIRouter, Response, status

from app.api.dependencies import ManagerDep, SettingsDep, StateRepositoryDep
from app.core.version import SERVICE_NAME, VERSION
from app.schemas.status import DependencyStatus, HealthResponse, ReadinessResponse

router = APIRouter(tags=["Health"])


@router.get("/health", response_model=HealthResponse, summary="Liveness probe")
async def health(settings: SettingsDep) -> HealthResponse:
    """Report that the process is running. Touches no dependency."""
    return HealthResponse(
        status="ok",
        service=SERVICE_NAME,
        version=VERSION,
        environment=settings.app.environment,
    )


@router.get("/ready", response_model=ReadinessResponse, summary="Readiness probe")
async def ready(
    response: Response,
    settings: SettingsDep,
    manager: ManagerDep,
    repository: StateRepositoryDep,
) -> ReadinessResponse:
    """Report whether this pod can accept a new meeting.

    A pod already running a meeting is *not* ready for another one, which is
    what keeps a dispatcher from sending two meetings to the same bot.
    """
    dependencies = [
        DependencyStatus(
            name="state_repository",
            healthy=repository.is_available,
            detail=None if repository.is_available else "using in-memory fallback",
        ),
        DependencyStatus(
            name="cw_utils",
            healthy=settings.cw_utils.enabled,
            detail=None if settings.cw_utils.enabled else "not configured",
        ),
        DependencyStatus(
            name="audio_service",
            healthy=settings.websocket.enabled,
            detail=None if settings.websocket.enabled else "not configured; direct upload will be used",
        ),
    ]

    # Only the ability to record is disqualifying: without either an audio
    # service or a CW backend there is nowhere for audio to go.
    can_store_audio = settings.websocket.enabled or settings.cw_utils.enabled
    is_ready = can_store_audio and manager.active_session_count == 0

    if not is_ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        if not can_store_audio:
            dependencies.append(
                DependencyStatus(
                    name="audio_storage",
                    healthy=False,
                    detail="neither an audio service nor CW is configured",
                )
            )
        else:
            dependencies.append(
                DependencyStatus(
                    name="capacity",
                    healthy=False,
                    detail=f"{manager.active_session_count} session(s) in progress",
                )
            )

    return ReadinessResponse(ready=is_ready, dependencies=dependencies)
