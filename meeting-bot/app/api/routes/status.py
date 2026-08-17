"""Status and meeting-state endpoints.

Two kinds of state are exposed, and they are deliberately separate:

  ``/status``                          runtime — what this pod is doing now
  ``/meetings/{id}/state``, ``/state/history``  durable — what happened to a meeting

The first dies with the pod. The second is what remains afterwards. See
:mod:`app.runtime.state` for why conflating them causes trouble.
"""

from __future__ import annotations

import time

from fastapi import APIRouter, Query

from app.api.dependencies import ManagerDep, SettingsDep, StateRepositoryDep
from app.core.exceptions import MeetingNotFoundError
from app.core.version import SERVICE_NAME, VERSION
from app.schemas.common import MessageResponse
from app.schemas.meeting import MeetingStateHistoryResponse, MeetingStateResponse

router = APIRouter(tags=["Status"])

_STARTED_AT = time.monotonic()


@router.get("/status", summary="Runtime status of this pod")
async def service_status(settings: SettingsDep, manager: ManagerDep) -> dict:
    """Everything this process is currently doing.

    Reads in-memory state only, so it is safe to poll frequently.
    """
    return {
        "service": SERVICE_NAME,
        "version": VERSION,
        "environment": settings.app.environment,
        "uptimeSeconds": round(time.monotonic() - _STARTED_AT, 1),
        "activeSessions": manager.active_session_count,
        "sessions": manager.all_status(),
        "configuration": settings.describe(),
    }


@router.get("/meetings/{meeting_id}/status", summary="Runtime status of one session")
async def session_status(meeting_id: str, manager: ManagerDep) -> dict:
    """Live status for a single meeting session.

    Raises:
        MeetingNotFoundError: If this pod has no session for the meeting.
    """
    return manager.session_status(meeting_id)


@router.get(
    "/meetings/{meeting_id}/state",
    response_model=MeetingStateResponse,
    summary="Latest persisted meeting state",
)
async def meeting_state(
    meeting_id: str,
    repository: StateRepositoryDep,
) -> MeetingStateResponse:
    """The most recent recorded transition for a meeting.

    Available after the session has ended, and from any pod sharing the store.

    Raises:
        MeetingNotFoundError: If nothing is recorded for this meeting.
    """
    record = await repository.current(meeting_id)
    if record is None:
        raise MeetingNotFoundError(meeting_id)
    return MeetingStateResponse(meeting_id=meeting_id, state=record.as_dict())


@router.get(
    "/meetings/{meeting_id}/state/history",
    response_model=MeetingStateHistoryResponse,
    summary="Persisted meeting state history",
)
async def meeting_state_history(
    meeting_id: str,
    repository: StateRepositoryDep,
    limit: int = Query(default=100, ge=1, le=1000),
) -> MeetingStateHistoryResponse:
    """Recorded transitions for a meeting, newest first."""
    records = await repository.history(meeting_id, limit=limit)
    entries = [record.as_dict() for record in records]
    return MeetingStateHistoryResponse(
        meeting_id=meeting_id, history=entries, count=len(entries)
    )


@router.delete(
    "/meetings/{meeting_id}/state",
    response_model=MessageResponse,
    summary="Delete persisted meeting state",
)
async def delete_meeting_state(
    meeting_id: str,
    repository: StateRepositoryDep,
) -> MessageResponse:
    """Remove a meeting's recorded history."""
    deleted = await repository.delete(meeting_id)
    return MessageResponse(
        message=f"State deleted for meeting {meeting_id}"
        if deleted
        else f"No stored state for meeting {meeting_id}"
    )
