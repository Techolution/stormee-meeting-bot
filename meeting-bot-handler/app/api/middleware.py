"""Application middleware."""

from __future__ import annotations

import logging
import time

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.core.context import new_request_id, set_request_id, set_session_id

logger = logging.getLogger(__name__)

REQUEST_ID_HEADER = "X-Request-ID"


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Honour and echo ``X-Request-ID``.

    The id is put in a context variable, which is what makes it travel: the bot
    client reads it from there and sends it on, so one id covers the handler's
    logs and the pod's.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = request.headers.get(REQUEST_ID_HEADER) or new_request_id()
        set_request_id(request_id)
        set_session_id(request.path_params.get("session_id", "") if request.path_params else "")

        started = time.monotonic()
        response = await call_next(request)
        elapsed_ms = (time.monotonic() - started) * 1000

        response.headers[REQUEST_ID_HEADER] = request_id
        logger.info(
            "%s %s -> %d (%.0fms)",
            request.method,
            request.url.path,
            response.status_code,
            elapsed_ms,
        )
        return response
