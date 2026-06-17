# Phase 2 — Ollama + Open WebUI runbook

Goal: serve a local LLM on the GPU and reach it from a browser.

```
Open WebUI (no GPU) ──http──▶ Ollama Service ──▶ Ollama pod (nvidia.com/gpu: 1)
       ▲                                                  │
   Ingress + TLS                                     models PVC (50Gi)
   chat.hag19.howes
```

**Prereq:** Phase 1 complete — `kubectl describe node gpu-worker-1 | grep nvidia.com/gpu`
shows schedulable slices.

## What gets deployed (`kubernetes/ollama/`)

| File | Resource |
|------|----------|
| `namespace.yaml` | `ai` namespace |
| `ollama.yaml` | Ollama Deployment (requests `nvidia.com/gpu: 1`) + 50Gi models PVC + Service `:11434` |
| `open-webui.yaml` | Open WebUI Deployment + 5Gi data PVC + Service `:80` |
| `ingress.yaml` | Ingress for `chat.hag19.howes` (nginx + cert-manager TLS) |
| `kustomization.yaml` | ties them together |

## Deploy

```bash
kubectl apply -k kubernetes/ollama/
kubectl -n ai rollout status deploy/ollama
kubectl -n ai rollout status deploy/open-webui
```

Confirm Ollama landed on the GPU and is using it:

```bash
kubectl -n ai get pod -l app=ollama -o wide          # node = gpu-worker-1
ssh debian@192.168.1.127 'nvidia-smi'                # ollama process appears once a model loads
```

## Pull a model

```bash
kubectl -n ai exec deploy/ollama -- ollama pull llama3.1:8b
kubectl -n ai exec deploy/ollama -- ollama list
# quick GPU smoke test:
kubectl -n ai exec deploy/ollama -- ollama run llama3.1:8b "say hi in one word"
```

While it generates, `nvidia-smi` on the node should show the `ollama` process and
rising GPU/VRAM use.

## Reach the UI

- With DNS + ingress: open `https://chat.hag19.howes`.
- Without ingress yet (test locally):

```bash
kubectl -n ai port-forward svc/open-webui 8080:80
# browse http://localhost:8080
```

In the UI, models pulled into Ollama appear automatically (UI is pointed at
`http://ollama:11434` via `OLLAMA_BASE_URL`).

## Notes / constraints

- **One model at a time.** 8 GB VRAM can't hold two 7-8B Q4 models, hence
  `OLLAMA_MAX_LOADED_MODELS=1`. Pulling more is fine — only one loads at a time.
- **Auth is off** (`WEBUI_AUTH=false`) for a single-user homelab. Turn it on +
  set `WEBUI_SECRET_KEY` before exposing beyond the LAN.
- **Images are `:latest`/`:main`** for now; Phase 4 (GitOps) pins versions.
- **Ingress assumptions** (class `nginx`, ClusterIssuer `letsencrypt`) are noted
  in `ingress.yaml` — adjust to match the homelab, or drop the `tls:` block to
  start on plain HTTP.

## Next: Phase 3

Observability — Prometheus + Grafana scraping the DCGM exporter (already enabled
by the GPU Operator) for real GPU dashboards. Lands in `kubernetes/observability/`.
