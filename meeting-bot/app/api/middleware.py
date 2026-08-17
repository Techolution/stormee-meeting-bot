"""HTTP middleware.

Establishes the correlation context for every request so that all logging
emitted while handling it — including from background work started during it —
carries the same ``request_id``, and echoes that id back on the response for
support to quote.
"""

from __future__ import annotations

import logging

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.core.request_context import get_context, new_request_id, reset_context, start_request

logger = logging.getLogger(__name__)

#: Honoured on the way in so a caller's trace id survives the hop.
REQUEST_ID_HEADER = "X-Request-ID"

#: Paths excluded from access logging. Probes run every few seconds and drown
#: everything else out.
_QUIET_PATHS = frozenset({"/health", "/healthz", "/ready", "/readyz"})


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Binds a correlation context around each request and logs the outcome."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = request.headers.get(REQUEST_ID_HEADER) or new_request_id()

        # The meeting id is the most useful correlation key this service has, so
        # pick it up from the path when the route carries one. Body parameters
        # are not read here: consuming the stream in middleware would break the
        # handler that needs it.
        meeting_id = request.path_params.get("meeting_id", "") if request.path_params else ""

        token = start_request(request.url.path, request_id=request_id, meeting_id=str(meeting_id))
        try:
            response = await call_next(request)
        except Exception:
            logger.exception(
                "Request raised",
                extra={"method": request.method, "path": request.url.path},
            )
            raise
        finally:
            context = get_context()
            duration_ms = round(context.elapsed_ms, 1)
            reset_context(token)

        response.headers[REQUEST_ID_HEADER] = request_id

        if not _is_quiet(request.url.path):
            logger.info(
                "Request completed",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "status": response.status_code,
                    "duration_ms": duration_ms,
                    "request_id": request_id,
                },
            )

        return response


def _is_quiet(path: str) -> bool:
    return any(path.endswith(quiet) for quiet in _QUIET_PATHS)
