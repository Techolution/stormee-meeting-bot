"""Logging setup.

Two formatters share one contract: every record carries the correlation fields
from :mod:`app.core.request_context` plus any ``extra`` the call site supplied.
The text formatter is for humans reading a terminal; the JSON formatter is for
log aggregators. Choose with ``LOG_FORMAT``.

Call :func:`configure_logging` exactly once, at startup, before anything logs.
"""

from __future__ import annotations

import json
import logging
import sys
from collections.abc import Iterable, Mapping
from typing import Any

from app.core.request_context import get_context

#: Attributes present on every LogRecord. Anything else was passed as ``extra``
#: by the call site and is therefore structured data worth emitting.
#:
#: This is also the set of names ``extra`` may not use: stdlib logging raises
#: ``KeyError`` rather than shadowing a record attribute, so
#: ``extra={"filename": ...}`` crashes the call site. See :class:`SafeLogger`.
_STANDARD_RECORD_FIELDS = frozenset(
    {
        "args", "asctime", "created", "exc_info", "exc_text", "filename",
        "funcName", "levelname", "levelno", "lineno", "module", "msecs",
        "message", "msg", "name", "pathname", "process", "processName",
        "relativeCreated", "stack_info", "taskName", "thread", "threadName",
    }
)

#: Prefix applied to an ``extra`` key that would collide with a record attribute.
_COLLISION_PREFIX = "ctx_"

#: Third-party loggers that are noisy at DEBUG and rarely useful.
_NOISY_LOGGERS = {
    "asyncio": logging.INFO,
    "engineio.client": logging.WARNING,
    "hpack": logging.WARNING,
    "httpcore": logging.WARNING,
    "httpx": logging.WARNING,
    "socketio.client": logging.WARNING,
    "urllib3": logging.WARNING,
}


def _extra_fields(record: logging.LogRecord) -> dict[str, Any]:
    return {
        key: value
        for key, value in record.__dict__.items()
        if key not in _STANDARD_RECORD_FIELDS and not key.startswith("_")
    }


class SafeLogger(logging.Logger):
    """A logger whose ``extra`` cannot crash the call site.

    Stdlib logging refuses to let ``extra`` shadow a ``LogRecord`` attribute and
    raises ``KeyError`` when it would. That turns an innocuous field name —
    ``filename``, ``module``, ``name`` — into an exception thrown from a log
    statement, which is a poor way to discover the problem: the code path fails
    only when it logs, and often only in the branch nobody exercises.

    Colliding keys are renamed rather than dropped, so the value still reaches
    the log and the collision is visible in the output.
    """

    def makeRecord(  # noqa: N802 - overrides logging.Logger.makeRecord
        self,
        name: str,
        level: int,
        fn: str,
        lno: int,
        msg: object,
        args: Any,
        exc_info: Any,
        func: str | None = None,
        extra: Mapping[str, Any] | None = None,
        sinfo: str | None = None,
    ) -> logging.LogRecord:
        if extra:
            extra = {
                (f"{_COLLISION_PREFIX}{key}" if key in _STANDARD_RECORD_FIELDS else key): value
                for key, value in extra.items()
            }
        return super().makeRecord(name, level, fn, lno, msg, args, exc_info, func, extra, sinfo)


def _install_safe_logger_class(namespace: str = "app") -> None:
    """Make loggers under ``namespace`` collision-proof.

    New loggers get :class:`SafeLogger` from ``setLoggerClass``. Loggers created
    earlier — every module-level ``getLogger(__name__)``, which runs at import
    time and therefore before configuration — are retargeted in place. Scoped to
    our own namespace so third-party logging behaviour is untouched.
    """
    logging.setLoggerClass(SafeLogger)

    root = logging.getLogger(namespace)
    existing = [root, *(
        logger
        for name, logger in logging.Logger.manager.loggerDict.items()
        if name.startswith(f"{namespace}.") and isinstance(logger, logging.Logger)
    )]
    for logger in existing:
        logger.__class__ = SafeLogger


class ContextFilter(logging.Filter):
    """Copy the ambient correlation context onto each record."""

    def filter(self, record: logging.LogRecord) -> bool:
        for key, value in get_context().as_log_fields().items():
            # An explicit `extra` on the call site always wins.
            if not hasattr(record, key):
                setattr(record, key, value)
        return True


class TextFormatter(logging.Formatter):
    """Human-readable single line: timestamp, level, logger, message, key=value pairs."""

    default_time_format = "%Y-%m-%d %H:%M:%S"

    def format(self, record: logging.LogRecord) -> str:
        base = (
            f"{self.formatTime(record)} {record.levelname:<8} "
            f"{record.name} - {record.getMessage()}"
        )

        fields = _extra_fields(record)
        # Correlation identifiers lead; drop the empty ones so quiet lines stay quiet.
        ordered: list[str] = []
        for key in ("meeting_id", "session_id", "request_id", "request_path"):
            value = fields.pop(key, "")
            if value:
                ordered.append(f"{key}={value}")
        ordered.extend(f"{key}={value}" for key, value in sorted(fields.items()))

        if ordered:
            base = f"{base} [{' '.join(ordered)}]"

        if record.exc_info:
            base = f"{base}\n{self.formatException(record.exc_info)}"
        if record.stack_info:
            base = f"{base}\n{self.formatStack(record.stack_info)}"
        return base


class JSONFormatter(logging.Formatter):
    """One JSON object per line, for structured log ingestion."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        payload.update(_extra_fields(record))

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        if record.stack_info:
            payload["stack"] = self.formatStack(record.stack_info)

        return json.dumps(payload, default=str, ensure_ascii=False)


def configure_logging(
    level: str = "INFO",
    log_format: str = "text",
    *,
    stream: Any = None,
    quiet_loggers: Iterable[str] | None = None,
) -> None:
    """Install the root handler. Safe to call more than once — handlers are replaced.

    Args:
        level: Root log level name, e.g. ``"DEBUG"``.
        log_format: ``"text"`` or ``"json"``.
        stream: Destination stream. Defaults to stderr.
        quiet_loggers: Extra logger names to pin at WARNING.
    """
    resolved = getattr(logging, level.upper(), None)
    if not isinstance(resolved, int):
        raise ValueError(f"invalid log level: {level!r}")

    _install_safe_logger_class()

    handler = logging.StreamHandler(stream or sys.stderr)
    handler.setFormatter(JSONFormatter() if log_format == "json" else TextFormatter())
    handler.addFilter(ContextFilter())

    root = logging.getLogger()
    for existing in list(root.handlers):
        root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(resolved)

    for name, noisy_level in _NOISY_LOGGERS.items():
        logging.getLogger(name).setLevel(max(noisy_level, resolved))
    for name in quiet_loggers or ():
        logging.getLogger(name).setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """Module logger. Use ``get_logger(__name__)``."""
    return logging.getLogger(name)
