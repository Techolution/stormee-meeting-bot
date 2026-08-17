"""Tests for logging setup.

The reserved-field test exists because this failed in practice: stdlib logging
raises ``KeyError`` when ``extra`` would shadow a ``LogRecord`` attribute, so
``extra={"filename": ...}`` throws from the log statement itself. It surfaced on
the recording-completion path, where a crash is expensive and rarely exercised.
"""

from __future__ import annotations

import io
import json
import logging

import pytest

from app.core.logging import configure_logging, get_logger
from app.core.request_context import bind


@pytest.fixture
def captured() -> io.StringIO:
    stream = io.StringIO()
    configure_logging(level="DEBUG", log_format="text", stream=stream)
    return stream


@pytest.fixture
def captured_json() -> io.StringIO:
    stream = io.StringIO()
    configure_logging(level="DEBUG", log_format="json", stream=stream)
    return stream


def test_extra_fields_appear_in_text_output(captured: io.StringIO) -> None:
    get_logger("app.test").info("something happened", extra={"chunk_id": "c-1", "size": 42})

    output = captured.getvalue()
    assert "something happened" in output
    assert "chunk_id=c-1" in output
    assert "size=42" in output


def test_reserved_field_names_do_not_raise(captured: io.StringIO) -> None:
    """The regression: these names all collide with LogRecord attributes."""
    logger = get_logger("app.test")

    for reserved in ("filename", "module", "name", "message", "args", "process", "lineno"):
        logger.info("upload finished", extra={reserved: "value"})  # must not raise

    output = captured.getvalue()
    assert output.count("upload finished") == 7
    # Renamed rather than dropped, so the value still reaches the log.
    assert "ctx_filename=value" in output


def test_reserved_field_value_survives_in_json(captured_json: io.StringIO) -> None:
    get_logger("app.test").info("stored", extra={"filename": "recording.webm"})

    payload = json.loads(captured_json.getvalue().strip())
    assert payload["ctx_filename"] == "recording.webm"
    assert payload["message"] == "stored"


def test_correlation_context_is_attached_automatically(captured: io.StringIO) -> None:
    """Every line inside a bound scope is traceable without passing ids around."""
    with bind(meeting_id="m-1", session_id="s-1"):
        get_logger("app.test").info("in a meeting")

    output = captured.getvalue()
    assert "meeting_id=m-1" in output
    assert "session_id=s-1" in output


def test_empty_correlation_fields_are_omitted(captured: io.StringIO) -> None:
    """Lines outside a meeting should not be padded with blank identifiers."""
    get_logger("app.test").info("standalone")

    assert "meeting_id=" not in captured.getvalue()


def test_explicit_extra_overrides_the_ambient_context(captured: io.StringIO) -> None:
    with bind(meeting_id="ambient"):
        get_logger("app.test").info("explicit wins", extra={"meeting_id": "override"})

    output = captured.getvalue()
    assert "meeting_id=override" in output
    assert "ambient" not in output


def test_json_output_is_one_object_per_line(captured_json: io.StringIO) -> None:
    logger = get_logger("app.test")
    logger.info("first", extra={"a": 1})
    logger.warning("second", extra={"b": 2})

    lines = [line for line in captured_json.getvalue().splitlines() if line.strip()]
    assert len(lines) == 2
    assert [json.loads(line)["level"] for line in lines] == ["INFO", "WARNING"]


def test_exceptions_include_a_traceback(captured: io.StringIO) -> None:
    try:
        raise ValueError("something broke")
    except ValueError:
        get_logger("app.test").exception("caught it")

    output = captured.getvalue()
    assert "caught it" in output
    assert "ValueError: something broke" in output
    assert "Traceback" in output


def test_configure_is_idempotent(captured: io.StringIO) -> None:
    """Repeated configuration must not duplicate every log line."""
    stream = io.StringIO()
    configure_logging(level="INFO", log_format="text", stream=stream)
    configure_logging(level="INFO", log_format="text", stream=stream)

    get_logger("app.test").info("once")

    assert stream.getvalue().count("once") == 1


def test_invalid_level_is_rejected() -> None:
    with pytest.raises(ValueError, match="invalid log level"):
        configure_logging(level="VERBOSE")


def test_noisy_third_party_loggers_are_quietened(captured: io.StringIO) -> None:
    configure_logging(level="DEBUG", log_format="text", stream=captured)

    assert logging.getLogger("httpx").level >= logging.WARNING
    assert logging.getLogger("socketio.client").level >= logging.WARNING
