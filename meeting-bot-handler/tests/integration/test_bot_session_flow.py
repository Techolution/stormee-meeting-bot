"""The whole lifecycle over HTTP, against a simulated bot pod.

Mirrors the sequence an integrator follows: create, start, poll until active,
record, transcribe, leave.
"""

from __future__ import annotations


def test_full_session_lifecycle(client, fake_bot):
    created = client.post(
        "/bot-sessions",
        json={
            "meeting_url": "https://meet.google.com/abc-defg-hij",
            "user_name": "Alice Smith",
            "meeting_title": "Weekly Sync",
        },
    )
    assert created.status_code == 201
    session_id = created.json()["session_id"]
    assert created.json()["meeting_status"] == "CREATED"

    # Dispatch is accepted, not completed: the bot may sit in the lobby.
    started = client.post(f"/bot-sessions/{session_id}/start")
    assert started.status_code == 202
    assert started.json()["bot_status"] == "STARTING"

    # The host admits the bot; status reconciles on the next read.
    fake_bot.admit()
    status = client.get(f"/bot-sessions/{session_id}/status").json()
    assert status["meeting_status"] == "ACTIVE"
    assert status["runtime"]["session_state"] == "in_meeting"

    assert client.post(f"/bot-sessions/{session_id}/recording/start").status_code == 202
    assert client.post(f"/bot-sessions/{session_id}/transcription/start").status_code == 202

    transcript = client.get(f"/bot-sessions/{session_id}/transcript")
    assert transcript.status_code == 200
    assert transcript.json()["count"] == 1

    chat = client.get(f"/bot-sessions/{session_id}/chat")
    assert chat.status_code == 200
    assert chat.json()["chat_segments"][0]["sender"] == "Bob"

    stopped = client.post(f"/bot-sessions/{session_id}/recording/stop")
    assert stopped.status_code == 200
    assert stopped.json()["recording_status"] == "STOPPED"

    left = client.post(f"/bot-sessions/{session_id}/leave")
    assert left.status_code == 200

    final = client.get(f"/bot-sessions/{session_id}").json()
    assert final["meeting_status"] == "COMPLETED"
    assert final["recording_status"] == "STOPPED"
    assert final["transcription_status"] == "COMPLETED"


def test_create_preserves_caller_supplied_session_id(client):
    response = client.post(
        "/bot-sessions",
        json={
            "meeting_url": "https://meet.google.com/abc-defg-hij",
            "session_id": "caller-session",
        },
    )

    assert response.status_code == 201
    assert response.json()["session_id"] == "caller-session"
    assert response.json()["meeting_id"] is None


def test_leave_finalizes_a_running_recording(client, fake_bot):
    session_id = _start(client)
    client.post(f"/bot-sessions/{session_id}/recording/start")

    client.post(f"/bot-sessions/{session_id}/leave")

    final = client.get(f"/bot-sessions/{session_id}").json()
    assert final["recording_status"] == "STOPPED"


def test_recording_restart_keeps_session_and_meeting_ids(client, fake_bot):
    session_id = _start(client)

    first = client.post(f"/bot-sessions/{session_id}/recording/start").json()
    client.post(f"/bot-sessions/{session_id}/recording/stop")
    second = client.post(f"/bot-sessions/{session_id}/recording/start").json()

    assert first["session_id"] == second["session_id"] == session_id
    assert first["meeting_id"] != second["meeting_id"]
    assert first["recording_count"] == 1
    assert second["recording_count"] == 2


def test_recording_start_preserves_caller_meeting_id(client):
    session_id = _start(client)

    response = client.post(
        f"/bot-sessions/{session_id}/recording/start",
        json={"meeting_id": "caller-meeting"},
    )

    assert response.status_code == 202
    assert response.json()["session_id"] == session_id
    assert response.json()["meeting_id"] == "caller-meeting"


def test_sessions_can_be_listed_and_filtered(client):
    first = _start(client, "demo-001")
    _start(client, "demo-002")
    client.post(f"/bot-sessions/{first}/leave")

    everything = client.get("/bot-sessions").json()
    active = client.get("/bot-sessions", params={"active_only": True}).json()

    assert len(everything) == 2
    assert len(active) == 1
    assert active[0]["session_id"].startswith("abc-defg-hij_")


def test_auto_start_dispatches_on_creation(client, fake_bot):
    response = client.post(
        "/bot-sessions",
        json={
            "meeting_url": "https://meet.google.com/abc-defg-hij",
            "auto_start": True,
        },
    )

    assert response.status_code == 201
    assert response.json()["bot_status"] == "STARTING"
    assert ("POST", "/meetings/join") in fake_bot.calls


def test_the_request_id_reaches_the_bot(client, fake_bot):
    session_id = _start(client)

    client.post(
        f"/bot-sessions/{session_id}/recording/start",
        headers={"X-Request-ID": "trace-me-123"},
    )

    assert "trace-me-123" in fake_bot.request_ids


def _start(client, meeting_id: str = "demo-001") -> str:
    session_id = client.post(
        "/bot-sessions",
        json={"meeting_id": meeting_id, "meeting_url": "https://meet.google.com/abc-defg-hij"},
    ).json()["session_id"]
    client.post(f"/bot-sessions/{session_id}/start")
    return session_id
