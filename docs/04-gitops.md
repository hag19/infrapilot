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
| `observability` | Helm `kube-prometheus-stack` + `$values` from the **base repo** `k8s/monitoring/values-monitoring.yaml` | Prometheus + Grafana |
| `observability-extras` | dir `kubernetes/observability` (SM + dashboard only) | DCGM scrape + GPU dashboard |

The two Helm apps use ArgoCD **multi-source**: source 1 is the chart repo, source
2 is a git repo referenced as `$values`, so committed values files drive the
chart. `gpu-operator` reads its values from *this* repo; `observability` is
shared cluster infra, so its values live in the **base homelab repo**
(`proxmox-k8s-ha`) and this app references them there — this repo deliberately
keeps no copy. The two `dir` apps use `directory.include` to pick only the real
k8s manifests out of folders that also contain Helm values files.

## Day-2: change-by-PR

Edit a manifest/value, commit to `main`, push. ArgoCD auto-syncs (or
`argocd app sync <app>`). `selfHeal: true` reverts manual drift; `prune: true`
deletes resources you remove from git. To pause automation on an app, set
`syncPolicy.automated` to `{}` or use `argocd app set <app> --sync-policy none`.

## Notes

- **Chart versions are pinned to the live releases.** `gpu-operator.yaml` →
  `v24.3.0` (matches node driver 550), `observability.yaml` → `86.2.0` (the
  running `monitoring` release). Re-check before bumping:
  `helm search repo <chart> --versions`. Adopting a release with a mismatched
  pin would diff against everything and trigger a full re-render — keep the pin
  equal to `helm -n <ns> list` until you intend to upgrade.
- **Repo URLs.** Most apps read from `https://github.com/hag19/infrapilot.git`;
  `observability` reads its `$values` from the base repo
  `https://github.com/hag19/proxmox-k8s-ha.git`. If you fork/rename, update them.
- **Bootstrapping note.** GPU Operator and kube-prometheus-stack install their
  own CRDs; `ServerSideApply=true` is set on both to handle the large CRD schemas.

## Adopting hand-installed releases into ArgoCD

Some layers were brought up live with `helm install` before ArgoCD existed
(see the internal deploy log). To put them under GitOps you must **hand the
release over without recreating the running objects**.

**Why this needs care.** ArgoCD uses Helm only as a *template engine* — it runs
the equivalent of `helm template` and then owns the rendered objects directly.
It does **not** take over Helm's release record. So if you just point an
ArgoCD app at a chart you already `helm install`ed, two managers fight over the
same objects. The clean handoff: make git reproduce what's live, drop Helm's
release record (leaving the objects running), then let ArgoCD adopt them
in place with server-side apply — no pod restarts.

> Note: the platform now runs under the `root-app.yaml` app-of-apps (the
> `ai-platform` Application), which renders every child under
> `kubernetes/argocd/apps/` from git and self-heals them. The `agent` app is
> excluded (`directory.exclude: agent.yaml`) until its image exists. Adoption was
> done per child app first; once a child is `Synced`, the root app keeps it that
> way — so don't hand-edit child Applications, change them in git.

### gpu-operator (no config conflict — safe)

The ArgoCD app already pins the live version (`v24.3.0`) and uses the same
`$values/kubernetes/gpu-operator/values.yaml`, so the render matches what's
running and adoption is a no-op diff.

```bash
# 0. Pre-checks: confirm the live release and that git reproduces it.
helm -n gpu-operator list                          # release gpu-operator, v24.3.0
helm -n gpu-operator get values gpu-operator \
  | diff - kubernetes/gpu-operator/values.yaml     # should be empty/expected
kubectl -n argocd get applications                 # gpu-operator app NOT present yet

# 1. Drop Helm's release record WITHOUT deleting the workloads.
#    (Deletes only the release-state Secret; every running object stays put.
#    Do NOT `helm uninstall` — that deletes the operator and drops the GPU.)
kubectl -n gpu-operator delete secret -l owner=helm,name=gpu-operator

# 2. Hand it to ArgoCD. ServerSideApply (already set on this app) lets ArgoCD
#    take field ownership of the existing objects in place.
kubectl apply -f kubernetes/argocd/apps/gpu-operator.yaml
argocd app sync gpu-operator        # or wait for auto-sync
argocd app get gpu-operator         # Synced / Healthy, no resource recreation

# 3. Verify nothing restarted and the GPU is still schedulable.
kubectl -n gpu-operator get pods
kubectl get node gpu-worker-1.first-cluster.hag19.howes \
  -o jsonpath='{.status.allocatable.nvidia\.com/gpu}'      # still 4
```

