"""The Kubernetes wrapper's contract, without a cluster."""

from __future__ import annotations

from types import SimpleNamespace

from app.kubernetes.client import KubernetesClient, PodInfo


def pod(name="bot-a", ip="10.0.0.1", phase="Running", ready=True):
    return SimpleNamespace(
        metadata=SimpleNamespace(name=name),
        status=SimpleNamespace(
            pod_ip=ip,
            phase=phase,
            conditions=[SimpleNamespace(type="Ready", status="True" if ready else "False")],
        ),
        spec=SimpleNamespace(node_name="node-1"),
    )


def test_pod_info_is_extracted_from_the_api_object():
    info = KubernetesClient._to_pod_info(pod())

    assert info == PodInfo(name="bot-a", ip="10.0.0.1", phase="Running", ready=True, node_name="node-1")
    assert info.addressable


def test_a_busy_pod_is_still_addressable():
    # A bot reports itself unready while in a meeting; the handler must still
    # be able to reach it to control that meeting.
    info = KubernetesClient._to_pod_info(pod(ready=False))

    assert info.ready is False
    assert info.addressable


def test_a_pod_without_an_ip_is_not_addressable():
    assert not KubernetesClient._to_pod_info(pod(ip=None, phase="Pending")).addressable


def test_disabled_client_reports_unavailable_instead_of_raising():
    client = KubernetesClient(namespace="default", enabled=False)

    assert client.available is False
