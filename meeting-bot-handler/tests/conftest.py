"""Shared fixtures.

Nothing here touches a cluster or a real bot: the Kubernetes API is faked, and
the bot pod is an httpx MockTransport implementing the documented contract.
"""

from __future__ import annotations

from typing import Callable, Dict, Optional

import httpx
import pytest
from fastapi.testclient import TestClient

from app.application.bot_handler import BotHandler
from app.application.bot_service_resolver import BotServiceResolver
from app.application.session_service import SessionService
from app.bootstrap import Container
from app.core.config import Settings
from app.domain.models import BotSession
from app.kubernetes.client import PodInfo
from app.kubernetes.pod_pool import BotPodPool
from app.main import create_app
from app.repositories.in_memory_session_repository import InMemorySessionRepository


@pytest.fixture
def settings() -> Settings:
    return Settings(
        environment="test",
        kubernetes_enabled=False,
        bot_service_url="http://bot-pod:5000",
        join_poll_interval_seconds=0.01,
        join_poll_timeout_seconds=0.5,
        bot_probe_timeout_seconds=0.5,
    )


class FakeKubernetesClient:
    """Stands in for the Kubernetes API with a fixed set of pods."""

    def __init__(self, pods: Optional[list[PodInfo]] = None, available: bool = True):
        self.pods = pods or []
        self._available = available
        self.load_error = None if available else "no cluster"

    @property
    def available(self) -> bool:
        return self._available

    async def list_pods(self, label_selector: str) -> list[PodInfo]:
        return list(self.pods)

    async def get_pod(self, name: str) -> Optional[PodInfo]:
        return next((pod for pod in self.pods if pod.name == name), None)


def running_pod(name: str, ip: str, ready: bool = True) -> PodInfo:
    return PodInfo(name=name, ip=ip, phase="Running", ready=ready, node_name="node-1")


class FakeBot:
    """One bot pod's behaviour, addressable over a mock transport.

    Models the two things the handler has to react to: a pod takes one meeting
    at a time, and joining is asynchronous.
    """

    def __init__(self, *, busy: bool = False, offline: bool = False, claimed_after_probe: bool = False):
        self.meeting_id: Optional[str] = "someone-elses-meeting" if busy else None
        self.offline = offline
        #: Probes free, then refuses the join — a pod claimed by another
        #: replica between the two calls.
        self.claimed_after_probe = claimed_after_probe
        self.session_state = "joining"
        self.recording = False
        self.calls: list[tuple[str, str]] = []
        self.request_ids: list[str] = []

    def admit(self) -> None:
        self.session_state = "in_meeting"

    def handle(self, request: httpx.Request) -> httpx.Response:
        if self.offline:
            raise httpx.ConnectError("connection refused", request=request)

        path = request.url.path.replace("/api/meet", "", 1)
        self.calls.append((request.method, path))
        self.request_ids.append(request.headers.get("X-Request-ID", ""))

        if path == "/ready":
            free = self.meeting_id is None
            return httpx.Response(200 if free else 503, json={"ready": free, "dependencies": []})

        if path == "/meetings/join":
            if self.claimed_after_probe:
                return self._error(409, "meeting_already_active", "Claimed since the probe")
            if self.meeting_id is not None:
                return self._error(409, "meeting_already_active", "Already in a meeting")
            self.meeting_id = request.read().decode() and _json(request)["meetingId"]
            return httpx.Response(
                202,
                json={
                    "message": "Joining meeting",
                    "meetingId": self.meeting_id,
                    "sessionId": "bot-session-1",
                },
            )

        if path.startswith("/meetings/") and path.endswith("/status"):
            meeting_id = path.split("/")[2]
            if meeting_id != self.meeting_id:
                return self._error(404, "meeting_not_found", "No such meeting")
            return httpx.Response(
                200,
                json={
                    "meeting_id": meeting_id,
                    "session_id": "bot-session-1",
                    "session_state": self.session_state,
                    "healthy": True,
                    "components": [],
                },
            )

        if path == "/meetings/leave":
            self.meeting_id = None
            self.session_state = "ended"
            return httpx.Response(200, json={"message": "Left meeting"})

        if path == "/recordings/start":
            if self.recording:
                return self._error(409, "recording_already_active", "Already recording")
            self.recording = True
            return httpx.Response(200, json={"message": "Recording started"})

        if path == "/recordings/stop":
            self.recording = False
            return httpx.Response(200, json={"message": "Recording stopped"})

        if path.startswith("/recordings/") and path.endswith("/status"):
            return httpx.Response(
                200,
                json={
                    "status": "stopped",
                    "chunksCaptured": 48,
                    "chunksUploaded": 48,
                    "chunksPending": 0,
                    "bytesUploaded": 3145728,
                },
            )

        if path in ("/transcription/start", "/transcription/stop"):
            return httpx.Response(200, json={"message": "ok", "count": 0, "segments": []})

        if path.endswith("/transcript"):
            return httpx.Response(
                200,
                json={"count": 1, "segments": [{"speaker": "Alice", "text": "hi"}]},
            )

        if path.endswith("/chat"):
            return httpx.Response(
                200, json={"count": 1, "chatSegments": [{"sender": "Bob", "text": "hello"}]}
            )

        return self._error(404, "not_found", f"No route for {path}")

    @staticmethod
    def _error(status: int, code: str, message: str) -> httpx.Response:
        return httpx.Response(
            status,
            json={"code": code, "message": message, "details": {}, "requestId": "bot-req-1"},
        )


