"""Shared response primitives and base model configuration."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class CamelCaseModel(BaseModel):
    """Base for API models exposed over HTTP.

    Accepts both the camelCase alias and the snake_case field name on input, and
    serialises with aliases so responses match the documented contract.
    """

    model_config = ConfigDict(
        populate_by_name=True,
        serialize_by_alias=True,
        str_strip_whitespace=True,
    )


class ErrorResponse(CamelCaseModel):
    """Uniform error envelope returned by every failing endpoint.

    A stable ``code`` lets clients branch on the failure type without parsing
    prose; ``requestId`` ties the response to server logs.
    """

    code: str = Field(..., description="Stable machine-readable error identifier.")
    message: str = Field(..., description="Human-readable explanation.")
    details: dict[str, Any] | None = Field(default=None)
    request_id: str | None = Field(default=None, alias="requestId")


class MessageResponse(CamelCaseModel):
    """Simple acknowledgement."""

    message: str
