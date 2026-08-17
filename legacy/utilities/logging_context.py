"""Request-scoped logging context management using contextvars.

This module provides a RequestContext class that manages request-scoped logging
context via Python's contextvars module, enabling automatic inclusion of request
identifiers and metadata in all log entries generated within a request lifecycle.
"""

import contextvars
from typing import Any


class RequestContext:
    """Manages request-scoped logging context using context variables.

    This class provides static methods to set and retrieve request-scoped context
    including request_id, timer, meetingId, and request_url. Context variables are
    async-safe and do not leak across concurrent requests.
    """

    # Define context variables for each field
    _request_id: contextvars.ContextVar[str] = contextvars.ContextVar(
        'request_id', default=''
    )
    _timer: contextvars.ContextVar[Any] = contextvars.ContextVar(
        'timer', default=''
    )
    _meeting_id: contextvars.ContextVar[str] = contextvars.ContextVar(
        'meetingId', default=''
    )
    _request_url: contextvars.ContextVar[str] = contextvars.ContextVar(
        'request_url', default=''
    )

    @staticmethod
    def set_context(
        request_id: str,
        timer: float,
        meetingId: str,
        request_url: str
    ) -> None:
        """Set all four context variables for the current request.

        Args:
            request_id: Unique identifier for the request.
            timer: Request execution start time (timestamp).
            meetingId: ID of the meeting associated with the request.
            request_url: Full URL of the HTTP request.
        """
        RequestContext._request_id.set(request_id)
        RequestContext._timer.set(timer)
        RequestContext._meeting_id.set(meetingId)
        RequestContext._request_url.set(request_url)

    @staticmethod
    def get_context() -> dict[str, Any]:
        """Retrieve all context variables as a dictionary.

        Returns:
            Dictionary containing all four context fields. Missing or unset
            context variables are replaced with empty strings.

        Raises:
            No exceptions are raised; missing values default to empty strings.
        """
        return {
            'request_id': RequestContext._request_id.get(),
            'timer': RequestContext._timer.get(),
            'meetingId': RequestContext._meeting_id.get(),
            'request_url': RequestContext._request_url.get(),
        }

