"""Probes and cluster visibility."""

from __future__ import annotations


def test_health_is_dependency_free(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_ready_accepts_a_statically_configured_bot(client):
    # No cluster in this fixture, but BOT_SERVICE_URL is set, so the handler
    # can still dispatch.
    response = client.get("/ready")

    assert response.status_code == 200
    body = response.json()
    assert body["ready"] is True
    names = {d["name"]: d["healthy"] for d in body["dependencies"]}
    assert names["kubernetes"] is False
    assert names["static_bot_service"] is True


def test_request_id_is_echoed(client):
    response = client.get("/health", headers={"X-Request-ID": "trace-me-123"})

    assert response.headers["X-Request-ID"] == "trace-me-123"


def test_a_request_id_is_generated_when_absent(client):
    assert client.get("/health").headers["X-Request-ID"]


def test_bot_pods_reports_discovery_being_off_rather_than_failing(client):
    response = client.get("/bot-pods")

    assert response.status_code == 200
    body = response.json()
    assert body["discovery_available"] is False
    assert body["total"] == 0
    assert body["detail"]
