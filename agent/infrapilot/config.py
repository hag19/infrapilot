"""Environment-driven configuration for the InfraPilot agent."""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    # Claude model — default to the latest Opus. Override with INFRAPILOT_MODEL.
    model: str = os.getenv("INFRAPILOT_MODEL", "claude-opus-4-8")
    # Reasoning depth: low | medium | high | max.
    effort: str = os.getenv("INFRAPILOT_EFFORT", "high")
    max_tokens: int = int(os.getenv("INFRAPILOT_MAX_TOKENS", "16000"))
    # How many agent loop turns before we stop (guards against runaway loops).
    max_turns: int = int(os.getenv("INFRAPILOT_MAX_TURNS", "12"))

    # In-cluster Prometheus (kube-prometheus-stack default Service).
    prometheus_url: str = os.getenv(
        "PROMETHEUS_URL", "http://monitoring-prometheus.monitoring:9090"
    )

    # Whether the agent may APPLY remediations. Off by default — diagnose &
    # propose only. Set INFRAPILOT_ALLOW_REMEDIATION=true to enable the
    # (still RBAC-gated) write tools.
    allow_remediation: bool = os.getenv(
        "INFRAPILOT_ALLOW_REMEDIATION", "false"
    ).lower() in ("1", "true", "yes")

    def __post_init__(self) -> None:
        if not os.getenv("ANTHROPIC_API_KEY"):
            raise RuntimeError(
                "ANTHROPIC_API_KEY is not set — the agent cannot reach Claude."
            )


config = Config()
