mock_provider "google" {}

variables {
  project_id = "test-project"
  neg_zones  = ["us-central1-a", "us-central1-b"]
}

run "routes_to_all_neg_zones" {
  command = apply

  assert {
    condition     = length(google_compute_backend_service.greeter.backend) == 2
    error_message = "Every reported NEG zone must be attached."
  }
  assert {
    condition     = google_compute_backend_service.greeter.load_balancing_scheme == "INTERNAL_SELF_MANAGED" && google_compute_backend_service.greeter.protocol == "GRPC"
    error_message = "The backend must use the proxyless gRPC scheme."
  }
  assert {
    condition     = length(google_network_services_grpc_route.greeter.meshes) == 1 && google_network_services_grpc_route.greeter.meshes[0] == "projects/test-project/locations/global/meshes/utila-grpc"
    error_message = "The route must attach to the same mesh used by bootstrap."
  }
}
