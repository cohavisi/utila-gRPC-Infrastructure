mock_provider "google" {}

variables {
  project_id = "test-project"
  admin_cidr = "203.0.113.10/32"
}

run "reject_public_administrator_access" {
  command = plan
  variables {
    admin_cidr = "0.0.0.0/0"
  }
  expect_failures = [var.admin_cidr]
}

run "private_proxyless_platform" {
  command = plan

  assert {
    condition     = google_container_cluster.main.private_cluster_config[0].enable_private_nodes
    error_message = "Workload nodes must not have public IPs."
  }
  assert {
    condition     = google_container_cluster.main.workload_identity_config[0].workload_pool == "test-project.svc.id.goog"
    error_message = "Workload Identity must use the selected project."
  }
  assert {
    condition     = google_network_services_endpoint_policy.server.type == "GRPC_SERVER"
    error_message = "The server needs an actual proxyless endpoint policy."
  }
  assert {
    condition     = google_compute_firewall.health.source_ranges == toset(["35.191.0.0/16", "130.211.0.0/22"])
    error_message = "Health-check access must stay scoped to the documented source ranges."
  }
}
