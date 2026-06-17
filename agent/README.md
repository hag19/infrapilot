# InfraPilot — AI SRE agent (Phase 5)

An LLM agent (Claude, `claude-opus-4-8`) that diagnoses the GPU/K8s platform from
**real signals** — it queries Prometheus and inspects Kubernetes state through a
small set of read-only tools, finds the root cause, and proposes a fix. It only
*applies* changes when remediation is explicitly enabled (and even then it's
RBAC-gated).

## How it works

```
symptom ─▶ Claude (adaptive thinking) ──tool calls──▶ Prometheus / K8s API
              ▲                                              │
              └──────────── tool results ───────────────────┘
                         ↳ ROOT CAUSE · EVIDENCE · REMEDIATION
```

A manual tool-use loop (`infrapilot/agent.py`) keeps control of which tools run,
so mutating actions can be gated. Tools (`infrapilot/tools.py`):

| Tool | Access | What |
|------|--------|------|
| `query_prometheus` / `query_prometheus_range` | read | PromQL (incl. DCGM GPU metrics) |
| `list_pods` / `pod_logs` / `list_events` | read | workload state |
| `describe_node` | read | GPU capacity/allocatable + conditions |
| `restart_deployment` | **write, gated** | `kubectl rollout restart` equivalent |

## Run locally

```bash
cd agent
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...
# uses your kubeconfig + PROMETHEUS_URL (defaults to the in-cluster Service)
export PROMETHEUS_URL=http://localhost:9090   # e.g. via kubectl port-forward

python -m infrapilot "ollama pod is Pending in namespace ai"
python -m infrapilot            # default health sweep
```

## Evals

Offline, deterministic — each scenario stubs the tool outputs and an LLM judge
scores the diagnosis against the expected root cause (`evals/scenarios.yaml`):

```bash
cd agent && python -m evals.run_evals
```

## Config (env)

| Var | Default | |
|-----|---------|--|
| `ANTHROPIC_API_KEY` | — | required |
| `INFRAPILOT_MODEL` | `claude-opus-4-8` | Claude model |
| `INFRAPILOT_EFFORT` | `high` | low/medium/high/max |
| `PROMETHEUS_URL` | `http://monitoring-prometheus.monitoring:9090` | |
| `INFRAPILOT_ALLOW_REMEDIATION` | `false` | enable the write tool |

## In-cluster

See `../kubernetes/agent/` (ServiceAccount + read-only RBAC, Secret for the API
key, Deployment) and `../docs/05-agent.md`.
