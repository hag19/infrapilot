terraform {
  required_version = ">=0.13.0"
  required_providers {
    proxmox = {
      source  = "bpg/proxmox"
      version = ">=0.60.0"
    }
  }
}

# Secrets (pm_api_url / token) are injected as TF_VAR_* from ansible-vault,
# exactly like ../../terraform. Everything else has a homelab-matching default.
provider "proxmox" {
  endpoint  = replace(var.pm_api_url, "/api2/json", "")
  api_token = "${var.pm_api_token_id}=${var.pm_api_token_secret}"
  insecure  = true

  ssh {
    agent       = false
    username    = var.pm_ssh_user
    private_key = file(pathexpand(var.pm_ssh_private_key))
  }
}
