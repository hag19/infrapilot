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
| `values.yaml` | kube-prometheus-stack Helm values (Prometheus + Alertmanager + Grafana, homelab-sized) |
| `dcgm-servicemonitor.yaml` | scrapes the DCGM exporter in the `gpu-operator` namespace |
| `grafana-dashboard-gpu.yaml` | ConfigMap dashboard, auto-imported by the Grafana sidecar |

## Deploy

```bash
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update

helm install monitoring prometheus-community/kube-prometheus-stack \
  -n monitoring --create-namespace \
  -f kubernetes/observability/values.yaml

# the DCGM scrape config + GPU dashboard (namespace exists after the helm install)
kubectl apply -f kubernetes/observability/dcgm-servicemonitor.yaml
kubectl apply -f kubernetes/observability/grafana-dashboard-gpu.yaml

kubectl -n monitoring rollout status deploy/monitoring-grafana
```

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
