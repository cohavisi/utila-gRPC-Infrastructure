output "project_id" {
  value = var.project_id
}

output "project_number" {
  value = data.google_project.current.number
}

output "region" {
  value = var.region
}

output "zone" {
  value = var.zone
}

output "cluster_name" {
  value = google_container_cluster.main.name
}

output "mesh_name" {
  value = google_network_services_mesh.main.name
}

output "network_name" {
  value = google_compute_network.main.name
}

output "namespace" {
  value = "utila-grpc"
}

output "workload_service_accounts" {
  value = { for name, account in google_service_account.workload : name => account.email }
}

output "image_repository" {
  value = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.application.repository_id}/greeter"
}
