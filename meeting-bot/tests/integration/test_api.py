"""API contract tests.

These pin the HTTP surface: status codes, the error envelope, and the camelCase
field names existing callers already send. A refactor is free to move code
around behind these.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app

PREFIX = "/api/meet"


@pytest.fixture
def client(settings: Settings) -> TestClient:
    with TestClient(create_app(settings)) as test_client:
        yield test_client


# --------------------------------------------------------------------------
# Probes
# --------------------------------------------------------------------------


def test_health_needs_no_dependency(client: TestClient) -> None:
    """Liveness must be true whenever the process is up; failing it restarts the pod."""
    response = client.get(f"{PREFIX}/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "meeting-bot"


def test_readiness_reports_dependencies(client: TestClient) -> None:
    response = client.get(f"{PREFIX}/ready")

    assert response.status_code == 200
    body = response.json()
    assert body["ready"] is True
    assert {entry["name"] for entry in body["dependencies"]} >= {
        "state_repository",
        "cw_utils",
        "audio_service",
    }


def test_status_reports_configuration_without_secrets(client: TestClient) -> None:
    response = client.get(f"{PREFIX}/status")

    assert response.status_code == 200
    body = response.json()
    assert body["activeSessions"] == 0
    assert body["configuration"]["environment"] == "local"
    assert "password" not in str(body["configuration"]).lower().replace("password_set", "")


# --------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "payload,bad_field",
    [
        ({"meetingId": "m1"}, "meetingUrl"),
        ({"meetingUrl": "https://meet.google.com/abc"}, "meetingId"),
        ({"meetingId": "m1", "meetingUrl": "meet.google.com/abc"}, "meetingUrl"),
        ({"meetingId": "  ", "meetingUrl": "https://meet.google.com/abc"}, "meetingId"),
    ],
)
def test_join_rejects_invalid_requests(client: TestClient, payload: dict, bad_field: str) -> None:
    response = client.post(f"{PREFIX}/meetings/join", json=payload)

    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "validation_error"
    assert any(field["field"] == bad_field for field in body["details"]["fields"])


def test_play_audio_rejects_out_of_range_volume(client: TestClient) -> None:
    response = client.post(
        f"{PREFIX}/meetings/audio/play",
        json={"meetingId": "m1", "audioUrl": "https://audio.test/clip.wav", "volume": 1.5},
    )

    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"



# --------------------------------------------------------------------------
# Missing sessions
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "method,path,payload",
    [
        ("POST", f"{PREFIX}/meetings/leave", {"meetingId": "ghost"}),
        ("POST", f"{PREFIX}/recordings/start", {"meetingId": "ghost"}),
        ("POST", f"{PREFIX}/recordings/stop", {"meetingId": "ghost"}),
        ("POST", f"{PREFIX}/transcription/start", {"meetingId": "ghost"}),
        ("POST", f"{PREFIX}/transcription/stop", {"meetingId": "ghost"}),
        ("GET", f"{PREFIX}/recordings/ghost/status", None),
        ("GET", f"{PREFIX}/transcription/ghost/transcript", None),
        ("GET", f"{PREFIX}/transcription/ghost/chat", None),
        ("GET", f"{PREFIX}/meetings/ghost/status", None),
        ("GET", f"{PREFIX}/meetings/ghost/state", None),
    ],
)
def test_unknown_meeting_returns_a_typed_404(
    client: TestClient, method: str, path: str, payload: dict | None
) -> None:
    response = client.request(method, path, json=payload)

    assert response.status_code == 404
    body = response.json()
    assert body["code"] == "meeting_not_found"
    assert body["details"]["meeting_id"] == "ghost"
    assert body["requestId"], "every error must be traceable to a log line"


def test_state_history_is_empty_rather_than_missing(client: TestClient) -> None:
    """A history read for an unknown meeting is a valid empty answer, not an error."""
    response = client.get(f"{PREFIX}/meetings/ghost/state/history")

    assert response.status_code == 200
    body = response.json()
    assert body["history"] == []
    assert body["count"] == 0


# --------------------------------------------------------------------------
# Correlation
# --------------------------------------------------------------------------


def test_request_id_is_honoured_and_echoed(client: TestClient) -> None:
    """A caller's trace id must survive the hop so logs join up across services."""
    response = client.get(f"{PREFIX}/health", headers={"X-Request-ID": "trace-123"})

    assert response.headers["X-Request-ID"] == "trace-123"


def test_request_id_is_generated_when_absent(client: TestClient) -> None:
    response = client.get(f"{PREFIX}/health")

    assert response.headers.get("X-Request-ID")


# --------------------------------------------------------------------------
# Documentation
# --------------------------------------------------------------------------


def test_openapi_document_is_complete(client: TestClient) -> None:
    """The published schema is the contract; it must describe every route."""
    response = client.get(f"{PREFIX}/openapi.json")

    assert response.status_code == 200
    paths = response.json()["paths"]
    for expected in (
        f"{PREFIX}/meetings/join",
        f"{PREFIX}/meetings/leave",
        f"{PREFIX}/recordings/start",
        f"{PREFIX}/recordings/stop",
        f"{PREFIX}/transcription/start",
        f"{PREFIX}/transcription/stop",
        f"{PREFIX}/health",
        f"{PREFIX}/ready",
        f"{PREFIX}/status",
    ):
        assert expected in paths, f"{expected} is not documented"


# --------------------------------------------------------------------------
# Log correlation
#
# The previous implementation pulled meetingId out of the request body so every
# log line for a request named the meeting it concerned. Reading only path
# parameters lost that for POST routes, which are most of them.
# --------------------------------------------------------------------------


def test_meeting_id_is_correlated_from_the_request_body(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level("INFO"):
        client.post(f"{PREFIX}/recordings/start", json={"meetingId": "from-body"})

    tagged = [r for r in caplog.records if getattr(r, "meeting_id", "") == "from-body"]
    assert tagged, "log records should carry the meeting id taken from the body"
    assert any(r.name == "app.api.middleware" for r in tagged), (
        "the request-completion line runs after the handler and must carry it too"
    )


def test_meeting_id_is_correlated_from_the_path(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level("INFO"):
        client.get(f"{PREFIX}/recordings/from-path/status")

    assert any(getattr(r, "meeting_id", "") == "from-path" for r in caplog.records)


def test_join_correlates_by_url_before_an_id_exists(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    """A malformed join has no usable id; the URL is the next best handle."""
    with caplog.at_level("INFO"):
        client.post(f"{PREFIX}/meetings/join", json={"meetingUrl": "https://meet.google.com/a-b-c"})

    assert any(
        "meet.google.com" in str(getattr(r, "meeting_id", "")) for r in caplog.records
    )


def test_requests_without_a_meeting_are_not_tagged(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    """An empty field would be noise on every line that has no meeting."""
    with caplog.at_level("INFO"):
        client.get(f"{PREFIX}/status")

    completion = [r for r in caplog.records if r.name == "app.api.middleware"]
    assert completion
    assert all(not getattr(r, "meeting_id", "") for r in completion)
