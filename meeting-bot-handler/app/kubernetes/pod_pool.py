"""Bot pod discovery and allocation.

A bot pod handles one meeting at a time. It advertises that by failing its
readiness probe — ``GET /api/meet/ready`` answers 503 while a meeting is in
progress — which is exactly what the handler needs to pick a free pod.

Allocation is therefore: list the pods behind the bot Deployment, probe each
one, and prefer the ones that answer "ready". The probe result is a hint, not a
lock: two handler replicas can pick the same pod at the same instant, so the
caller is expected to walk the returned candidates in order and move on when a
pod answers 409 ``meeting_already_active``.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, replace
from typing import Optional

import httpx

from app.core.config import Settings
from app.kubernetes.client import KubernetesClient, PodInfo

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BotPod:
    """A bot pod the handler can address."""

    name: str
    ip: str
    base_url: str
    #: None when the pod was never probed.
    ready: Optional[bool] = None
    node_name: Optional[str] = None

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "ip": self.ip,
            "base_url": self.base_url,
            "ready": self.ready,
            "node_name": self.node_name,
        }


class BotPodPool:
    """Discovers bot pods in the cluster and reports which ones are free."""

    def __init__(
        self,
        kubernetes: KubernetesClient,
        http_client: httpx.AsyncClient,
        settings: Settings,
    ) -> None:
        self._kubernetes = kubernetes
        self._http = http_client
        self._settings = settings

    @property
    def available(self) -> bool:
        return self._kubernetes.available

    def url_for(self, pod: PodInfo) -> str:
        """Address a pod directly.

        Pod IPs are routable cluster-wide on GKE. The load-balanced Service is
        deliberately not used: it would send a follow-up command to a pod that
        has never heard of the meeting.
        """
        return f"http://{pod.ip}:{self._settings.bot_pod_port}"

    async def list_pods(self) -> list[BotPod]:
        """Every addressable bot pod, unprobed."""
        pods = await self._kubernetes.list_pods(self._settings.bot_label_selector)
        return [
            BotPod(
                name=pod.name,
                ip=pod.ip or "",
                base_url=self.url_for(pod),
                node_name=pod.node_name,
            )
            for pod in pods
            if pod.addressable
        ]

    async def candidates(self) -> list[BotPod]:
        """Addressable pods, probed, free ones first.

        Pods that fail to answer at all are dropped: a pod that cannot serve a
        probe cannot serve a join either.
        """
        pods = await self.list_pods()
        if not pods:
            return []

        probes = await asyncio.gather(*(self._probe(pod) for pod in pods))
        reachable = [pod for pod in probes if pod.ready is not None]
        reachable.sort(key=lambda pod: not pod.ready)

        free = sum(1 for pod in reachable if pod.ready)
        logger.info(
            "Bot pod discovery: %d pod(s) in namespace %s, %d reachable, %d free",
            len(pods),
            self._settings.bot_namespace,
            len(reachable),
            free,
        )
        return reachable

    async def get_pod(self, name: str) -> Optional[BotPod]:
        """Look one pod up by name — used to confirm an assignment survives."""
        pod = await self._kubernetes.get_pod(name)
        if pod is None or not pod.addressable:
            return None
        return BotPod(
            name=pod.name,
            ip=pod.ip or "",
            base_url=self.url_for(pod),
            node_name=pod.node_name,
        )

    async def find_pod_hosting(self, meeting_id: str) -> Optional[BotPod]:
        """Find the pod that currently holds a meeting.

        Used to recover an assignment the handler lost — after a restart, or
        when a session was created against a pod that has since been replaced.
        """
        pods = await self.list_pods()
        for pod in pods:
            if await self._hosts_meeting(pod, meeting_id):
                logger.info("Meeting %s is hosted by pod %s", meeting_id, pod.name)
                return pod
        return None

    async def _probe(self, pod: BotPod) -> BotPod:
        """Ask a pod whether it can take work. 503 means busy, not broken."""
        url = f"{pod.base_url}{self._settings.bot_api_prefix}/ready"
        try:
            response = await self._http.get(
                url, timeout=self._settings.bot_probe_timeout_seconds
            )
        except httpx.HTTPError as exc:
            logger.warning("Bot pod %s did not answer its readiness probe: %s", pod.name, exc)
            return pod

        if response.status_code == httpx.codes.OK:
            return replace(pod, ready=True)
        if response.status_code == httpx.codes.SERVICE_UNAVAILABLE:
            return replace(pod, ready=False)

        logger.warning(
            "Bot pod %s answered its readiness probe with an unexpected %d",
            pod.name,
            response.status_code,
        )
        return pod

    async def _hosts_meeting(self, pod: BotPod, meeting_id: str) -> bool:
        url = (
            f"{pod.base_url}{self._settings.bot_api_prefix}"
            f"/meetings/{meeting_id}/status"
        )
        try:
            response = await self._http.get(
                url, timeout=self._settings.bot_probe_timeout_seconds
            )
        except httpx.HTTPError:
            return False
        return response.status_code == httpx.codes.OK
