# Phase 4 — GitOps with ArgoCD runbook

Goal: stop running `helm install` / `kubectl apply` by hand. ArgoCD reconciles
the whole platform from this git repo; the cluster always matches `main`.

```
this repo (main)
      │  watched by
      ▼
ArgoCD ── root app "ai-platform" (app-of-apps, kubernetes/argocd/apps/)
            ├── gpu-operator           (Helm, wave 0)
            ├── gpu-operator-config    (time-slicing CM, wave 1)
            ├── ollama                 (kustomize, wave 1)
            ├── observability          (kube-prometheus-stack Helm, wave 0)
            └── observability-extras   (DCGM ServiceMonitor + dashboard, wave 1)
```

**Sync waves** order things: wave 0 installs the operators + their CRDs
(GPU Operator, Prometheus operator); wave 1 applies the resources that depend on
them (time-slicing ConfigMap, GPU workloads, ServiceMonitor).

## 1. Install ArgoCD

```bash
kubectl create namespace argocd
kubectl apply -n argocd -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml
kubectl -n argocd rollout status deploy/argocd-server

# initial admin password:
kubectl -n argocd get secret argocd-initial-admin-secret \
  -o jsonpath='{.data.password}' | base64 -d; echo
```

UI (optional): `kubectl -n argocd port-forward svc/argocd-server 8080:443`
→ https://localhost:8080 (user `admin`).

> If this repo is **private**, add repo credentials to ArgoCD first
> (`argocd repo add https://github.com/hag19/infrapilot.git --username … --password …`
> or a Secret labeled `argocd.argoproj.io/secret-type: repository`). It's public
> as set up here, so no creds are needed.

## 2. Apply the root app

```bash
kubectl apply -f kubernetes/argocd/root-app.yaml
```

That's the only manual `kubectl apply` from here on. ArgoCD discovers the five
child Applications and syncs them (automated, with prune + selfHeal).

## 3. Watch it converge

```bash
kubectl -n argocd get applications
# or: argocd app list ; argocd app get ai-platform
```

All apps should reach `Synced / Healthy`. Then verify the layers exactly as in
the earlier phases:

```bash
kubectl describe node gpu-worker-1 | grep nvidia.com/gpu   # 4 slices (Phase 1/3)
kubectl -n ai get pods                                      # ollama + open-webui (Phase 2)
kubectl -n monitoring get pods                              # prometheus + grafana (Phase 3)
```

## How it maps to the repo

| Child app | Source | Deploys |
|-----------|--------|---------|
| `gpu-operator` | Helm `nvidia/gpu-operator` + `$values/kubernetes/gpu-operator/values.yaml` | device plugin, DCGM, feature discovery |
| `gpu-operator-config` | dir `kubernetes/gpu-operator` (only `time-slicing-config.yaml`) | 4-slice ConfigMap |
| `ollama` | kustomize `kubernetes/ollama` | Ollama + Open WebUI + Ingress |
| `observability` | Helm `kube-prometheus-stack` + `$values/kubernetes/observability/values.yaml` | Prometheus + Grafana |
| `observability-extras` | dir `kubernetes/observability` (SM + dashboard only) | DCGM scrape + GPU dashboard |

The two Helm apps use ArgoCD **multi-source**: source 1 is the chart repo, source
2 is this git repo referenced as `$values`, so our committed values files drive
the chart. The two `dir` apps use `directory.include` to pick only the real k8s
manifests out of folders that also contain Helm values files.

## Day-2: change-by-PR

Edit a manifest/value, commit to `main`, push. ArgoCD auto-syncs (or
`argocd app sync <app>`). `selfHeal: true` reverts manual drift; `prune: true`
deletes resources you remove from git. To pause automation on an app, set
`syncPolicy.automated` to `{}` or use `argocd app set <app> --sync-policy none`.

## Notes

- **Pin chart versions.** `gpu-operator.yaml` and `observability.yaml` carry
  placeholder `targetRevision`s — verify with
  `helm search repo <chart> --versions` and pin to known-good ones.
- **Repo URL** is hardcoded to `https://github.com/hag19/infrapilot.git` in every
  app. If you fork/rename, update them (root + all apps).
- **Bootstrapping note.** GPU Operator and kube-prometheus-stack install their
  own CRDs; `ServerSideApply=true` is set on both to handle the large CRD schemas.

## Next: Phase 5

InfraPilot agent — MCP servers (Prometheus, Kubernetes) + an LLM agent that reads
the metrics this phase exposes, diagnoses incidents, and proposes/applies fixes,
with an eval harness. Lands in `kubernetes/agent/` + an app source.
