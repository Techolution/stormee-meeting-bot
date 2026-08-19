"""HTTP error handling.

One envelope for every failure, matching the shape the bot API uses so a client
sees the same structure whichever service failed:

    {"code": "...", "message": "...", "details": {...}, "requestId": "..."}

Callers branch on ``code``. The status code is derived from the exception type,
and for failures that originated in the bot pod the bot's own code is forwarded
unchanged rather than flattened into a 500.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.context import get_request_id
from app.domain.exceptions import (
    BotOperationError,
    BotServiceNotAssignedError,
    BotServiceUnavailableError,
    ClusterUnavailableError,
    DomainException,
    InvalidSessionStateError,
    NoBotPodAvailableError,
    SessionAlreadyExistsError,
    SessionNotFoundError,
)

logger = logging.getLogger(__name__)

_STATUS_BY_EXCEPTION = {
    SessionNotFoundError: status.HTTP_404_NOT_FOUND,
    SessionAlreadyExistsError: status.HTTP_409_CONFLICT,
    InvalidSessionStateError: status.HTTP_409_CONFLICT,
    BotServiceNotAssignedError: status.HTTP_409_CONFLICT,
    NoBotPodAvailableError: status.HTTP_503_SERVICE_UNAVAILABLE,
    BotServiceUnavailableError: status.HTTP_502_BAD_GATEWAY,
    ClusterUnavailableError: status.HTTP_503_SERVICE_UNAVAILABLE,
}


def error_response(
    status_code: int,
    code: str,
    message: str,
    details: Optional[Dict[str, Any]] = None,
    request_id: Optional[str] = None,
) -> JSONResponse:
    body: Dict[str, Any] = {"code": code, "message": message}
    if details:
        body["details"] = details
    body["requestId"] = request_id or get_request_id() or None
    return JSONResponse(status_code=status_code, content=body)


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(BotOperationError)
    async def _bot_operation_error(_: Request, exc: BotOperationError) -> JSONResponse:
        # The bot already classified this. Forward its code and status; a 5xx
        # from the bot is a bad gateway from here.
        upstream = exc.status_code
        outbound = upstream if upstream < 500 else status.HTTP_502_BAD_GATEWAY
        return error_response(
            outbound,
            exc.code,
            exc.message,
            {**exc.details, "botRequestId": exc.request_id} if exc.request_id else exc.details,
        )

    @app.exception_handler(DomainException)
    async def _domain_error(_: Request, exc: DomainException) -> JSONResponse:
        status_code = _STATUS_BY_EXCEPTION.get(type(exc), status.HTTP_400_BAD_REQUEST)
        if status_code >= 500:
            logger.error("%s: %s", exc.code, exc.message)
        else:
            logger.info("%s: %s", exc.code, exc.message)
        return error_response(status_code, exc.code, exc.message, exc.details)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        fields = [
            {"field": ".".join(str(p) for p in err.get("loc", [])), "error": err.get("msg", "")}
            for err in exc.errors()
        ]
        return error_response(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "validation_error",
            "Request validation failed",
            {"fields": fields},
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        return error_response(
            exc.status_code,
            "http_error" if exc.status_code < 500 else "internal_error",
            str(exc.detail),
        )

    @app.exception_handler(Exception)
    async def _unexpected_error(_: Request, exc: Exception) -> JSONResponse:
        # Nothing internal is exposed; the request id is how support finds it.
        logger.exception("Unhandled error: %s", exc)
        return error_response(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "internal_error",
            "An unexpected error occurred",
        )