def _json(request: httpx.Request) -> Dict:
    import json

    return json.loads(request.content or b"{}")


def bot_transport(routes: Dict[str, FakeBot]) -> httpx.MockTransport:
    """Route by host, so several pods can be simulated at once."""

    def dispatch(request: httpx.Request) -> httpx.Response:
        bot = routes.get(request.url.host)
        if bot is None:
            return httpx.Response(404, json={"code": "no_such_pod", "message": "unknown host"})
        return bot.handle(request)

    return httpx.MockTransport(dispatch)


@pytest.fixture
def fake_bot() -> FakeBot:
    return FakeBot()


@pytest.fixture
def http_client(fake_bot: FakeBot) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=bot_transport({"bot-pod": fake_bot}))


@pytest.fixture
def session_service() -> SessionService:
    return SessionService(InMemorySessionRepository())


@pytest.fixture
def make_handler(settings: Settings, session_service: SessionService) -> Callable[..., BotHandler]:
    def factory(
        http_client: httpx.AsyncClient,
        pod_pool: Optional[BotPodPool] = None,
        static_service_url: Optional[str] = "http://bot-pod:5000",
    ) -> BotHandler:
        return BotHandler(
            session_service=session_service,
            bot_resolver=BotServiceResolver(
                pod_pool=pod_pool, static_service_url=static_service_url
            ),
            http_client=http_client,
            settings=settings,
        )

    return factory


@pytest.fixture
def handler(make_handler, http_client) -> BotHandler:
    return make_handler(http_client)


@pytest.fixture
async def created_session(session_service: SessionService) -> BotSession:
    return await session_service.create_session(
        BotSession(
            session_id="sess-1",
            meeting_id="demo-001",
            meeting_url="https://meet.google.com/abc-defg-hij",
        )
    )


@pytest.fixture
def client(settings, session_service, handler, http_client) -> TestClient:
    """A TestClient whose app is wired to the fakes above."""
    app = create_app(settings)

    kubernetes = FakeKubernetesClient(available=False)
    pod_pool = BotPodPool(kubernetes=kubernetes, http_client=http_client, settings=settings)
    container = Container(
        settings=settings,
        http_client=http_client,
        kubernetes=kubernetes,
        pod_pool=pod_pool,
        repository=session_service._repo,
        session_service=session_service,
        resolver=handler.bot_resolver,
        bot_handler=handler,
    )

    with TestClient(app) as test_client:
        # Replace the container the real lifespan built.
        app.state.container = container
        yield test_client