**Rollback (detach, keep it running).** The child apps carry no finalizer, so
deleting the Application leaves the resources in place:

```bash
kubectl -n argocd delete app gpu-operator    # objects keep running, now Helm-orphaned
# optional: re-establish Helm ownership
helm upgrade --install gpu-operator nvidia/gpu-operator --version v24.3.0 \
  -n gpu-operator -f kubernetes/gpu-operator/values.yaml
```

### observability / kube-prometheus-stack (shared infra, base repo owns it)

This is the `monitoring` release (chart `kube-prometheus-stack-86.2.0`) that
monitors the *whole* homelab — not just the AI platform. It is owned by the base
repo (`proxmox-k8s-ha`, `k8s/monitoring/values-monitoring.yaml`). The
`apps/observability.yaml` app references those values via `$values`; this repo
keeps no copy. Two extra hazards beyond the gpu-operator case:

1. **The base repo gitignored `k8s/`** — its values file was never committed, so
   ArgoCD can't read it yet. (`.gitignore` is patched to un-ignore just
   `k8s/monitoring/values-monitoring.yaml`; it still needs to be committed +
   pushed to `proxmox-k8s-ha`.)
2. **Immutable selector labels.** ArgoCD's default tracking sets
   `app.kubernetes.io/instance` to the *Application name* (`observability`), but
   the live objects carry `instance=monitoring` from Helm — and on Deployments
   that label is part of the **immutable** selector, so a sync would fail. Avoid
   this by switching ArgoCD to annotation-based tracking (cluster-wide, once).

```bash
# 0. PREREQ: commit + push the values file in the BASE repo so ArgoCD can read it.
cd ~/proxmox
git add k8s/monitoring/values-monitoring.yaml .gitignore
git commit -m "Track monitoring values (source of truth for ArgoCD)"
git push                     # ai-platform's observability app reads it from here
# If proxmox-k8s-ha is PRIVATE, give ArgoCD read access first:
#   argocd repo add https://github.com/hag19/proxmox-k8s-ha.git --username … --password …

# 1. Switch ArgoCD to annotation tracking so it won't rewrite the immutable
#    app.kubernetes.io/instance selector label on the live Helm objects.
kubectl -n argocd patch cm argocd-cm --type merge \
  -p '{"data":{"application.resourceTrackingMethod":"annotation"}}'
kubectl -n argocd rollout restart deploy/argocd-application-controller

# 2. Confirm the live release and that the app is pinned to match it.
helm -n monitoring list      # release "monitoring", chart kube-prometheus-stack-86.2.0
#   apps/observability.yaml pins targetRevision 86.2.0 + helm.releaseName monitoring.

# 3. Drop Helm's release record WITHOUT deleting the running stack.
kubectl -n monitoring delete secret -l owner=helm,name=monitoring

# 4. Hand it to ArgoCD (ServerSideApply already set).
kubectl apply -f kubernetes/argocd/apps/observability.yaml
argocd app diff observability        # review BEFORE syncing — expect ~no changes
argocd app sync observability
argocd app get observability         # Synced / Healthy, nothing recreated

# 5. Verify the stack is intact and our GPU extras still scrape.
kubectl -n monitoring get pods
# DCGM target up (its ServiceMonitor now carries release: monitoring in git):
kubectl apply -f kubernetes/argocd/apps/observability-extras.yaml
```

**Rollback:** `kubectl -n argocd delete app observability` (no finalizer → leaves
the stack running, Helm-orphaned); re-adopt with
`helm upgrade --install monitoring prometheus-community/kube-prometheus-stack
--version 86.2.0 -n monitoring -f ~/proxmox/k8s/monitoring/values-monitoring.yaml`.

> The `monitoring` release is shared with the base homelab. Once ArgoCD owns it,
> stop running `helm upgrade` on it by hand — change it by editing the values in
> `proxmox-k8s-ha` and pushing. That repo is now the source of truth either way.

## Next: Phase 5

InfraPilot agent — MCP servers (Prometheus, Kubernetes) + an LLM agent that reads
the metrics this phase exposes, diagnoses incidents, and proposes/applies fixes,
with an eval harness. Lands in `kubernetes/agent/` + an app source.
