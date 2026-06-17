# Phase 3 — Observability runbook

Goal: real GPU metrics (utilization, VRAM, temperature, power) plus normal
cluster metrics, in Grafana.

```
DCGM exporter (gpu-operator ns, already running)
        │  /metrics :9400
        ▼
ServiceMonitor ──▶ Prometheus ──▶ Grafana ──▶ "GPU — RTX 3070 (DCGM)" dashboard
                   (kube-prometheus-stack, monitoring ns)
```

**Prereq:** Phase 1 done (GPU Operator running with `dcgmExporter.enabled: true`,
which it is in `kubernetes/gpu-operator/values.yaml`).

## What gets deployed (`kubernetes/observability/`)

| File | Purpose |
|------|---------|
| `dcgm-servicemonitor.yaml` | scrapes the DCGM exporter in the `gpu-operator` namespace |
| `grafana-dashboard-gpu.yaml` | ConfigMap dashboard, auto-imported by the Grafana sidecar |

The kube-prometheus-stack itself (Prometheus + Alertmanager + Grafana) is
**shared cluster infra owned by the base homelab repo** (`proxmox-k8s-ha`,
release `monitoring`, values in `k8s/monitoring/values-monitoring.yaml`). This
phase does **not** stand up a second stack — it only plugs GPU scraping + a
dashboard into the existing one. (See `docs/04-gitops.md` for putting that shared
stack under ArgoCD.)

## Deploy

The `monitoring` stack already runs on the cluster (from the base homelab repo).
We only add the GPU scrape config + dashboard:

```bash
kubectl apply -f kubernetes/observability/dcgm-servicemonitor.yaml
kubectl apply -f kubernetes/observability/grafana-dashboard-gpu.yaml

kubectl -n monitoring rollout status deploy/monitoring-grafana
```

> The DCGM `ServiceMonitor` carries `release: monitoring` so this cluster's
> kube-prometheus-stack (default `serviceMonitorSelector`) adopts it. The Grafana
> sidecar imports the dashboard ConfigMap by its `grafana_dashboard` label.

## Verify GPU metrics are flowing

```bash
# DCGM exporter service name/port assumed by the ServiceMonitor — confirm:
kubectl -n gpu-operator get svc -l app=nvidia-dcgm-exporter
# (adjust dcgm-servicemonitor.yaml's selector/port if they differ)

# Prometheus should list the dcgm target as "up":
kubectl -n monitoring port-forward svc/monitoring-kube-prometheus-prometheus 9090:9090
# browse http://localhost:9090/targets  → search "dcgm"
# or query:  DCGM_FI_DEV_GPU_UTIL
```

## Open Grafana

- With ingress: `https://grafana.hag19.howes` (admin / `adminPassword` from values).
- Locally:

```bash
kubectl -n monitoring port-forward svc/monitoring-grafana 3000:80
# http://localhost:3000  → Dashboards → "GPU — RTX 3070 (DCGM)"
```

Drive load from Phase 2 to see the panels move:

```bash
kubectl -n ai exec deploy/ollama -- ollama run llama3.1:8b "write a haiku about GPUs"
```

GPU utilization, VRAM used, temperature, and power should all rise.

## Notes

- **`adminPassword: changeme`** in `values.yaml` — change it (or wire to a Secret)
  before exposing Grafana beyond the LAN.
- The DCGM **ServiceMonitor selector/port** (`app=nvidia-dcgm-exporter`,
  `gpu-metrics`) matches the GPU Operator's defaults; verify and adjust if your
  operator version names them differently.
- `serviceMonitorSelectorNilUsesHelmValues: false` is what lets Prometheus pick
  up our ServiceMonitor even though it isn't labeled with the helm release.
- Ingress assumptions (nginx + cert-manager `letsencrypt`) mirror Phase 2 —
  adjust or drop the `tls:`/annotations to start on plain HTTP.

## Next: Phase 4

GitOps — ArgoCD app-of-apps so gpu-operator, ollama, and observability are all
reconciled from this repo instead of `helm install`/`kubectl apply` by hand.
Lands in `kubernetes/argocd/`.
