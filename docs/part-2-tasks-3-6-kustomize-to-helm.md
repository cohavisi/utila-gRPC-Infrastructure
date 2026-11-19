# Part 2, Tasks 3-6: Helm Alternative and Migration

**Status:** the Helm alternative is locally rendered, parity-tested, and
schema-checked. The running demonstration remains Kustomize-managed. No live
Helm migration or zero-downtime guarantee is claimed.

The chart replaces **application manifest generation**, not Terraform or the
pinned Kustomize bootstrap of Argo CD itself.

## What stays the same

| Concern | Both versions |
| --- | --- |
| Cloud ownership | Terraform owns GKE, IAM, mesh, endpoint policy, backend, and route |
| Kubernetes ownership | The same Argo CD Application, `argocd/utila-grpc` |
| Workload identities | Namespace `utila-grpc`; service accounts `greeter-server` and `greeter-client` |
| Resource names | Deployments `greeter-server`/`greeter-client`, Service `greeter`, server PDB, and Namespace |
| Discovery | Standalone NEG `utila-grpc`, application port 50051, health port 50052 |
| Bootstrap | One completed generator init container, shared memory volume, read-only application mount |
| Runtime | Digest-pinned images, actual server/client xDS, private plaintext application traffic |

Helm uses ConfigMap `deployment-settings`, rather than Kustomize's
`deployment-settings-<hash>`. A pod-template checksum changes when settings
change. **The initial migration rolls both server and client Deployments**;
the original client's UID is not expected to survive it. Earlier evidence
describes the historical Kustomize run, not this migration.

## Files and local rendering

```text
gitops/helm/greeter/                 Helm chart, defaults, and values schema
gitops/helm/demo-values.yaml        Environment overrides
gitops/argocd/project.yaml          Shared restricted AppProject
gitops/argocd/application.yaml      Existing Kustomize Application
gitops/argocd/application-helm.yaml Alternative for the SAME Application
```

From the infrastructure repository, with Helm 4.3.x and the existing Python
validation dependencies installed:

```sh
helm lint gitops/helm/greeter --strict \
  --namespace utila-grpc --values gitops/helm/demo-values.yaml
helm template utila-grpc gitops/helm/greeter \
  --namespace utila-grpc --values gitops/helm/demo-values.yaml
.tmp/venv/bin/python scripts/check_manifests.py \
  --renderer both --require-configured
```

The installed Argo CD repo-server reports Helm 4.3.2; CI pins that version.
The chart's unconfigured defaults intentionally fail validation. Supply the
environment values file. The namespace is restricted to `utila-grpc` because
the Terraform Workload Identity bindings target that namespace.

Validation checks both configured renderers and compares Helm defaults with
the Kustomize baseline using equivalent image/environment inputs. Only the
ConfigMap name/reference and settings-checksum annotation are normalized.
Day-two Helm overrides belong in `demo-values.yaml`, not in chart defaults;
they may intentionally differ from the retained Kustomize baseline.

## Migrate the existing Argo CD deployment

### 1. Confirm context and capture the current identities

Use the isolated kubeconfig from the runbook. Confirm the context refers to
`gke_vast-maxim-388708_us-central1-a_utila-grpc` before making changes.

```sh
export PROJECT_ID="vast-maxim-388708"
export KUBECONFIG="$PWD/.tmp/kubeconfig"
kubectl config current-context
kubectl -n argocd get application utila-grpc
mkdir -p .tmp
kubectl -n argocd get application utila-grpc -o yaml > .tmp/pre-helm-application.yaml
export GREETER_SERVICE_UID="$(kubectl -n utila-grpc get service greeter -o jsonpath='{.metadata.uid}')"
export OLD_SETTINGS_CONFIGMAP="$(kubectl -n utila-grpc get deployment greeter-server -o jsonpath='{.spec.template.spec.initContainers[0].envFrom[0].configMapRef.name}')"
```

Do not delete the Application, Namespace, Service, or NEG. Do not run Helm
installation/adoption commands against the Argo-owned resources.

### 2. Generate values from the same platform and running image

Keep the initial migration separate from application-version changes.
The platform backend must already be initialized with access to its real state.

```sh
export IMAGE="$(kubectl -n utila-grpc get deployment greeter-server -o jsonpath='{.spec.template.spec.containers[0].image}')"
.tmp/venv/bin/python scripts/configure_demo.py --format helm --image="$IMAGE"
git diff -- gitops/helm/demo-values.yaml
```

The generator replaces image/settings only, preserving workload overrides.
Keep `namespace.create: true` for Argo CD so the Namespace remains in the
desired resource set. Review, commit, and push changes before proceeding.
If using a fork, update the shared AppProject and both Application repository
URLs; do not leave Argo CD reading the original repository.

### 3. Pause automatic sync, then change the source

```sh
kubectl -n argocd patch application utila-grpc --type merge \
  -p '{"spec":{"syncPolicy":{"automated":{"enabled":false}}}}'
kubectl apply -f gitops/argocd/project.yaml
kubectl apply -f gitops/argocd/application-helm.yaml
```

