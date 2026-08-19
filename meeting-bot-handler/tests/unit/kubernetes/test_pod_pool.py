"""Pod discovery: which pods exist, and which can take a meeting."""

from __future__ import annotations

import httpx

from app.kubernetes.client import PodInfo
from app.kubernetes.pod_pool import BotPodPool
from tests.conftest import FakeBot, FakeKubernetesClient, bot_transport, running_pod


def make_pool(pods, bots, settings) -> BotPodPool:
    return BotPodPool(
        kubernetes=FakeKubernetesClient(pods),
        http_client=httpx.AsyncClient(transport=bot_transport(bots)),
        settings=settings,
    )

async def test_only_addressable_pods_are_listed(settings):
    pods = [
        running_pod("bot-a", "10.0.0.1"),
        PodInfo(name="bot-pending", ip=None, phase="Pending", ready=False),
        PodInfo(name="bot-gone", ip="10.0.0.9", phase="Succeeded", ready=False),
    ]
    pool = make_pool(pods, {}, settings)

    listed = await pool.list_pods()

    assert [pod.name for pod in listed] == ["bot-a"]
    assert listed[0].base_url == "http://10.0.0.1:5000"

async def test_free_pods_are_offered_before_busy_ones(settings):
    pods = [running_pod("bot-busy", "10.0.0.1"), running_pod("bot-free", "10.0.0.2")]
    bots = {"10.0.0.1": FakeBot(busy=True), "10.0.0.2": FakeBot()}
    pool = make_pool(pods, bots, settings)

    candidates = await pool.candidates()

    assert [pod.name for pod in candidates] == ["bot-free", "bot-busy"]
    assert [pod.ready for pod in candidates] == [True, False]

async def test_unreachable_pods_are_dropped(settings):
    pods = [running_pod("bot-down", "10.0.0.1"), running_pod("bot-up", "10.0.0.2")]
    bots = {"10.0.0.1": FakeBot(offline=True), "10.0.0.2": FakeBot()}
    pool = make_pool(pods, bots, settings)

    candidates = await pool.candidates()

    assert [pod.name for pod in candidates] == ["bot-up"]

async def test_no_pods_when_discovery_is_unavailable(settings):
    pool = BotPodPool(
        kubernetes=FakeKubernetesClient(available=False),
        http_client=httpx.AsyncClient(transport=bot_transport({})),
        settings=settings,
    )

    assert pool.available is False
    assert await pool.list_pods() == []

async def test_find_pod_hosting_locates_the_meeting(settings):
    pods = [running_pod("bot-a", "10.0.0.1"), running_pod("bot-b", "10.0.0.2")]
    holder = FakeBot()
    holder.meeting_id = "demo-001"
    pool = make_pool(pods, {"10.0.0.1": FakeBot(), "10.0.0.2": holder}, settings)

    found = await pool.find_pod_hosting("demo-001")

    assert found is not None and found.name == "bot-b"

async def test_find_pod_hosting_returns_none_when_nobody_holds_it(settings):
    pods = [running_pod("bot-a", "10.0.0.1")]
    pool = make_pool(pods, {"10.0.0.1": FakeBot()}, settings)

    assert await pool.find_pod_hosting("demo-001") is None
