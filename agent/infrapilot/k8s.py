"""Read-only Kubernetes helpers, plus an optional gated restart action.

Loads in-cluster config when running as a pod, otherwise falls back to the
local kubeconfig so you can run the agent from your laptop against the cluster.
"""
from __future__ import annotations

from typing import Any

from kubernetes import client, config as kube_config


def _load() -> None:
    try:
        kube_config.load_incluster_config()
    except kube_config.ConfigException:
        kube_config.load_kube_config()


_load()
_core = client.CoreV1Api()
_apps = client.AppsV1Api()


def list_pods(namespace: str) -> list[dict[str, Any]]:
    pods = _core.list_namespaced_pod(namespace).items
    out = []
    for p in pods:
        statuses = p.status.container_statuses or []
        out.append(
            {
                "name": p.metadata.name,
                "phase": p.status.phase,
                "node": p.spec.node_name,
                "restarts": sum(c.restart_count for c in statuses),
                "ready": all(c.ready for c in statuses) if statuses else False,
                "reasons": [
                    c.state.waiting.reason
                    for c in statuses
                    if c.state and c.state.waiting and c.state.waiting.reason
                ],
            }
        )
    return out


def pod_logs(namespace: str, pod: str, container: str | None = None, tail: int = 100) -> str:
    return _core.read_namespaced_pod_log(
        name=pod, namespace=namespace, container=container, tail_lines=tail
    )


def list_events(namespace: str, limit: int = 40) -> list[dict[str, Any]]:
    events = _core.list_namespaced_event(namespace).items
    events.sort(key=lambda e: e.last_timestamp or e.event_time or 0, reverse=True)
    return [
        {
            "type": e.type,
            "reason": e.reason,
            "object": f"{e.involved_object.kind}/{e.involved_object.name}",
            "message": e.message,
        }
        for e in events[:limit]
    ]


def describe_node(node: str) -> dict[str, Any]:
    n = _core.read_node(node)
    alloc = n.status.allocatable or {}
    cap = n.status.capacity or {}
    conditions = {c.type: c.status for c in (n.status.conditions or [])}
    return {
        "name": node,
        "gpu_capacity": cap.get("nvidia.com/gpu"),
        "gpu_allocatable": alloc.get("nvidia.com/gpu"),
        "conditions": conditions,
    }


def restart_deployment(namespace: str, name: str) -> str:
    """Gated remediation: roll a Deployment by bumping a restart annotation.

    Only reachable when INFRAPILOT_ALLOW_REMEDIATION=true AND the ServiceAccount
    RBAC allows the patch. Mirrors `kubectl rollout restart`.
    """
    import datetime

    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    patch = {
        "spec": {
            "template": {
                "metadata": {
                    "annotations": {"infrapilot.ai/restartedAt": now}
                }
            }
        }
    }
    _apps.patch_namespaced_deployment(name=name, namespace=namespace, body=patch)
    return f"rollout restart issued for deploy/{name} in {namespace} at {now}"
