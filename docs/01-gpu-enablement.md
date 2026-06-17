# Phase 1 — GPU enablement runbook

Goal: take the RTX 3070 from "host console card" to "schedulable
`nvidia.com/gpu` resource in the cluster", shared by time-slicing.

```
host vfio bind ──▶ create gpu-worker VM (passthrough) ──▶ node driver+toolkit
       │                      │                                  │
   reboot host          terraform apply                    nvidia-smi works
                                                                 │
                                              join cluster ──▶ GPU Operator (device plugin + DCGM + time-slicing)
```

## Hardware facts (verified 2026-06-17)

- Proxmox host `192.168.1.103`, PVE 9.1.4, AMD CPU, IOMMU already active
  (`amd_iommu=on iommu=pt`, `nomodeset`). No host driver claims the card.
- GPU: NVIDIA GeForce RTX 3070 (GA104, 8 GB) at PCI `0000:2b:00`.
  - VGA fn `2b:00.0` = `10de:2488`, audio fn `2b:00.1` = `10de:228b`.
  - Alone in IOMMU group 16 → clean passthrough, no ACS override needed.
- 8 GB VRAM → 7–8B Q4 models (llama3.1:8b, qwen2.5:7b, mistral:7b).

## Step 1 — Bind the GPU to vfio-pci on the host

Writes `/etc/modprobe.d/{vfio,blacklist-gpu}.conf` + `/etc/modules-load.d/vfio.conf`,
rebuilds initramfs. A **host reboot** is required and detaches the GPU from the
host console — the reboot is gated behind `allow_reboot=true`.

```bash
cd ansible
ansible-playbook 01-host-vfio.yml --check --diff      # preview
ansible-playbook 01-host-vfio.yml                     # write config, no reboot
ansible-playbook 01-host-vfio.yml -e allow_reboot=true # write + reboot
```

Verify after reboot (both functions must show `vfio-pci`):

```bash
ssh hag@192.168.1.103 'lspci -nnk -s 2b:00'
# Kernel driver in use: vfio-pci
```

## Step 2 — Create the GPU worker VM

Clones template `9000`, attaches the whole PCI device (both functions) as PCIe,
q35 + OVMF. **Prereq: Step 1 done + host rebooted**, else attach fails.

```bash
cd terraform
# secrets via TF_VAR_* from ansible-vault (like the proxmox repo), or terraform.tfvars
terraform init
terraform plan
terraform apply
# output: ssh debian@192.168.1.127  # gpu-worker-1
```

## Step 3 — Install NVIDIA driver + container toolkit on the node

Driver installed at the node level (reliable on a custom kernel); the GPU
Operator runs later in driver/toolkit-preinstalled mode. Reboot gated.

```bash
cd ansible
ansible-playbook 02-gpu-node-driver.yml -e allow_reboot=true
```

Verify:

```bash
ssh debian@192.168.1.127 'nvidia-smi'   # lists the RTX 3070
```

## Step 4 — Join the node to the cluster

Reuse the `proxmox` repo's `join-workers.yml` against `gpu-worker-1`. This repo
never modifies the base cluster — it only adds the node and workloads.

```bash
# from the proxmox repo
ansible-playbook join-workers.yml --limit gpu-worker-1
kubectl get nodes -o wide   # gpu-worker-1 Ready
```

## Step 5 — Install the GPU Operator with time-slicing

Driver + toolkit are off in `values.yaml` (installed on the node). The operator
manages the device plugin, DCGM exporter (Phase 3 metrics), and feature discovery.
`time-slicing-config.yaml` advertises the one card as 4 `nvidia.com/gpu` slices.

```bash
helm repo add nvidia https://helm.ngc.nvidia.com/nvidia && helm repo update

kubectl create namespace gpu-operator
kubectl apply -f kubernetes/gpu-operator/time-slicing-config.yaml

helm install gpu-operator nvidia/gpu-operator \
  -n gpu-operator --create-namespace \
  -f kubernetes/gpu-operator/values.yaml
```

Verify the node advertises sliced GPUs:

```bash
kubectl describe node gpu-worker-1 | grep nvidia.com/gpu
# nvidia.com/gpu: 4   (one physical card, time-sliced)
```

> **Time-slicing, not multi-GPU.** A single consumer RTX 3070 has no true
> vGPU/MIG. The 4 slices are cooperative time-sharing of one card; VRAM (8 GB
> total) is the real limit, so keep concurrent model loads modest.

## Teardown / re-do

- Re-running any playbook is idempotent; configs are marked "Managed by ai-platform".
- To give the GPU back to the host: `terraform destroy` the VM, remove the
  `/etc/modprobe.d/*.conf` vfio files, rebuild initramfs, reboot.

## Next: Phase 2

Ollama (GPU) + Open WebUI → `kubernetes/ollama/`. See README phased build table.
