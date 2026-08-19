"""Application logging configuration.

Every log line carries the request id and, where one is in scope, the session
id: tracing a meeting means following it across the handler and the bot pod,
and the ids are what stitch the two logs together.
"""

from __future__ import annotations

import logging
import sys

from app.core.context import get_request_id, get_session_id

_TEXT_FORMAT = "%(asctime)s %(levelname)-8s %(name)s [req=%(request_id)s session=%(session_id)s] %(message)s"


class _ContextFilter(logging.Filter):
    """Attach correlation ids so the formatter can always reference them."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = get_request_id() or "-"
        record.session_id = get_session_id() or "-"
        return True


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(_TEXT_FORMAT))
    handler.addFilter(_ContextFilter())

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())

    # uvicorn installs its own handlers; route them through ours so the
    # correlation ids appear on access logs too.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(name)
        logger.handlers = [handler]
        logger.propagate = False
