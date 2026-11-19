terraform {
  required_version = ">= 1.12, < 2.0"
  backend "gcs" {}
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "8.12.0"
    }
  }
}

provider "google" {
  project = var.project_id
}

data "google_compute_network_endpoint_group" "greeter" {
  for_each  = var.neg_zones
  self_link = "https://www.googleapis.com/compute/v1/projects/${var.project_id}/zones/${each.value}/networkEndpointGroups/${var.neg_name}"
}

resource "google_compute_health_check" "greeter" {
  name                = "${var.name}-grpc"
  check_interval_sec  = 5
  timeout_sec         = 5
  healthy_threshold   = 2
  unhealthy_threshold = 2
  grpc_health_check {
    port = 50052
  }
  log_config {
    enable = true
  }
}

resource "google_compute_backend_service" "greeter" {
  name                  = var.name
  protocol              = "GRPC"
  load_balancing_scheme = "INTERNAL_SELF_MANAGED"
  locality_lb_policy    = "ROUND_ROBIN"
  health_checks         = [google_compute_health_check.greeter.self_link]
  dynamic "backend" {
    for_each = data.google_compute_network_endpoint_group.greeter
    content {
      group                 = backend.value.self_link
      balancing_mode        = "RATE"
      max_rate_per_endpoint = 100
    }
  }
}

resource "google_network_services_grpc_route" "greeter" {
  name      = var.name
  hostnames = ["greeter.utila.internal:50051"]
  meshes    = ["projects/${var.project_id}/locations/global/meshes/${var.mesh_name}"]
  rules {
    action {
      destinations {
        service_name = google_compute_backend_service.greeter.id
        weight       = 100
      }
    }
  }
}

output "client_target" {
  value = "xds:///greeter.utila.internal:50051"
}
