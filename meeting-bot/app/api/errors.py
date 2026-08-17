"""Error translation for the HTTP layer.

One place turns exceptions into responses. Route handlers therefore contain no
``try``/``except`` at all: they call the manager, and a domain exception becomes
the right status code with the right body on its own.

Every error response has the same shape — ``code``, ``message``, optional
``details``, and the ``requestId`` that ties it to server logs.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.core.exceptions import MeetingBotError
from app.core.request_context import get_context
from app.schemas.common import ErrorResponse

logger = logging.getLogger(__name__)

#: Spelled numerically rather than via ``fastapi.status``: Starlette renamed the
#: 422 constant, and the number is stable across both.
_STATUS_UNPROCESSABLE = 422
_STATUS_INTERNAL_ERROR = 500


def _envelope(
    *,
    code: str,
    message: str,
    details: dict | None = None,
    status_code: int,
) -> JSONResponse:
    """Build an error response from :class:`ErrorResponse`.

    Built through the model rather than as a hand-rolled dict so that the schema
    published in the OpenAPI document is the shape clients actually receive.
    """
    envelope = ErrorResponse(
        code=code,
        message=message,
        details=details or None,
        request_id=get_context().request_id or None,
    )
    return JSONResponse(
        status_code=status_code,
        # Aliases give camelCase (`requestId`); empty fields are dropped so a
        # simple error stays a two-key object.
        content=envelope.model_dump(by_alias=True, exclude_none=True),
    )


def register_exception_handlers(app: FastAPI) -> None:
    """Install handlers for domain, validation and unexpected errors."""

    @app.exception_handler(MeetingBotError)
    async def _handle_domain_error(_request: Request, error: MeetingBotError) -> JSONResponse:
        # Client mistakes are not incidents; server-side failures are.
        log = logger.warning if error.status_code < 500 else logger.error
        log(
            "Request failed",
            extra={"error_code": error.code, "status": error.status_code, "detail": error.message},
        )
        return _envelope(
            code=error.code,
            message=error.message,
            details=error.details,
            status_code=error.status_code,
        )

    @app.exception_handler(RequestValidationError)
    async def _handle_validation_error(
        _request: Request, error: RequestValidationError
    ) -> JSONResponse:
        fields = [
            {
                "field": ".".join(str(part) for part in item.get("loc", ()) if part != "body"),
                "problem": item.get("msg", ""),
            }
            for item in error.errors()
        ]
        logger.warning("Request validation failed", extra={"fields": fields})
        return _envelope(
            code="validation_error",
            message="The request body or parameters are invalid.",
            details={"fields": fields},
            status_code=_STATUS_UNPROCESSABLE,
        )

    @app.exception_handler(Exception)
    async def _handle_unexpected_error(_request: Request, error: Exception) -> JSONResponse:
        # Full traceback to the log; nothing internal to the client.
        logger.exception("Unhandled error", exc_info=error)
        return _envelope(
            code="internal_error",
            message="An unexpected error occurred.",
            status_code=_STATUS_INTERNAL_ERROR,
        )
