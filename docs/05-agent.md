# Phase 5 — InfraPilot agent runbook

The capstone: an LLM agent (Claude `claude-opus-4-8`) that operates the platform
it runs on. Given a symptom, it queries Prometheus and the Kubernetes API
through read-only tools, finds the root cause from real signals, and proposes a
fix — applying changes only when explicitly enabled and RBAC-permitted.

```
symptom ─▶ InfraPilot (Claude + adaptive thinking)
              │  tool calls
              ├─▶ Prometheus  (DCGM GPU metrics, pod/node series)
              └─▶ K8s API     (pods, logs, events, nodes)   [read-only]
                     ↳ ROOT CAUSE · EVIDENCE · REMEDIATION
```

Code lives in [`../agent/`](../agent/README.md); deploy manifests in
`kubernetes/agent/`.

## Why an agent (not a script)

The failure modes here aren't a fixed checklist — "Ollama is Pending" could be a
missing GPU node, an unready Operator, a VRAM ceiling, or a bad image. The agent
forms a hypothesis, pulls the specific signals that confirm or refute it, and
explains the chain. The tool surface is deliberately small and read-only by
default; the one mutating tool (`restart_deployment`) is gated twice — by app
config (`INFRAPILOT_ALLOW_REMEDIATION`) and by Kubernetes RBAC.

## Run locally (fastest feedback)

```bash
cd agent && pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...
kubectl -n monitoring port-forward svc/monitoring-prometheus 9090:9090 &
export PROMETHEUS_URL=http://localhost:9090

python -m infrapilot "ollama pod is Pending in namespace ai"
python -m infrapilot                       # default health sweep
```

It uses your kubeconfig out of cluster, the in-cluster ServiceAccount in cluster.

## Evals

Deterministic and offline — each scenario stubs the tool outputs, the agent runs
end-to-end, and Claude judges the diagnosis against the expected root cause:

```bash
cd agent && python -m evals.run_evals
```

Add scenarios in `agent/evals/scenarios.yaml` (symptom + fixture tool outputs +
expected root cause). This is the regression net for prompt/tool changes.

## Deploy to the cluster

1. **Build + push the image** (referenced by `kubernetes/agent/cronjob.yaml`):

   ```bash
   cd agent
   docker build -t ghcr.io/hag19/infrapilot:0.1.0 .
   docker push ghcr.io/hag19/infrapilot:0.1.0
   # update the image tag in kubernetes/agent/cronjob.yaml
   ```

2. **Create the API-key Secret** (kept out of GitOps on purpose):

   ```bash
   kubectl -n ai create secret generic infrapilot-secrets \
     --from-literal=ANTHROPIC_API_KEY=sk-ant-...
   ```

3. **Apply** (read-only RBAC + config + CronJob):

   ```bash
   kubectl apply -k kubernetes/agent/
   ```

The CronJob runs a health sweep every 30 min; read its findings with:

```bash
kubectl -n ai logs job/$(kubectl -n ai get jobs -o name | grep infrapilot | tail -1 | cut -d/ -f2)
# on-demand run:
kubectl -n ai create job --from=cronjob/infrapilot-healthcheck adhoc-1
```

Under GitOps, the `agent` ArgoCD Application (sync-wave 2) reconciles all of the
above except the Secret.

## Enabling remediation (optional)

Set `INFRAPILOT_ALLOW_REMEDIATION=true` in `kubernetes/agent/configmap.yaml`.
The `infrapilot-remediation` Role (already in `rbac.yaml`) scopes the write to
*patching Deployments in `ai`* — i.e. roll-restart only. Keep it off unless you
want autonomous action; diagnosis is valuable on its own.

## Security notes

- Default posture is **read-only** — the agent observes and recommends.
- The API key is a Secret, never committed; the example file is a template.
- RBAC is least-privilege: cluster-wide *read* of pods/logs/events/nodes, plus a
  single namespaced *patch* verb only when remediation is enabled.

## That's the stack

Phases 1–5 take the platform from a bare GPU on a hypervisor to a self-operating,
observable, GitOps-managed LLM service with an agent that can reason about its
own health. See [`00-overview.md`](00-overview.md) for the whole picture.
