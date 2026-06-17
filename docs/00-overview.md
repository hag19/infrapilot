# ai-platform — full project overview

A readable, end-to-end explanation of what this project is, why it's built the
way it is, what exists today, and where it's going. If you only read one doc,
read this one. For the hands-on Phase 1 commands, see
[`01-gpu-enablement.md`](01-gpu-enablement.md).

---

## 1. The one-paragraph version

`ai-platform` turns a spare consumer GPU (an NVIDIA RTX 3070) sitting in a
Proxmox homelab into a real, self-operating Kubernetes platform that serves
local LLMs. It passes the GPU through to a dedicated Kubernetes worker, shares
that one card across pods via time-slicing, runs Ollama + Open WebUI on it,
makes the whole thing observable (Prometheus/Grafana with real GPU metrics), 
manages it all declaratively with GitOps (ArgoCD), and finally puts an AI agent
on top that can diagnose and remediate the platform itself. It's a portfolio of
the full stack — cluster ops, SRE, CD, and LLMOps — built on real hardware.

---

## 2. Why this exists

Most "I deployed an LLM" projects stop at `docker run ollama`. This one is built
to demonstrate the *operations* around a GPU LLM service the way a platform/SRE
team would actually run it:

- **Real GPU, real passthrough.** Not a cloud rental — a physical RTX 3070
  passed through from a Proxmox hypervisor into a VM, the way you'd carve up
  bare metal in a datacenter.
- **Shared, not dedicated.** One consumer card, multiple workloads, via
  GPU time-slicing — the honest technique for a card with no MIG/vGPU support.
- **Observable.** GPU utilization, memory, temperature, and power exported to
  Prometheus and graphed in Grafana, alongside normal cluster metrics.
- **Declarative.** Everything lands in Git and is reconciled by ArgoCD, so the
  cluster state always matches the repo.
- **Self-operating.** An agent (InfraPilot) with read access to metrics and the
  cluster can explain incidents and propose/apply fixes.

---

## 3. How it relates to the homelab (the `proxmox` repo)

This is a **standalone repo** with its own Terraform state, Ansible playbooks,
and Kubernetes manifests. It sits *on top of* an already-built homelab that
lives in a separate `proxmox` repo (Terraform + Ansible + an HA Kubernetes
cluster + BIND DNS).

