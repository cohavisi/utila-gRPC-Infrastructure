# Cloud Service Mesh infrastructure and GitOps

Companion to [utila-gRPC](https://github.com/cohavisi/utila-gRPC). Terraform owns
Google Cloud resources; Argo CD owns application Kubernetes resources; GKE's
standalone NEG controller owns pod endpoint membership.

> **Assignment scope:** "fully managed by ArgoCD" is interpreted here as
> application-level Kubernetes GitOps (Task 6). Terraform is applied separately
> for GCP provisioning and mesh routing (Task 3). Argo CD installation and its
> Application/AppProject are bootstrapped with `kubectl`, not self-managed.
> Argo-driven cloud provisioning is not implemented. This boundary is explicit,
> but evaluator acceptance of that interpretation is not assumed.

**Status:** deployed in `vast-maxim-388708`, `us-central1-a`, with real managed
client/server xDS. Argo CD is Healthy/Synced; three servers and the original
continuous client are running. Distribution, GitOps scale-out, pod replacement,
and server rollout are recorded in the [deployment evidence](docs/deployment-evidence.md),
with screenshots and an explicit account of initial discovery errors.
The [latest live evidence rerun](docs/part-2-tasks-3-6-live-evidence-20261119T152720Z.md)
includes five actual Argo CD screenshots with visible Pods, continuous RPC
logs, and a fully converged three-endpoint final state.
**Cloud resources remain running and billable.**

## Architecture and ownership

```text
Terraform platform -> private-node, zonal GKE + NAT + Artifact Registry + IAM
                   -> Cloud Service Mesh Mesh + GRPC_SERVER endpoint policy
Argo CD            -> three Go servers + one Go client + NEG-annotated Service
GKE NEG controller -> named zonal NEG containing server pod IPs:50051
Terraform routing  -> gRPC health check :50052 + backend service + GRPCRoute
Cloud Service Mesh -> client routing/endpoints and server Listener configuration
Go client          -> direct RPCs to Go server pods, without traffic sidecars
```

This uses **Google Cloud service-routing APIs**, not GKE Gateway API or Istio
configuration. See the application's
[integration decision](https://github.com/cohavisi/utila-gRPC/blob/main/docs/part-2-tasks-3-6-integration-decision.md).
The logical target is `xds:///greeter.utila.internal:50051`; no DNS record is
required for that target.

Application gRPC is intentionally **plaintext on private pod addresses**.
There is no public application LoadBalancer, no claim of application mTLS,
and no certificate-authority deployment. The Kubernetes API has a public
endpoint restricted to the configured administrator CIDR; nodes have private
IP addresses. Cloud NAT supplies outbound access for Argo CD and containers.
Health/admin port `50052` stays internal.

| Directory | Owner / purpose |
| --- | --- |
| `terraform/state` | One-time private, versioned state bucket bootstrap |
| `terraform/platform` | APIs, network, GKE, registry, separate client/server identities, mesh, inbound policy |
| `terraform/routing` | Looks up existing controller-created NEGs; creates health/backend/route |
| `gitops/base`, `gitops/overlays/demo` | Application desired state and environment configuration |
| `gitops/argocd/install` | Pinned Argo CD 3.6.2 bootstrap |
| `gitops/argocd/application.yaml` | Restricted AppProject and Kustomize Application |

Argo CD does **not** execute Terraform. The cloud states are applied explicitly;
the application is continuously reconciled from Git. Auto-prune is disabled
to protect the NEG lifecycle; deleting a Service needs the teardown sequence.
No custom Terraform plugin or `local-exec` hides this ownership boundary.

## Prerequisites

- An existing, billed GCP project with GKE/Compute quota and permissions to
  enable APIs, provision the listed resources, manage IAM, and upload images.
- Terraform **1.17.2**, Google Cloud CLI with `gke-gcloud-auth-plugin`, kubectl,
  Docker Buildx, Python 3, Git, and writable copies of both repositories checked
  out as siblings; see step 0.
- A trusted administrator IPv4 CIDR, normally your current public IP `/32`.
  The example CIDR is documentation-only; replace it.
- Service Usage API access for initial API enablement. Organization policies
  may require an administrator to enable APIs or approve service accounts.

**Costs:** this creates a billable Standard GKE cluster, two `e2-standard-2`
nodes, disks, Cloud NAT, Artifact Registry, and managed mesh resources. This is
a single-zone demonstration, not high availability. Destroy it when finished.
Do not run the following against an unrelated project.

## 0. Prepare writable repositories and the Argo CD source

For an independent deployment, fork **both** repositories into your GitHub
namespace before configuring another GCP project. From your chosen parent
directory, clone the forks as siblings:

```sh
export GITHUB_OWNER="YOUR_GITHUB_OWNER"
git clone "https://github.com/${GITHUB_OWNER}/utila-gRPC.git"
git clone "https://github.com/${GITHUB_OWNER}/utila-gRPC-Infrastructure.git"
cd utila-gRPC-Infrastructure
git remote get-url origin
```

In the existing `gitops/argocd/application.yaml`, update **both** repository
references, preserving the remaining configuration:

| Document | Field | Value for your deployment |
| --- | --- | --- |
| `AppProject/utila-grpc` | `spec.sourceRepos[0]` | `https://github.com/YOUR_GITHUB_OWNER/utila-gRPC-Infrastructure.git` |
| `Application/utila-grpc` | `spec.source.repoURL` | The same infrastructure fork URL |
| `Application/utila-grpc` | `spec.source.targetRevision` | Your deployment branch, normally `main` |

Use your actual GitHub owner in the URL. The AppProject allowlist and Application
URL must agree. Keep `spec.source.path: gitops/overlays/demo`. Push subsequent
configuration changes to the branch selected by `targetRevision`.
`scripts/configure_demo.py` updates the image and cloud settings only: it
**does not change these Git repository references**.

If you already maintain the supplied repositories and have write access, you
can keep their existing URLs. Do not retarget the running shared demonstration
to a fork merely to read its evidence. For private forks, register a read-only
repository credential in Argo CD outside Git before creating the Application.

## 1. Bootstrap state and platform

In this infrastructure repository:

```sh
export PROJECT_ID="YOUR_PROJECT_ID"
export TF_STATE_BUCKET="${PROJECT_ID}-utila-grpc-tfstate"
gcloud auth login
gcloud auth application-default login
gcloud auth application-default set-quota-project "$PROJECT_ID"
gcloud services enable serviceusage.googleapis.com --project="$PROJECT_ID"

terraform -chdir=terraform/state init
terraform -chdir=terraform/state apply \
  -var="project_id=$PROJECT_ID" -var="bucket_name=$TF_STATE_BUCKET"

cp terraform/platform/terraform.tfvars.example terraform/platform/terraform.tfvars
# Edit project_id and admin_cidr before proceeding.
terraform -chdir=terraform/platform init \
  -backend-config="bucket=$TF_STATE_BUCKET" -backend-config="prefix=utila-grpc/platform"
terraform -chdir=terraform/platform plan -out=platform.tfplan
terraform -chdir=terraform/platform apply platform.tfplan
```

Main states use the GCS backend's state locking and separate prefixes. Keep the
bootstrap stack's local state backed up securely; it manages the state bucket
itself. State files, credentials, plans, and real `.tfvars` are excluded from Git.
The bucket enforces uniform access and public-access prevention. It is not
force-deleted during cleanup.

Provider 8.12.0 currently warns that `remove_default_node_pool` is deprecated
for newer GKE releases. This conventional separate-node-pool configuration is
retained for Regular-channel compatibility; the warning is not live GKE
validation. Confirm the selected version is available in your zone.

## 2. Publish and pin the application image

After platform apply, in this repository:

```sh
export IMAGE_REPOSITORY="$(terraform -chdir=terraform/platform output -raw image_repository)"
export REGISTRY_HOST="${IMAGE_REPOSITORY%%/*}"
gcloud auth configure-docker "$REGISTRY_HOST"
export APP_REVISION="$(git -C ../utila-gRPC rev-parse HEAD)"
docker buildx build --platform linux/amd64 \
  --tag "${IMAGE_REPOSITORY}:${APP_REVISION}" --push ../utila-gRPC
gcloud artifacts docker images describe "${IMAGE_REPOSITORY}:${APP_REVISION}" \
  --project="$PROJECT_ID" --format='value(image_summary.digest)'
```

Commit the intended application source before assigning its Git SHA to an
image; otherwise that SHA would misidentify uncommitted code. These commands
assume the two repositories are siblings. Copy the returned digest:

```sh
python3 scripts/configure_demo.py \
  --image="${IMAGE_REPOSITORY}@sha256:PASTE_REAL_DIGEST"
```

The script reads **applied platform outputs**, supplies the project number,
network/mesh/cluster details and distinct workload identities, and pins the
image digest. It rejects mutable tags, zero digests, and another registry.
No cloud credentials are written to the manifests. The committed overlay is
configured for the demonstrated project; reconfigure it for a different
environment rather than deploying someone else's identities or image reference.

Review the two changed files under `gitops/overlays/demo` **and** the repository
references in `gitops/argocd/application.yaml` from step 0:

```sh
git -C ../utila-gRPC remote get-url origin
git remote get-url origin
git diff -- gitops/argocd/application.yaml gitops/overlays/demo
```

Commit and push the application source to your application repository and the
infrastructure configuration to the repository and branch selected by the
Application. Before bootstrapping Argo CD, confirm the configured overlay and
digest are visible on that GitHub branch. Argo CD cannot read local/unpushed
files; a correct local render does not prove it will read your fork.

## 3. Bootstrap Argo CD and create the standalone NEG

Install local validation dependencies as described below, then:

```sh
.tmp/venv/bin/python scripts/check_manifests.py --require-configured
gcloud container clusters get-credentials utila-grpc \
  --zone=us-central1-a --project="$PROJECT_ID"
kubectl config current-context
# Confirm the context points at this demo cluster.
kubectl apply --server-side -k gitops/argocd/install
kubectl -n argocd rollout status deployment/argocd-repo-server --timeout=300s
kubectl -n argocd rollout status statefulset/argocd-application-controller --timeout=300s
kubectl apply -f gitops/argocd/application.yaml
kubectl -n utila-grpc get service greeter -o yaml
```

Use platform outputs instead of the default cluster/zone above if customized.
The Argo CD server is ClusterIP; access it with
`kubectl -n argocd port-forward svc/argocd-server 8080:443`.
Retrieve the initial admin password from `argocd-initial-admin-secret` locally,
never commit or screenshot it, and change it after login.

Wait until `greeter` has a `cloud.google.com/neg-status` annotation containing
NEG `utila-grpc` and its actual zones. Verify the NEG exists in **every**
reported zone:

```sh
gcloud compute network-endpoint-groups describe utila-grpc \
  --zone=us-central1-a --project="$PROJECT_ID"
```

Do not replace this existence gate with an arbitrary sleep. **Do not wait for
the complete application rollout before applying routing:** client discovery
and NEG health may remain pending until the next stage exists. Terraform never
creates or independently manages these controller-owned NEGs.

## 4. Attach routing, then verify readiness

```sh
cp terraform/routing/terraform.tfvars.example terraform/routing/terraform.tfvars
# Set project_id, mesh_name from platform output, and ALL actual NEG zones.
terraform -chdir=terraform/routing init \
  -backend-config="bucket=$TF_STATE_BUCKET" -backend-config="prefix=utila-grpc/routing"
terraform -chdir=terraform/routing plan -out=routing.tfplan
terraform -chdir=terraform/routing apply routing.tfplan
kubectl -n utila-grpc rollout status deployment/greeter-server --timeout=600s
gcloud compute backend-services get-health utila-grpc --global --project="$PROJECT_ID"
kubectl -n utila-grpc logs deployment/greeter-client --since=2m
```

Expect healthy NEG endpoints and repeated successful `SayHello` calls with
multiple distinct `server_id` values. Initial discovery errors can occur before
routing is created; inspect a fresh, post-convergence time window separately.
Server logs must show xDS serving mode `SERVING`. A Running pod or open socket
alone is insufficient. Startup/liveness use the independent `liveness` health
service; readiness and Google backend health use default health reflecting xDS.

The bootstrap init image is amd64 and digest-pinned. Its explicit
`--node-metadata=app=greeter` matches the cloud server endpoint policy.
The client uses a different metadata value. Bootstrap is generated into an
in-memory volume and mounted read-only by the one application container.
Port `50052` also exposes CSDS/channelz for compatible internal diagnostic tools.

If anything fails, inspect init-container logs, server/client errors, IAM
bindings, Service NEG status, backend health, and Argo CD conditions. Do not
silently switch to DNS, a non-xDS server, or a sidecar to make the demo pass.

## 5. Reviewer evidence

The completed [evidence package](docs/deployment-evidence.md) includes actual
Argo CD UI and captured-data report screenshots, machine-readable observations,
and the measurement/transport limitations. The following is the reproduction
checklist:

Record observations and screenshots; do not substitute the local test results:

- Argo CD: `Synced` and `Healthy` at the intended pushed Git revision.
- Kubernetes: three ready servers, one client, one application container per pod,
  and a **completed init container**, not an Envoy/Linkerd traffic sidecar.
- Mesh: endpoint-policy match, server serving-mode logs, healthy NEG backends,
  and successful client calls to multiple pod hostnames.
- Scale-out: change server `replicas` from 3 to 5 **in Git**, commit/push, and
  observe new server IDs without replacing/restarting the client pod.
- Failure: delete one explicitly selected server pod; record any failed RPCs,
  recovery, and endpoint convergence. Do not promise zero errors.
- Rollout: change only the server pod-template annotation in Git; observe
  draining and client behavior while leaving the client pod/channel intact.

Check client pod UID/restart count before and after the latter experiments.
Do not use `kubectl scale` for the persistent scale-out demonstration: Argo CD's
self-healing would restore the Git-defined replica count. Restore three replicas
in Git after the experiment. Perfectly equal call counts are not required.

## Local checks and CI

```sh
python3 -m venv .tmp/venv
.tmp/venv/bin/python -m pip install -r scripts/requirements.txt
go install github.com/yannh/kubeconform/cmd/kubeconform@v0.7.0
export PATH="$(go env GOPATH)/bin:$PATH"
make check PYTHON=.tmp/venv/bin/python
```

Checks include Terraform formatting/schema validation, **mock-provider** tests
(including a mock-only routing apply), configuration-script tests, Kustomize
rendering, cross-resource wiring, Kubernetes 1.35 schemas for application
resources, and the pinned Argo CD CRD schemas for Application/AppProject.
They require internet access for providers, schemas, and pinned upstream Argo CD
manifests, but no GCP credentials or Kubernetes API access. CI performs these
checks; it does not provision infrastructure or execute a live cloud plan.
Use a fresh checkout for offline-backend checks if your working directory is
already initialized against a real GCS backend.

### CI security, Python lint, and coverage

On pushes and pull requests, additional CI checks run without cloud credentials:

- Gitleaks scans the complete fetched Git history with redacted findings and
  fails on detected secrets.
- Ruff checks Python code and import ordering with `ruff check scripts/`;
  `ruff format --check scripts/` enforces formatting. Rules are versioned in
  `ruff.toml`. Use `ruff format scripts/` to format locally.
- Trivy checks Terraform source, the fully rendered demo Kustomize workloads,
  and local Argo CD manifests. HIGH and CRITICAL misconfigurations fail CI;
  no exceptions are configured. Bases are not scanned as standalone workloads:
  the overlay supplies security settings required by the deployed configuration.

Trivy performs static analysis, not a live Terraform plan or cloud audit.
Required Terraform variables can remain unresolved in source scans, and remote
upstream Argo CD installation resources are outside this security scan.
Scanner versions are pinned and downloaded scanner archives are checksum
verified. Security scanning and Ruff remain CI checks, separate from the
pre-commit hook's existing checks.

`make check` measures Python unit-test coverage of scripts, excluding test files.
CI publishes XML and HTML reports as the **python-coverage** artifact for 14 days.
Download it from the workflow run's Artifacts section and open
`htmlcov/index.html`. There is no minimum threshold; low coverage remains
visible rather than being hidden by exclusions of untested application code.
The separate manifest-validation process is not counted as unit-test coverage.

### Pre-commit hook

After installing the check prerequisites above, enable the versioned hook once
per clone:

```sh
make install-hooks
```

Each commit checks staged files for whitespace errors and runs `make check` in
an isolated temporary snapshot. This covers Terraform formatting, validation
and mocked tests, Python unit tests, and Kubernetes schema/cross-resource
analysis. Failures block the commit; unstaged changes are not tested or modified.
The deployed checkout's Terraform initialization and state are not touched.
No live Terraform apply or GCP/Kubernetes mutation is performed.

The hook uses `.tmp/venv/bin/python` from the original checkout when available,
otherwise `python3`. Set `PYTHON` to an absolute interpreter path to override it.
Terraform, kubectl and kubeconform must be available; `KUBECONFORM` can specify
an absolute validator path. Provider/schema downloads require network access.
The hook does not install missing tools or dependencies, and CI remains the
authoritative shared check.

## Teardown

1. Stop Argo reconciliation by deleting only the Application:
   `kubectl -n argocd delete application utila-grpc`. There is deliberately no
   cascading-deletion finalizer, so this does not immediately delete the Service.
2. `terraform -chdir=terraform/routing destroy` first: removes the backend's
   references to the controller-owned NEGs.
3. `kubectl delete -k gitops/overlays/demo`; wait for NEG controller cleanup and
   verify `gcloud compute network-endpoint-groups list --project="$PROJECT_ID"`
   no longer lists this demo's NEGs. Inspect before deleting anything else.
4. Disable cluster deletion protection with an explicit platform apply:
   `terraform -chdir=terraform/platform apply -var=deletion_protection=false`.
   Then run
   `terraform -chdir=terraform/platform destroy -var=deletion_protection=false`.
   Registry images and the demo cluster are removed.
5. Retain the protected state bucket and securely backed-up bootstrap state
   unless intentionally retiring them. Deleting the bucket requires separately
   removing retained state versions; it is deliberately not automatic.

APIs remain enabled on destroy. Do not delete the cluster or Service first:
orphaned/in-use NEGs can block cleanup or leak billable resources.
