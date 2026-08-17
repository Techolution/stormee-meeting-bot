"""HTTP routes.

One module per resource. Every handler is thin: validate, call the manager,
shape the response. Business logic lives in :mod:`app.meeting`; error
translation lives in :mod:`app.api.errors`.
"""

from fastapi import APIRouter

from app.api.routes import health, meeting, recording, status, transcription
from app.schemas.common import ErrorResponse

#: Error responses every meeting-scoped route can return, declared once so the
#: published OpenAPI schema matches what :mod:`app.api.errors` actually sends.
#: Without this the error envelope would be undocumented, and clients would have
#: to discover its shape by causing failures.
_ERROR_RESPONSES: dict[int | str, dict] = {
    404: {"model": ErrorResponse, "description": "No session or record for that meeting."},
    409: {"model": ErrorResponse, "description": "Conflicts with the current state."},
    422: {"model": ErrorResponse, "description": "The request is malformed."},
    500: {"model": ErrorResponse, "description": "Unexpected server-side failure."},
    502: {"model": ErrorResponse, "description": "A dependency or the meeting platform failed."},
}

#: Everything the service exposes, mounted under the configured API prefix.
api_router = APIRouter()

# Probes are excluded: they take no input and address no meeting, so declaring
# 404/409 on them would document failures they cannot produce.
api_router.include_router(health.router)

for resource in (status, meeting, recording, transcription):
    api_router.include_router(resource.router, responses=_ERROR_RESPONSES)

__all__ = ["api_router"]