The rule: **ai-platform only adds; it never modifies the base.** It adds one GPU
worker node and the workloads that use it. Cluster bootstrap, control-plane HA,
DNS, and the cloud-init VM template all come from the `proxmox` repo and are
reused (e.g. that repo's `join-workers.yml` is what joins the new GPU node).

```
L5  InfraPilot agent  — MCP servers + LLM agent that diagnoses & remediates   (LLMOps/AIOps)
L4  GitOps            — ArgoCD app-of-apps, everything declarative            (CD)
L3  Observability     — Prometheus + Grafana + NVIDIA DCGM (GPU metrics)       (SRE)
L2  Workloads         — Ollama (GPU) + Open WebUI, Ingress + TLS              (app deploy)
L1  GPU enablement    — vfio passthrough + NVIDIA GPU Operator + time-slicing (cluster ops)
L0  Foundation        — Terraform + Ansible + HA K8s + BIND DNS  (proxmox repo, already built)
```

---

## 4. The hardware (verified 2026-06-17)

- **Proxmox host** `192.168.1.103`, PVE 9.1.4, AMD CPU.
  - IOMMU is **already active** (`amd_iommu=on iommu=pt`) and `nomodeset` is set,
    so no host GRUB/cmdline change is needed — a big simplification.
- **GPU**: NVIDIA GeForce RTX 3070 (GA104, **8 GB VRAM**) at PCI `0000:2b:00`.
  - VGA function `2b:00.0` = PCI ID `10de:2488`.
  - HDMI-audio function `2b:00.1` = PCI ID `10de:228b`.
  - The card sits **alone in IOMMU group 16** → clean passthrough, no ACS
    override hack required.
- **8 GB VRAM** comfortably fits 7–8B models at Q4 quantization:
  `llama3.1:8b`, `qwen2.5:7b`, `mistral:7b`.
- **GPU worker VM**: name `gpu-worker-1`, vmid **127**, IP **192.168.1.127**,
  cloud-init user `debian`. Cloned from template vmid **9000**.

---

## 5. How the GPU gets from the host into a pod

This is the heart of Phase 1. Four hops:

1. **Host → vfio-pci.** On the Proxmox host we tell the `vfio-pci` driver to
   claim the GPU's two PCI IDs, blacklist the host NVIDIA/nouveau drivers, and
   make vfio load at boot. After a reboot the host no longer touches the card —
   it's reserved for passthrough. (`ansible/01-host-vfio.yml`)

2. **Host → VM (PCI passthrough).** Terraform clones the cloud-init template
   into `gpu-worker-1` and attaches the whole PCI device (both functions) as a
   PCIe device. GPU passthrough requires the **q35** chipset and **OVMF (UEFI)**
   firmware, plus an EFI vars disk. (`terraform/gpu-worker.tf`)

3. **VM → kernel.** Inside the VM we install the NVIDIA driver (Debian-packaged,
   built via DKMS against the running kernel) and the NVIDIA container toolkit,
   then point containerd's runtime at it. Now `nvidia-smi` works in the guest
   and containerd can hand the GPU to pods. (`ansible/02-gpu-node-driver.yml`)

4. **Kernel → pods (sliced).** The NVIDIA **GPU Operator** runs in
   "driver/toolkit pre-installed" mode (we already did those at the node level),
   so it only manages the **device plugin**, **DCGM exporter** (metrics), and
   feature discovery. A **time-slicing** ConfigMap advertises the single card as
   **4 schedulable `nvidia.com/gpu` slices**, letting multiple pods share it.
   (`kubernetes/gpu-operator/`)

> ### Time-slicing vs. multi-GPU — the honest framing
> A consumer RTX 3070 has **no MIG and no vGPU**. The "4 GPUs" the node
> advertises are **cooperative time-slices of one physical card**, not isolated
> partitions. They share compute *and* the 8 GB of VRAM, so the real ceiling is
> memory: keep concurrent model loads modest. This project deliberately uses the
> accurate term **time-slicing** rather than overselling it as "distributed GPU".

---

## 6. Repository layout

```
ai-platform/
├── README.md                      project intro + phase table + quick runbook
├── docs/
│   ├── 00-overview.md             ← you are here (the full explanation)
│   └── 01-gpu-enablement.md       Phase 1 hands-on runbook + verification
├── terraform/                     GPU worker VM (own state, clones template 9000)
│   ├── provider.tf                bpg/proxmox provider, secrets via TF_VAR_*
│   ├── variables.tf               homelab-matching defaults
│   ├── gpu-worker.tf              the VM + PCI passthrough + cloud-init
│   └── terraform.tfvars.example   what to override
├── ansible/
│   ├── ansible.cfg / inventory.ini
│   ├── 01-host-vfio.yml           bind GPU to vfio-pci on the host (reboot gated)
│   └── 02-gpu-node-driver.yml     NVIDIA driver + container toolkit on the node
└── kubernetes/
    └── gpu-operator/
        ├── values.yaml            driver/toolkit OFF, DCGM ON, time-slicing default
        └── time-slicing-config.yaml   advertise the card as 4 nvidia.com/gpu slices
    (ollama/, observability/, argocd/, agent/ arrive in later phases)
```

---

## 7. Design decisions worth knowing

- **Node-level driver, not operator-managed driver.** Building the NVIDIA driver
  via the GPU Operator on a custom/Debian kernel is fragile. We install it on the
  node with Ansible (DKMS) and tell the operator to skip driver + toolkit. More
  reliable, easier to debug.
- **Reboots are gated.** Both playbooks default `allow_reboot=false`, so you can
  run them to write config and review before any disruptive reboot. Opt in with
  `-e allow_reboot=true`.
- **Secrets via `TF_VAR_*` from ansible-vault**, mirroring the `proxmox` repo —
  no tokens committed. `terraform.tfvars`, tfstate, vault pass, and keys are all
  gitignored.
- **Idempotent + labeled.** Config files written by Ansible are marked
  "Managed by ai-platform/…" so they're recognizable and safe to re-apply.
- **8 GB VRAM is the governing constraint.** Every later decision (model choice,
  number of concurrent pods, slice count) is bounded by it.

---

## 8. Phased build & status

| Phase | Layer | What it delivers | Status |
|-------|-------|------------------|--------|
| 1 | GPU enablement | vfio passthrough, GPU worker VM, GPU Operator + time-slicing | **Scaffolded** (not yet applied to live infra) |
| 2 | Workloads | Ollama on GPU + Open WebUI, Ingress + TLS | todo (next) |
| 3 | Observability | Prometheus + Grafana + NVIDIA DCGM GPU dashboards | todo |
| 4 | GitOps | ArgoCD app-of-apps, everything reconciled from Git | todo |
| 5 | InfraPilot agent | MCP servers + LLM agent that diagnoses & remediates, with evals | todo |

**Important honesty note:** Phase 1's code is written and internally consistent,
but as of this commit **nothing has been applied to the real host or cluster**.
The repo can't prove infra state — verify on the box before assuming a step ran.

---

## 9. How to run Phase 1 (summary)

Full version with verification in [`01-gpu-enablement.md`](01-gpu-enablement.md).

```bash
# 1. Bind GPU to vfio on the host (preview, then apply + reboot)
cd ansible
ansible-playbook 01-host-vfio.yml --check --diff
ansible-playbook 01-host-vfio.yml -e allow_reboot=true
ssh hag@192.168.1.103 'lspci -nnk -s 2b:00'         # expect: vfio-pci

# 2. Create the GPU worker VM
cd ../terraform && terraform init && terraform apply

# 3. Install driver + toolkit on the node
cd ../ansible
ansible-playbook 02-gpu-node-driver.yml -e allow_reboot=true
ssh debian@192.168.1.127 'nvidia-smi'               # expect: RTX 3070

# 4. Join the node (from the proxmox repo)
ansible-playbook join-workers.yml --limit gpu-worker-1

# 5. GPU Operator + time-slicing
helm repo add nvidia https://helm.ngc.nvidia.com/nvidia && helm repo update
kubectl apply -f kubernetes/gpu-operator/time-slicing-config.yaml
helm install gpu-operator nvidia/gpu-operator \
  -n gpu-operator --create-namespace -f kubernetes/gpu-operator/values.yaml
kubectl describe node gpu-worker-1 | grep nvidia.com/gpu   # expect: 4
```

---

## 10. What's next (Phase 2 preview)

Bring up the actual LLM service on the GPU:

- **Ollama** Deployment that requests `nvidia.com/gpu: 1` (one slice), with a
  PersistentVolumeClaim for pulled models so they survive restarts.
- **Open WebUI** Deployment + Service, pointed at Ollama, for a browser chat UI.
- **Ingress + TLS** so it's reachable at a hostname via the cluster's ingress
  controller (DNS already handled by the homelab's BIND).
- Pull a starter model (e.g. `llama3.1:8b`) and confirm it runs on the GPU
  (`nvidia-smi` shows the process, tokens stream in the UI).

Lands in `kubernetes/ollama/`.

---

*Maintained alongside `.claude/memory/project-context.md`, which is Claude's own
durable working memory for this repo (gitignored).*
