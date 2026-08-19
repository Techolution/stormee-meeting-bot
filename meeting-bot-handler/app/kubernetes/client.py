"""Kubernetes API client wrapper.

All interaction with the Kubernetes client library lives behind this module, so
the rest of the application can be exercised without a cluster.

Configuration is loaded in the order a deployment actually experiences it:
in-cluster service account first (how this runs on GKE), then a kubeconfig (how
a developer runs it against a cluster from a laptop). When neither is available
the client reports itself unavailable rather than raising, and the handler falls
back to the statically configured ``BOT_SERVICE_URL``.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Optional

logger = logging.getLogger(__name__)

try:  # The library is absent in some local environments; degrade, do not crash.
    from kubernetes import client as k8s_client
    from kubernetes import config as k8s_config
    from kubernetes.client.rest import ApiException

    KUBERNETES_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised only where the dep is absent
    k8s_client = None  # type: ignore[assignment]
    k8s_config = None  # type: ignore[assignment]
    ApiException = Exception  # type: ignore[assignment,misc]
    KUBERNETES_AVAILABLE = False


@dataclass(frozen=True)
class PodInfo:
    """The parts of a pod the handler actually routes on."""

    name: str
    ip: Optional[str]
    phase: str
    ready: bool
    node_name: Optional[str] = None

    @property
    def addressable(self) -> bool:
        """True when the pod has an IP and a running container to serve it.

        Readiness is deliberately not part of this: a bot pod reports itself
        unready while it is in a meeting, and the handler still needs to reach
        that pod to control the meeting it is running.
        """
        return self.phase == "Running" and bool(self.ip)


class KubernetesClient:
    """Thin async wrapper over the (synchronous) Kubernetes Python client."""

    def __init__(
        self,
        namespace: str,
        kubeconfig: Optional[str] = None,
        enabled: bool = True,
    ) -> None:
        self.namespace = namespace
        self._kubeconfig = kubeconfig
        self._enabled = enabled and KUBERNETES_AVAILABLE
        self._core_v1: Any = None
        self._load_error: Optional[str] = None

        if enabled and not KUBERNETES_AVAILABLE:
            self._load_error = "kubernetes client library is not installed"
            logger.warning("Kubernetes support disabled: %s", self._load_error)
        elif self._enabled:
            self._load()

    def _load(self) -> None:
        try:
            if self._kubeconfig:
                k8s_config.load_kube_config(config_file=self._kubeconfig)
                source = f"kubeconfig {self._kubeconfig}"
            else:
                try:
                    k8s_config.load_incluster_config()
                    source = "in-cluster service account"
                except k8s_config.ConfigException:
                    k8s_config.load_kube_config()
                    source = "default kubeconfig"
        except Exception as exc:  # noqa: BLE001 - any failure means "no cluster"
            self._enabled = False
            self._load_error = str(exc)
            logger.warning("Kubernetes configuration unavailable: %s", exc)
            return

        self._core_v1 = k8s_client.CoreV1Api()
        logger.info(
            "Kubernetes client configured from %s (namespace=%s)", source, self.namespace
        )

    @property
    def available(self) -> bool:
        return self._enabled and self._core_v1 is not None

    @property
    def load_error(self) -> Optional[str]:
        return self._load_error

    async def list_pods(self, label_selector: str) -> list[PodInfo]:
        """List pods matching ``label_selector`` in the configured namespace."""
        if not self.available:
            return []

        try:
            result = await asyncio.to_thread(
                self._core_v1.list_namespaced_pod,
                namespace=self.namespace,
                label_selector=label_selector,
            )
        except ApiException as exc:
            logger.error(
                "Kubernetes rejected a pod listing (namespace=%s selector=%s): %s",
                self.namespace,
                label_selector,
                exc,
            )
            raise
        except Exception as exc:  # noqa: BLE001 - network/DNS failures
            logger.error("Could not reach the Kubernetes API: %s", exc)
            raise

        return [self._to_pod_info(item) for item in result.items]

    async def get_pod(self, name: str) -> Optional[PodInfo]:
        """Fetch one pod by name, or None when it no longer exists."""
        if not self.available:
            return None

        try:
            pod = await asyncio.to_thread(
                self._core_v1.read_namespaced_pod, name=name, namespace=self.namespace
            )
        except ApiException as exc:
            if getattr(exc, "status", None) == 404:
                return None
            raise
        return self._to_pod_info(pod)

    @staticmethod
    def _to_pod_info(pod: Any) -> PodInfo:
        conditions = pod.status.conditions or []
        ready = any(c.type == "Ready" and c.status == "True" for c in conditions)
        return PodInfo(
            name=pod.metadata.name,
            ip=pod.status.pod_ip,
            phase=pod.status.phase or "Unknown",
            ready=ready,
            node_name=pod.spec.node_name if pod.spec else None,
        )
