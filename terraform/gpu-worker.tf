# gpu-worker-1 — clones the existing cloud-init template (vmid 9000) and gets the
# RTX 3070 via PCI passthrough. q35 + OVMF are required for clean GPU passthrough.
#
# Prereq: the host must already have the GPU bound to vfio-pci
# (ansible/01-host-vfio.yml + reboot), otherwise apply will fail to attach it.

locals {
  ssh_keys = length(var.ssh_public_keys) > 0 ? [
    for k in var.ssh_public_keys : trimspace(k)
    ] : [
    trimspace(file(pathexpand(var.ssh_public_key_file)))
  ]
}

resource "proxmox_virtual_environment_vm" "gpu_worker" {
  name      = var.gpu_worker.name
  node_name = var.proxmox_node_name
  vm_id     = var.gpu_worker.vmid
  started   = true
  on_boot   = true

  # GPU passthrough needs the q35 chipset and OVMF (UEFI) firmware.
  machine = "q35"
  bios    = "ovmf"

  clone {
    vm_id = var.template_vmid
    full  = true
  }

  agent {
    enabled = true
  }

  cpu {
    cores = var.gpu_worker.cores
    type  = "host"
  }

  memory {
    dedicated = var.gpu_worker.memory
  }

  operating_system {
    type = "l26"
  }

  # OVMF requires an EFI vars disk.
  efi_disk {
    datastore_id = var.datastore_id
    type         = "4m"
  }

  # Pass the whole PCI device (both functions) through to the guest as PCIe.
  hostpci {
    device = "hostpci0"
    id     = var.gpu_pci_id
    pcie   = true
  }

  network_device {
    bridge = var.network_bridge
    model  = "virtio"
  }

  disk {
    datastore_id = var.datastore_id
    interface    = "scsi0"
    size         = var.gpu_worker.boot_disk_size
  }

  initialization {
    datastore_id = var.datastore_id

    ip_config {
      ipv4 {
        address = "${var.gpu_worker.ip}/${var.network_cidr_prefix}"
        gateway = var.network_gateway
      }
    }

    dns {
      servers = var.dns_servers
    }

    user_account {
      username = var.ci_user
      keys     = local.ssh_keys
    }
  }
}

output "gpu_worker" {
  value = "ssh ${var.ci_user}@${var.gpu_worker.ip}  # ${var.gpu_worker.name}"
}
