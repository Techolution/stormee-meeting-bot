"""The bot wire contract: payload casing, correlation ids, error envelopes."""

from __future__ import annotations

import json

import httpx
import pytest

from app.clients.meeting_api import MeetingApiClient
from app.core.context import set_request_id
from app.domain.exceptions import BotOperationError, BotServiceUnavailableError


def client_recording_requests() -> tuple[MeetingApiClient, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"ok": True})

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return MeetingApiClient(base_url="http://10.0.0.1:5000", http_client=http), seen


def test_api_prefix_is_added_once():
    http = httpx.AsyncClient()
    assert MeetingApiClient("http://pod:5000", http).base_url == "http://pod:5000/api/meet"
    assert MeetingApiClient("http://pod:5000/api/meet", http).base_url == "http://pod:5000/api/meet"
    assert MeetingApiClient("http://pod:5000/", http).base_url == "http://pod:5000/api/meet"


async def test_join_sends_camel_case_and_drops_unset_fields():
    client, seen = client_recording_requests()

    await client.join_meeting(
        meeting_id="demo-001",
        meeting_url="https://meet.google.com/abc",
        user_name="Alice",
    )

    body = json.loads(seen[0].content)
    assert body == {
        "meetingId": "demo-001",
        "meetingUrl": "https://meet.google.com/abc",
        "userName": "Alice",
    }
    assert seen[0].url.path == "/api/meet/meetings/join"


async def test_inbound_request_id_is_forwarded_to_the_bot():
    client, seen = client_recording_requests()
    set_request_id("trace-me-123")

    await client.start_recording("demo-001")

    assert seen[0].headers["X-Request-ID"] == "trace-me-123"


async def test_a_request_id_is_generated_when_there_is_none():
    client, seen = client_recording_requests()
    set_request_id("")

    await client.start_recording("demo-001")

    assert seen[0].headers["X-Request-ID"]


async def test_error_envelope_becomes_a_typed_exception():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            409,
            json={
                "code": "meeting_already_active",
                "message": "Already running",
                "details": {"meeting_id": "demo-001"},
                "requestId": "bot-req-7",
            },
        )

    client = MeetingApiClient(
        "http://pod:5000", httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )

    with pytest.raises(BotOperationError) as exc_info:
        await client.join_meeting("demo-001", "https://meet.google.com/abc")

    error = exc_info.value
    assert error.code == "meeting_already_active"
    assert error.status_code == 409
    assert error.request_id == "bot-req-7"
    assert error.details == {"meeting_id": "demo-001"}


async def test_a_non_json_error_still_raises_with_the_status():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(502, text="<html>nginx</html>")

    client = MeetingApiClient(
        "http://pod:5000", httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )

    with pytest.raises(BotOperationError) as exc_info:
        await client.leave_meeting("demo-001")

    assert exc_info.value.status_code == 502


async def test_a_network_failure_is_reported_as_an_unreachable_pod():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    client = MeetingApiClient(
        "http://pod:5000", httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )

    with pytest.raises(BotServiceUnavailableError):
        await client.get_bot_status("demo-001")


async def test_readiness_reports_a_busy_pod_rather_than_raising():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"ready": False, "dependencies": []})

    client = MeetingApiClient(
        "http://pod:5000", httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )

    ready, body = await client.check_ready()

    assert ready is False
    assert body == {"ready": False, "dependencies": []}
