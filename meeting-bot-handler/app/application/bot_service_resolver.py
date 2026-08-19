"""Resolving a session to the bot pod that serves it.

Two distinct questions, deliberately separate methods:

``resolve``    Where does this session's meeting already live? Answering wrong
               sends a stop-recording command to a pod that never heard of the
               meeting.

``allocate``   Which pods could take a new meeting? Returns an ordered list of
               candidates rather than a single answer, because readiness is a
               hint: between the probe and the join, another replica may have
               claimed the pod. The caller walks the list.

Nothing above this class knows about pods. Swapping discovery for a worker
registry or a queue changes this file and nothing else.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List, Optional

from app.domain.exceptions import BotServiceNotAssignedError, NoBotPodAvailableError
from app.domain.models import BotSession
from app.kubernetes.pod_pool import BotPod, BotPodPool

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BotTarget:
    """A resolved destination for one session's commands."""

    service_url: str
    worker_id: Optional[str] = None
    pod_name: Optional[str] = None
    pod_ip: Optional[str] = None

    @classmethod
    def from_pod(cls, pod: BotPod) -> "BotTarget":
        return cls(
            service_url=pod.base_url,
            worker_id=pod.name,
            pod_name=pod.name,
            pod_ip=pod.ip,
        )


class BotServiceResolver:
    """Resolves the execution destination for a bot session."""

    def __init__(
        self,
        pod_pool: Optional[BotPodPool] = None,
        static_service_url: Optional[str] = None,
    ) -> None:
        self._pod_pool = pod_pool
        self._static_service_url = static_service_url.rstrip("/") if static_service_url else None

    @property
    def can_discover(self) -> bool:
        return self._pod_pool is not None and self._pod_pool.available

    async def resolve(self, session: BotSession) -> BotTarget:
        """Return the pod already serving this session.

        Raises:
            BotServiceNotAssignedError: The session was never dispatched, or its
                pod is gone and the meeting with it.
        """
        service_url = getattr(session, "service_url", None)
        if service_url:
            return BotTarget(
                service_url=service_url,
                worker_id=session.worker_id,
                pod_name=session.pod_name,
                pod_ip=session.pod_ip,
            )

        if self._static_service_url:
            return BotTarget(service_url=self._static_service_url)

        # The assignment may have been lost — a handler restart, or a session
        # created before dispatch. Ask the cluster who holds the meeting.
        recovered = await self.recover(session)
        if recovered:
            return recovered

        raise BotServiceNotAssignedError(
            f"Session {session.session_id} has no bot pod assigned",
            details={"session_id": session.session_id, "meeting_id": session.meeting_id},
        )

    async def recover(self, session: BotSession) -> Optional[BotTarget]:
        """Find the pod hosting this session's meeting, if any still is."""
        if self._pod_pool is None or not self._pod_pool.available:
            return None
        pod = await self._pod_pool.find_pod_hosting(session.meeting_id)
        return BotTarget.from_pod(pod) if pod else None

    async def allocate(self, session: BotSession) -> List[BotTarget]:
        """Candidate pods for a new meeting, free ones first.

        Raises:
            NoBotPodAvailableError: Discovery is configured but found nothing
                reachable.
        """
        if self._pod_pool is None or not self._pod_pool.available:
            if self._static_service_url:
                logger.info(
                    "Pod discovery unavailable; dispatching session %s to the "
                    "statically configured bot service",
                    session.session_id,
                )
                return [BotTarget(service_url=self._static_service_url)]
            raise NoBotPodAvailableError(
                "Kubernetes pod discovery is unavailable and no BOT_SERVICE_URL is configured",
                details={"session_id": session.session_id},
            )

        pods = await self._pod_pool.candidates()
        if not pods:
            raise NoBotPodAvailableError(
                "No bot pod in the cluster is reachable",
                details={"session_id": session.session_id},
            )

        if not any(pod.ready for pod in pods):
            # Every pod is mid-meeting. Say so plainly: the fix is to scale the
            # Deployment, not to retry harder.
            raise NoBotPodAvailableError(
                f"All {len(pods)} bot pod(s) are busy",
                details={"session_id": session.session_id, "pods": len(pods)},
            )

        return [BotTarget.from_pod(pod) for pod in pods if pod.ready]
