"""HTTP interface.

The only layer that knows about FastAPI. It translates HTTP into calls on
:class:`~app.meeting.meeting_manager.MeetingManager` and domain errors back into
status codes — and does nothing else.
"""

from app.api.errors import register_exception_handlers
from app.api.middleware import RequestContextMiddleware
from app.api.routes import api_router

__all__ = ["RequestContextMiddleware", "api_router", "register_exception_handlers"]
