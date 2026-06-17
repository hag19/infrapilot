# ai-platform — GPU-accelerated, GitOps-managed K8s LLM platform

A self-operating Kubernetes platform on Proxmox that serves local LLMs on a real
GPU (NVIDIA RTX 3070), is fully observable, and is operated by an AI agent.

This is a **standalone repo** with its own Terraform state, Ansible playbooks,
Kubernetes manifests, and (later) the agent app. It builds *on top of* the
existing homelab (the separate `proxmox` repo: Terraform + Ansible + HA K8s +
BIND DNS) but never modifies it — it only adds a GPU node and workloads.

## Architecture (layers)

```
L5  InfraPilot agent  — MCP servers + LLM agent that diagnoses & remediates    (LLMOps/AIOps)
L4  GitOps            — ArgoCD app-of-apps, everything declarative             (CD)
L3  Observability     — Prometheus + Grafana + NVIDIA DCGM (GPU metrics)        (SRE)
L2  Workloads         — Ollama (GPU) + Open WebUI, Ingress + TLS               (app deploy)
L1  GPU enablement    — vfio passthrough + NVIDIA GPU Operator + time-slicing  (cluster ops)
L0  Foundation        — Terraform + Ansible + HA K8s + BIND DNS  (proxmox repo, already built)
```

## Hardware facts (verified 2026-06-17)

- Proxmox host `192.168.1.103`, PVE 9.1.4, **AMD CPU**, **IOMMU already active**
  (`amd_iommu=on iommu=pt`, `nomodeset` set — no host driver claims the card).
- GPU: **NVIDIA GeForce RTX 3070 (GA104, 8 GB)** at PCI `0000:2b:00`.
  - VGA fn `2b:00.0` = `10de:2488`, audio fn `2b:00.1` = `10de:228b`.
  - Sits alone in **IOMMU group 16** → clean passthrough, no ACS override.
- 8 GB VRAM fits 7–8B Q4 models well (llama3.1:8b, qwen2.5:7b, mistral:7b).

## GPU node

A dedicated `gpu-worker-1` (vmid **127**, IP **192.168.1.127**) gets the RTX 3070
via PCI passthrough (q35 + OVMF) and joins the existing cluster as a GPU node.
Single consumer GPU → no true vGPU; multi-pod sharing is done via the GPU
Operator's **time-slicing** (the accurate term — not "distributed GPU").

## Phased build

| Phase | Layer | Status |
|-------|-------|--------|
| 1 | GPU enablement (vfio + worker VM + GPU Operator) | in progress |
| 2 | Ollama + Open WebUI | todo |
| 3 | Observability (Prometheus/Grafana/DCGM) | todo |
| 4 | GitOps (ArgoCD) | todo |
| 5 | InfraPilot agent (MCP + evals + full-stack) | todo |

## Layout

```
ai-platform/
├── README.md
├── docs/                 architecture & runbooks
├── terraform/            GPU worker VM (own state, clones template 9000)
├── ansible/              host vfio prep + GPU node driver/toolkit
└── kubernetes/           gpu-operator / ollama / observability / argocd / agent
```

## Phase 1 runbook (summary — see docs/01-gpu-enablement.md)

1. `ansible-playbook ansible/01-host-vfio.yml` — bind GPU to vfio-pci on host.
   Requires a **host reboot** (detaches the GPU from the host console).
2. `cd terraform && terraform apply` — create `gpu-worker-1` with the GPU attached.
3. `ansible-playbook ansible/02-gpu-node-driver.yml` — NVIDIA driver + container toolkit.
4. Join the node to the cluster (reuse the `proxmox` repo's `join-workers.yml`).
5. `helm install` the NVIDIA GPU Operator with time-slicing (kubernetes/gpu-operator/).