The alternative manifest also disables auto-sync initially. It changes the
existing Application source to `gitops/helm/greeter`, with release name
`utila-grpc` and values file `../demo-values.yaml`. There must not be a second
Application reconciling the same workloads.

### 4. Review the Argo CD diff and sync manually

In the Argo CD UI, refresh and inspect **Diff**. Expect the ConfigMap transition
and both pod-template changes. The Service name, selectors, NEG annotation,
ports, service accounts, Namespace, and server Deployment selector must remain
unchanged. Stop if anything proposes deleting/recreating the Service or Namespace.

Click **Sync with Prune unchecked**. Do not use force replacement, enable
auto-prune, or delete/recreate resources to bypass an error.

### 5. Verify the rollout and real RPCs

```sh
kubectl -n utila-grpc rollout status deployment/greeter-server --timeout=600s
kubectl -n utila-grpc rollout status deployment/greeter-client --timeout=600s
test "$(kubectl -n utila-grpc get service greeter -o jsonpath='{.metadata.uid}')" = "$GREETER_SERVICE_UID"
kubectl -n utila-grpc get pods
gcloud compute backend-services get-health utila-grpc \
  --global --project="$PROJECT_ID"
kubectl -n utila-grpc logs deployment/greeter-server -c server --tail=50
kubectl -n utila-grpc logs deployment/greeter-client -c client --since=1m
```

Require three ready servers, a ready client, healthy cloud endpoints, xDS
`SERVING`, and successful calls reaching multiple servers. Record observed
errors rather than assuming the rolling strategy guarantees zero loss.

### 6. Remove only the obsolete ConfigMap

Auto-prune stays disabled. The former hashed ConfigMap can leave the
Application OutOfSync even after the workloads are healthy.

Inspect every Pod's bootstrap reference:

```sh
kubectl -n utila-grpc get pods \
  -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.spec.initContainers[0].envFrom[0].configMapRef.name}{"\n"}{end}'
printf '%s\n' "$OLD_SETTINGS_CONFIGMAP"
```

Wait until old Pods are gone and all references are `deployment-settings`.
Only then remove the exact previously captured hashed ConfigMap:

```sh
test -n "$OLD_SETTINGS_CONFIGMAP" &&
  test "$OLD_SETTINGS_CONFIGMAP" != deployment-settings &&
  kubectl -n utila-grpc delete configmap "$OLD_SETTINGS_CONFIGMAP"
```

Do not prune the Service/NEG or Namespace. Refresh Argo CD and require
Healthy/Synced. The old ConfigMap can be recreated from Git if rollback is needed.

### 7. Enable the chosen steady-state policy

After acceptance, change
`gitops/argocd/application-helm.yaml`:

```yaml
automated:
  enabled: true
  prune: false
  selfHeal: true
```

Commit/push, then reapply that Application manifest. Future image, replica,
resource, and interval changes go through `gitops/helm/demo-values.yaml`.
Argo CD renders Helm templates and applies them; **it does not create a native
Helm release**, so `helm list` is not the deployment's source of truth.

## Rollback and eventual retirement

Keep the Kustomize files during acceptance. To return to that configuration,
review its image/replicas, then:

```sh
kubectl apply -f gitops/argocd/application.yaml
```

This restores the original source and its auto-sync policy. To preview rather
than immediately reconcile, explicitly set `automated.enabled: false` in that
manifest before applying it. Expect another rollout and recreation of the
hashed ConfigMap. Verify Service UID, backend health, and RPCs again; remove
the now-unused Helm ConfigMap only after no Pods reference it.

Retire application Kustomize directories only after acceptance: remove the
old Application option, update baseline-parity tests and CI to Helm-only
checks, and update teardown instructions in the same change. The separate
Argo CD installation bootstrap can remain Kustomize-based.

## Native Helm installation: a different ownership choice

Only for a fresh environment with **no Argo Application or existing conflicting
workloads**, after Terraform/image configuration:

```sh
helm upgrade --install utila-grpc gitops/helm/greeter \
  --namespace utila-grpc --create-namespace \
  --values gitops/helm/demo-values.yaml \
  --set namespace.create=false
```

Do not use `--wait` for the first installation: application readiness depends
on routing, whose backend depends on the Service-created NEG. Follow the
runbook's NEG-existence gate, apply Terraform routing, then wait for both
Deployment rollouts and verify RPCs. Subsequent upgrades can use
`--wait --timeout 10m`.

Here Helm creates the namespace and owns a release. This is not the assignment's
Argo CD delivery path. Do not use `--take-ownership`, `helm uninstall`, or
`helm upgrade` to manage the currently Argo-owned deployment.

For either renderer, retiring cloud resources still requires the
[ordered teardown](../README.md#teardown): stop reconciliation, detach cloud
routing, remove application resources, verify NEG cleanup, then destroy GKE.
For a native Helm release, use `helm uninstall utila-grpc --namespace utila-grpc`
at the application-removal step, after routing is destroyed.
