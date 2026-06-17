"""Tool definitions (Claude tool-use schema) and the dispatcher that runs them.

Read-only tools are always available. The one write tool (restart_deployment)
is only included when remediation is enabled in config.
"""
from __future__ import annotations

import json
from typing import Any

from . import k8s
from .config import config
from .prometheus import Prometheus

_prom = Prometheus(config.prometheus_url)

READ_TOOLS: list[dict[str, Any]] = [
    {
        "name": "query_prometheus",
        "description": (
            "Run an instant PromQL query against Prometheus and return the "
            "current value(s). Use for GPU metrics (DCGM_FI_DEV_GPU_UTIL, "
            "DCGM_FI_DEV_FB_USED, DCGM_FI_DEV_GPU_TEMP, DCGM_FI_DEV_POWER_USAGE), "
            "pod restarts, node readiness, etc."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "expr": {"type": "string", "description": "A PromQL expression"}
            },
            "required": ["expr"],
        },
    },
    {
        "name": "query_prometheus_range",
        "description": "Range query over the last N minutes — use to see a trend.",
        "input_schema": {
            "type": "object",
            "properties": {
                "expr": {"type": "string"},
                "minutes": {"type": "integer", "description": "Lookback, default 30"},
            },
            "required": ["expr"],
        },
    },
    {
        "name": "list_pods",
        "description": "List pods in a namespace with phase, node, restarts, ready, and waiting reasons.",
        "input_schema": {
            "type": "object",
            "properties": {"namespace": {"type": "string"}},
            "required": ["namespace"],
        },
    },
    {
        "name": "pod_logs",
        "description": "Tail logs from a pod (optionally a specific container).",
        "input_schema": {
            "type": "object",
            "properties": {
                "namespace": {"type": "string"},
                "pod": {"type": "string"},
                "container": {"type": "string"},
                "tail": {"type": "integer", "description": "Lines, default 100"},
            },
            "required": ["namespace", "pod"],
        },
    },
    {
        "name": "list_events",
        "description": "Recent Kubernetes events in a namespace (newest first).",
        "input_schema": {
            "type": "object",
            "properties": {"namespace": {"type": "string"}},
            "required": ["namespace"],
        },
    },
    {
        "name": "describe_node",
        "description": "Node GPU capacity/allocatable and conditions — confirms the GPU node is schedulable.",
        "input_schema": {
            "type": "object",
            "properties": {"node": {"type": "string"}},
            "required": ["node"],
        },
    },
]

WRITE_TOOLS: list[dict[str, Any]] = [
    {
        "name": "restart_deployment",
        "description": (
            "REMEDIATION (mutating): roll-restart a Deployment, like "
            "`kubectl rollout restart`. Only use after diagnosing a clear, "
            "transient fault that a restart will fix. State your reason first."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "namespace": {"type": "string"},
                "name": {"type": "string"},
            },
            "required": ["namespace", "name"],
        },
    },
]


def tool_specs() -> list[dict[str, Any]]:
    tools = list(READ_TOOLS)
    if config.allow_remediation:
        tools += WRITE_TOOLS
    return tools


def dispatch(name: str, args: dict[str, Any]) -> str:
    """Execute a tool call and return a JSON/string result for the model."""
    try:
        if name == "query_prometheus":
            return json.dumps(_prom.query(args["expr"]))
        if name == "query_prometheus_range":
            return json.dumps(_prom.query_range(args["expr"], args.get("minutes", 30)))
        if name == "list_pods":
            return json.dumps(k8s.list_pods(args["namespace"]))
        if name == "pod_logs":
            return k8s.pod_logs(
                args["namespace"], args["pod"], args.get("container"), args.get("tail", 100)
            )
        if name == "list_events":
            return json.dumps(k8s.list_events(args["namespace"]))
        if name == "describe_node":
            return json.dumps(k8s.describe_node(args["node"]))
        if name == "restart_deployment":
            if not config.allow_remediation:
                return "Remediation is disabled (INFRAPILOT_ALLOW_REMEDIATION=false)."
            return k8s.restart_deployment(args["namespace"], args["name"])
        return f"Unknown tool: {name}"
    except Exception as e:  # surface the error to the model so it can adapt
        return f"ERROR running {name}: {e}"
