variable "project_id" {
  description = "Existing billed GCP project; no project is selected implicitly."
  type        = string
}

variable "name" {
  type    = string
  default = "utila-grpc"
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{1,18}[a-z0-9]$", var.name))
    error_message = "Use 3-20 lowercase letters, digits or hyphens; begin with a letter and end with a letter or digit."
  }
}

variable "region" {
  type    = string
  default = "us-central1"
}

variable "zone" {
  type    = string
  default = "us-central1-a"
}

variable "admin_cidr" {
  description = "Trusted IPv4 /24-/32 allowed to access the Kubernetes control plane, normally your public IP/32."
  type        = string
  validation {
    condition     = can(cidrnetmask(var.admin_cidr)) && try(tonumber(split("/", var.admin_cidr)[1]) >= 24, false)
    error_message = "Provide a restricted IPv4 administrator CIDR with a /24-/32 prefix."
  }
}

variable "node_count" {
  type    = number
  default = 2
  validation {
    condition     = var.node_count >= 1 && var.node_count <= 3 && floor(var.node_count) == var.node_count
    error_message = "The demo supports 1-3 nodes."
  }
}

variable "deletion_protection" {
  description = "Disable with an explicit apply before intentionally destroying the demo cluster."
  type        = bool
  default     = true
}
