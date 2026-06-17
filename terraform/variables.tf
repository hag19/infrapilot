# Self-contained vars for the GPU worker. Mirrors ../../terraform defaults so a
# bare `apply` works on this homelab; override in terraform.tfvars as needed.

# ---- Proxmox API (secrets, injected via TF_VAR_* from ansible-vault) -------
variable "pm_api_url" {
  type        = string
  description = "Proxmox API URL, e.g. https://192.168.1.103:8006/api2/json"
}

variable "pm_api_token_id" {
  type      = string
  sensitive = true
}

variable "pm_api_token_secret" {
  type      = string
  sensitive = true
}

# ---- SSH into the Proxmox host (bpg shells in for disk/clone ops) ----------
variable "pm_ssh_user" {
  type    = string
  default = "hag"
}

variable "pm_ssh_private_key" {
  type    = string
  default = "~/.ssh/id_rsa"
}

# ---- Placement / network (homelab defaults) --------------------------------
variable "proxmox_node_name" {
  type    = string
  default = "proxmox-node1"
}

variable "datastore_id" {
  type    = string
  default = "vm-storage"
}

variable "network_bridge" {
  type    = string
  default = "vmbr0"
}

variable "network_gateway" {
  type    = string
  default = "192.168.1.254"
}

variable "network_cidr_prefix" {
  type    = number
  default = 24
}

variable "dns_servers" {
  type    = list(string)
  default = ["192.168.1.167"]
}

# ---- Template + guest identity (clones the existing template 9000) ---------
variable "template_vmid" {
  type        = number
  default     = 9000
  description = "VMID of the cloud-init template (built by ../../terraform)."
}

variable "ci_user" {
  type    = string
  default = "debian"
}

variable "ssh_public_keys" {
  type    = list(string)
  default = []
}

variable "ssh_public_key_file" {
  type    = string
  default = "~/.ssh/id_rsa.pub"
}

# ---- GPU passthrough -------------------------------------------------------
variable "gpu_pci_id" {
  type        = string
  default     = "0000:2b:00"
  description = <<-EOT
    PCI address of the RTX 3070 on the host, WITHOUT a function suffix so both
    functions (VGA 2b:00.0 + audio 2b:00.1) pass through together. Confirm with
    `lspci -nn | grep -i nvidia` on the host. Used when creating the PCI mapping.
  EOT
}

variable "gpu_mapping" {
  type        = string
  default     = "rtx3070"
  description = <<-EOT
    Name of the Proxmox cluster PCI mapping for the GPU. Raw hostpci passthrough
    can only be set by root@pam; a mapped device is settable by an API token, so
    we map the device once on the host and reference it by name here.
  EOT
}

variable "gpu_worker" {
  type = object({
    name           = string
    vmid           = number
    ip             = string
    cores          = number
    memory         = number
    boot_disk_size = number
  })
  description = "The single GPU passthrough worker VM."
  default = {
    name           = "gpu-worker-1"
    vmid           = 127
    ip             = "192.168.1.127"
    cores          = 6
    memory         = 16384
    boot_disk_size = 80
  }
}
