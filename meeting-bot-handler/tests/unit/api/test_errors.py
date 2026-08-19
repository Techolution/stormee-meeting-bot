"""Error envelope and status mapping."""

from __future__ import annotations


def test_unknown_session_is_404_with_a_code(client):
    response = client.get("/bot-sessions/nope/status")

    assert response.status_code == 404
    body = response.json()
    assert body["code"] == "session_not_found"
    assert body["requestId"]


def test_a_malformed_request_lists_the_offending_fields(client):
    response = client.post(
        "/bot-sessions", json={"meeting_id": "demo-001", "meeting_url": "not-a-url"}
    )

    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "validation_error"
    assert body["details"]["fields"][0]["field"].endswith("meeting_url")


def test_an_invalid_transition_is_409(client):
    session_id = _create(client)
    client.post(f"/bot-sessions/{session_id}/start")

    response = client.post(f"/bot-sessions/{session_id}/start")

    assert response.status_code == 409
    assert response.json()["code"] == "invalid_session_state"


def test_a_configured_bot_service_serves_a_session_that_was_never_dispatched(client):
    # Local-development behaviour: with BOT_SERVICE_URL set there is exactly
    # one pod, so commands reach it without discovery having run.
    session_id = _create(client)

    response = client.post(f"/bot-sessions/{session_id}/recording/start")

    assert response.status_code == 202


def test_a_bot_error_code_is_forwarded(client, fake_bot):
    session_id = _create(client)
    client.post(f"/bot-sessions/{session_id}/start")
    client.post(f"/bot-sessions/{session_id}/recording/start")
    # The bot refuses a second recording; that code must survive the hop.
    fake_bot.recording = True

    other = _create(client, meeting_id="demo-002")
    client.post(f"/bot-sessions/{other}/start")

    response = client.post(f"/bot-sessions/{other}/recording/start")

    assert response.status_code == 409
    assert response.json()["code"] in {"recording_already_active", "meeting_already_active"}


def _create(client, meeting_id: str = "demo-001") -> str:
    response = client.post(
        "/bot-sessions",
        json={"meeting_id": meeting_id, "meeting_url": "https://meet.google.com/abc-defg-hij"},
    )
    assert response.status_code == 201
    return response.json()["session_id"]
