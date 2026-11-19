locals {
  apis = toset([
    "artifactregistry.googleapis.com",
    "cloudresourcemanager.googleapis.com",
    "compute.googleapis.com",
    "container.googleapis.com",
    "iam.googleapis.com",
    "iamcredentials.googleapis.com",
    "logging.googleapis.com",
    "monitoring.googleapis.com",
    "networkservices.googleapis.com",
    "serviceusage.googleapis.com",
    "sts.googleapis.com",
    "trafficdirector.googleapis.com",
  ])
}

resource "google_project_service" "api" {
  for_each           = local.apis
  service            = each.value
  disable_on_destroy = false
}

data "google_project" "current" {
  depends_on = [google_project_service.api]
}

resource "google_compute_network" "main" {
  name                    = var.name
  auto_create_subnetworks = false
  depends_on              = [google_project_service.api]
}

resource "google_compute_subnetwork" "main" {
  name                     = var.name
  region                   = var.region
  network                  = google_compute_network.main.id
  ip_cidr_range            = "10.10.0.0/20"
  private_ip_google_access = true
  secondary_ip_range {
    range_name    = "pods"
    ip_cidr_range = "10.20.0.0/16"
  }
  secondary_ip_range {
    range_name    = "services"
    ip_cidr_range = "10.30.0.0/20"
  }
}

resource "google_compute_router" "main" {
  name    = var.name
  region  = var.region
  network = google_compute_network.main.id
}

resource "google_compute_router_nat" "main" {
  name                                = var.name
  router                              = google_compute_router.main.name
  region                              = var.region
  nat_ip_allocate_option              = "AUTO_ONLY"
  source_subnetwork_ip_ranges_to_nat  = "LIST_OF_SUBNETWORKS"
  enable_endpoint_independent_mapping = false
  enable_dynamic_port_allocation      = true
  min_ports_per_vm                    = 64
  max_ports_per_vm                    = 1024
  subnetwork {
    name                    = google_compute_subnetwork.main.id
    source_ip_ranges_to_nat = ["ALL_IP_RANGES"]
  }
}

resource "google_artifact_registry_repository" "application" {
  location      = var.region
  repository_id = var.name
  format        = "DOCKER"
  depends_on    = [google_project_service.api]
}

resource "google_service_account" "node" {
  account_id = "${var.name}-node"
  depends_on = [google_project_service.api]
}

resource "google_project_iam_member" "node" {
  role    = "roles/container.defaultNodeServiceAccount"
  member  = "serviceAccount:${google_service_account.node.email}"
  project = var.project_id
}

resource "google_artifact_registry_repository_iam_member" "pull" {
  project    = var.project_id
  location   = var.region
  repository = google_artifact_registry_repository.application.name
  role       = "roles/artifactregistry.reader"
  member     = "serviceAccount:${google_service_account.node.email}"
}

resource "google_container_cluster" "main" {
  name                     = var.name
  location                 = var.zone
  network                  = google_compute_network.main.id
  subnetwork               = google_compute_subnetwork.main.id
  initial_node_count       = 1
  remove_default_node_pool = true
  deletion_protection      = var.deletion_protection
  networking_mode          = "VPC_NATIVE"
  node_config {
    service_account = google_service_account.node.email
    oauth_scopes    = ["https://www.googleapis.com/auth/cloud-platform"]
  }
  release_channel {
    channel = "REGULAR"
  }
  ip_allocation_policy {
    cluster_secondary_range_name  = "pods"
    services_secondary_range_name = "services"
  }
  private_cluster_config {
    enable_private_nodes    = true
    enable_private_endpoint = false
    master_ipv4_cidr_block  = "172.16.0.0/28"
  }
  master_authorized_networks_config {
    cidr_blocks {
      cidr_block   = var.admin_cidr
      display_name = "administrator"
    }
  }
  workload_identity_config {
    workload_pool = "${var.project_id}.svc.id.goog"
  }
  addons_config {
    http_load_balancing {
      disabled = false
    }
  }
  logging_service    = "logging.googleapis.com/kubernetes"
  monitoring_service = "monitoring.googleapis.com/kubernetes"
  lifecycle {
    precondition {
      condition     = startswith(var.zone, "${var.region}-")
      error_message = "zone must belong to region."
    }
  }
  depends_on = [google_compute_router_nat.main, google_project_iam_member.node]
}

resource "google_container_node_pool" "main" {
  name       = "workloads"
  cluster    = google_container_cluster.main.name
  location   = var.zone
  node_count = var.node_count
  management {
    auto_repair  = true
    auto_upgrade = true
  }
  node_config {
    machine_type    = "e2-standard-2"
    disk_size_gb    = 30
    disk_type       = "pd-balanced"
    image_type      = "COS_CONTAINERD"
    service_account = google_service_account.node.email
    oauth_scopes    = ["https://www.googleapis.com/auth/cloud-platform"]
    tags            = ["${var.name}-nodes"]
    workload_metadata_config {
      mode = "GKE_METADATA"
    }
    shielded_instance_config {
      enable_secure_boot          = true
      enable_integrity_monitoring = true
    }
  }
  depends_on = [google_artifact_registry_repository_iam_member.pull]
}

resource "google_service_account" "workload" {
  for_each   = toset(["greeter-server", "greeter-client"])
  account_id = "${var.name}-${each.key == "greeter-server" ? "server" : "client"}"
  depends_on = [google_project_service.api]
}

resource "google_project_iam_member" "xds" {
  for_each = google_service_account.workload
  project  = var.project_id
  role     = "roles/trafficdirector.client"
  member   = "serviceAccount:${each.value.email}"
}

resource "google_service_account_iam_member" "identity" {
  for_each           = google_service_account.workload
  service_account_id = each.value.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "serviceAccount:${var.project_id}.svc.id.goog[utila-grpc/${each.key}]"
  depends_on         = [google_container_cluster.main]
}

resource "google_network_services_mesh" "main" {
  name       = var.name
  depends_on = [google_project_service.api]
}

resource "google_network_services_endpoint_policy" "server" {
  name = "${var.name}-server"
  type = "GRPC_SERVER"
  traffic_port_selector {
    ports = ["50051"]
  }
  endpoint_matcher {
    metadata_label_matcher {
      metadata_label_match_criteria = "MATCH_ALL"
      metadata_labels {
        label_name  = "app"
        label_value = "greeter"
      }
    }
  }
  depends_on = [google_project_service.api]
}

resource "google_compute_firewall" "health" {
  name          = "${var.name}-health"
  network       = google_compute_network.main.id
  source_ranges = ["35.191.0.0/16", "130.211.0.0/22"]
  target_tags   = ["${var.name}-nodes"]
  allow {
    protocol = "tcp"
    ports    = ["50052"]
  }
}
