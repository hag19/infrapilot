"""InfraPilot — an SRE agent that diagnoses the GPU/K8s platform with Claude.

Runs a manual tool-use loop (so we keep control of which actions execute and
can gate mutating ones) against the Messages API with adaptive thinking.
"""
from __future__ import annotations

import anthropic

from .config import config
from .tools import dispatch, tool_specs

SYSTEM = """You are InfraPilot, a senior SRE/LLMOps agent operating a small
GPU-accelerated Kubernetes platform (an NVIDIA RTX 3070 passed through to one
worker, shared by time-slicing; Ollama + Open WebUI workloads; Prometheus +
Grafana + DCGM observability).

Your job: diagnose problems from real signals, find the root cause, and propose
a concrete remediation. Workflow:
1. Form a hypothesis, then verify it with the tools — query Prometheus for
   metrics, inspect pods/events/logs/nodes for state. Don't guess when you can
   look.
2. Ground every claim in a tool result you actually saw. If you couldn't verify
   something, say so.
3. End with: ROOT CAUSE (one or two sentences), EVIDENCE (the specific signals),
   and REMEDIATION (exact commands or manifest changes).

Key facts: VRAM is 8 GB, so only one 7-8B model loads at a time; the GPU is
advertised as time-slices, not real multi-GPU; an Ollama pod stuck Pending
usually means no schedulable nvidia.com/gpu (GPU node missing or Operator not
ready). Be concise and lead with the answer.

Unless remediation is explicitly enabled, you only PROPOSE fixes — you do not
apply them."""


def diagnose(symptom: str) -> str:
    """Run the agent on a symptom and return its final text answer."""
    client = anthropic.Anthropic()
    tools = tool_specs()
    messages: list[dict] = [{"role": "user", "content": symptom}]

    for _ in range(config.max_turns):
        resp = client.messages.create(
            model=config.model,
            max_tokens=config.max_tokens,
            thinking={"type": "adaptive"},
            output_config={"effort": config.effort},
            system=SYSTEM,
            tools=tools,
            messages=messages,
        )

        if resp.stop_reason == "end_turn":
            return "".join(b.text for b in resp.content if b.type == "text")

        if resp.stop_reason == "pause_turn":
            # Server-side pause — echo content back and continue.
            messages.append({"role": "assistant", "content": resp.content})
            continue

        if resp.stop_reason == "tool_use":
            messages.append({"role": "assistant", "content": resp.content})
            results = []
            for block in resp.content:
                if block.type == "tool_use":
                    out = dispatch(block.name, block.input)
                    results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": out,
                        }
                    )
            messages.append({"role": "user", "content": results})
            continue

        if resp.stop_reason == "refusal":
            return "[refused] " + str(getattr(resp, "stop_details", ""))

        # Any other stop reason (e.g. max_tokens) — return what we have.
        return "".join(b.text for b in resp.content if b.type == "text")

    return "Reached max turns without a final answer — try a narrower symptom."
