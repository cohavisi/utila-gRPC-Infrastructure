variable "project_id" {
  type = string
}

variable "name" {
  type    = string
  default = "utila-grpc"
}

variable "mesh_name" {
  type    = string
  default = "utila-grpc"
}

variable "neg_name" {
  type    = string
  default = "utila-grpc"
}

variable "neg_zones" {
  description = "Use the zones reported by the Kubernetes Service NEG status annotation."
  type        = set(string)
  validation {
    condition     = length(var.neg_zones) > 0
    error_message = "Provide at least one actual NEG zone."
  }
}
