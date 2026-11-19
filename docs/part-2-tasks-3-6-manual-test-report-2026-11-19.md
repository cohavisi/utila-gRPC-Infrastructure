# Part 2, Tasks 3-6: Manual Test Report, 2026-11-19

**Run:** `evidence-20261119T135844Z`. All times below are **UTC**.
This report analyzes the operator's supplied manual-test captures; it does not
represent a new deployment, an independently repeated experiment, or a fresh
cloud-state check. A separately dated read-only follow-up is included below;
it does not change the original experiment measurements.

**Subsequent change:** Helm support and its parity checks have been removed;
Kustomize is now the sole supported deployment path. The historical CI failure
at `e56f211` remains recorded below, but restoring inactive Helm defaults is no
longer required. The original backend-health captures and screenshot
qualification are unchanged; the
[backend-cleanup follow-up](#backend-cleanup-follow-up-2026-11-19-1510-utc)
records subsequent removal of the retired entries.
Removal was published in
[`11258a5`](https://github.com/cohavisi/utila-gRPC-Infrastructure/commit/11258a5),
and its [Kustomize-only CI run passed](https://github.com/cohavisi/utila-gRPC-Infrastructure/actions/runs/44549218928).

## Executive assessment

The captured Kustomize deployment demonstrated three-server balancing,
Git-controlled scale-out to five servers, replacement of one server, a
five-server rolling update, and restoration to three servers. Across the
five non-overlapping captured log segments, **4,435 distinct RPCs succeeded
and zero RPC failures were recorded**. The original client retained its UID
and zero application-container restarts.

The result is a **qualified runtime pass**, not an unconditional completion
claim. Three qualifications were identified in the recorded run; the subsequent
removal of Helm support resolves the second, and the separately dated backend
follow-up closes the first, without rewriting that history:

1. The final backend snapshot has three healthy current endpoints **and five
   unhealthy retired endpoints**. Their eventual removal was not captured.
2. The restoration commit left inactive Helm defaults inconsistent with
   Kustomize, and its CI run failed the renderer-parity check.
3. This directory contains no screenshots. The earlier deployment's images
   must not be relabeled as screenshots of this manual run.

The live application source stayed `gitops/overlays/demo` in every captured
Argo CD Application. **Helm was not deployed.**

## Evidence and method

Source directory, relative to the infrastructure repository:

```text
.tmp/evidence-20261119T135844Z/
```

The analysis inspected all **42 supplied artifacts**: five client log files,
ten before/after pod lists, five backend-health snapshots, six Application
snapshots including the initial state, ten start/end markers, two client
identity snapshots, two Git revision files, the deleted-pod name, and server
startup logs.

The derived [machine-readable verification](evidence/manual-20261119T135844Z/verification.json)
contains exact timestamps, call-number ranges, per-server counts, pod UIDs,
health-to-pod attribution, Git revisions, and SHA-256 hashes of all inputs.
Original captures remain in the ignored source directory; the derived JSON
is a reduced analysis, **not an included raw-capture archive**. Preserve the
source directory for a full local audit. Hashes identify the analyzed files;
they do not independently authenticate how those files were captured.

Counts were recomputed from `SayHello succeeded` and `SayHello failed` records.
Every file has a contiguous, increasing call-number range with no duplicate
calls, and the five files do not overlap. Backend IPs were matched locally to
before/after Pod IPs; the published summary identifies pods without duplicating
private IP addresses or full Kubernetes API metadata.

## Environment and client continuity

| Property | Captured/configured value |
| --- | --- |
| Project / cluster / zone | `vast-maxim-388708` / `utila-grpc` / `us-central1-a` |
| Namespace | `utila-grpc` |
| Argo CD Application | `argocd/utila-grpc` |
| Active renderer | Kustomize, `gitops/overlays/demo` |
| Client target | `xds:///greeter.utila.internal:50051` |
| Client Pod | `greeter-client-5dbd98b6cc-kjh9l` |
| Client UID | `7487a0b7-730b-49fb-aa26-85584674f5da` |
| Client container restarts | `0` before, after, and in every experiment pod snapshot |
| Client settings | Continuous calls; interval `250ms`; per-call timeout `10s` |

`client-before.json` and `client-after.json` are byte-for-byte identical.
The same UID and zero restart count also appear in all ten experiment pod
snapshots. This supports discovery and recovery through the existing client,
rather than success obtained by replacing it.

The image remained:

```text
us-central1-docker.pkg.dev/vast-maxim-388708/utila-grpc/greeter@sha256:0c0c3efd3609af7d3e58e6c8fb3c085bbec85f173cd2e027c63ba717b86bc862
```

Every captured application pod was Ready, had one application container,
and had a completed `xds-bootstrap` init container with exit code zero.
This supports the proxyless deployment claim at the captured boundaries.
No node inventory or fresh network/IAM audit was supplied in this run.

## Measured outcomes

The intervals below show the first and last **captured RPC records**, displayed
to whole seconds. Exact fractional timestamps and separately recorded test
start/end times are retained in the JSON.

| Experiment | Captured RPC interval | Successful / failed | Distinct server IDs | Ready servers after | Healthy / unhealthy backend entries |
| --- | --- | --- | --- | --- | --- |
| Baseline | 14:04:19-14:05:21 | 250 / 0 | 3 | 3 | 3 / 0 |
| Scale-out | 14:14:45-14:21:30 | 1,610 / 0 | 5 | 5 | 5 / 0 |
| Pod replacement | 14:22:04-14:24:00 | 464 / 0 | 6 | 5 | 5 / 1 |
| Server rollout | 14:25:01-14:30:13 | 1,237 / 0 | 10 | 5 | 5 / 5 |
| Restoration | 14:32:48-14:36:28 | 874 / 0 | 8 | 3 | 3 / 5 |

Every unhealthy endpoint in these snapshots maps to a server present before
the operation but absent afterward. Every current server has a matching
healthy endpoint on port `50051`. Retired entries must nevertheless be
reported rather than silently removed from the health totals.

### Baseline and scale-out

The baseline distributed 250 calls as **84/83/83** across the original three
servers. Scale-out added:

```text
greeter-server-7bfffffc5c-4p9r9
greeter-server-7bfffffc5c-nxvd9
```

Both were created at `14:18:27Z` and subsequently received calls. The complete
scale-out segment includes time before they existed, explaining the larger
totals on the original servers.

For a like-for-like view, the final 60 seconds of the captured scale-out log
contain **239 successes**, distributed **48/48/48/48/47** over five servers.
This is an observed distribution, not a fairness guarantee.

### Pod replacement

`deleted-server.txt` identifies `greeter-server-7bfffffc5c-4p9r9`.
It received 31 calls in this segment. Its replacement,
`greeter-server-7bfffffc5c-vfhs8`, was created at `14:22:42Z` and received 55.
The other four servers remained present.

Six cumulative server IDs therefore represent five servers plus one
replacement, not six simultaneous replicas. The health capture still contains
the deleted pod as one unhealthy retired endpoint. The exact deletion
command/grace period was not captured, so this is evidence of pod replacement,
not proof of a forced process kill, node crash, or network partition.

### Server rollout and xDS serving mode

All five server UIDs changed from ReplicaSet hash `7bfffffc5c` to `6d4596c8f4`.
The 1,237 successful calls include all five old and all five new server IDs.
The client was unchanged.

`server-startup.log` records each of the five replacement servers entering xDS
`SERVING`, between `14:28:11.355400161Z` and `14:28:53.598472104Z`.
The final 60 seconds contain 239 successes reaching only the five new servers.

No shutdown/drain messages were supplied for this run. The earlier evidence
package's drain messages must not be attributed to this rollout.

### Restoration

Restoration changed replicas from five to three and reset the rollout marker
from `manual-evidence-20261119-1` to `verified-1`. Resetting the marker also
changed the pod template, so the restoration was **another server rollout**,
not just removal of two replicas.

The final captured server set is:

```text
greeter-server-7bfffffc5c-55fn8
greeter-server-7bfffffc5c-nslrk
greeter-server-7bfffffc5c-qglzf
```

All three are Ready with healthy matching backend entries. The last 60 seconds
contain **239 successes**, split **80/80/79**, using only these three IDs.
The five unhealthy backend entries map exactly to the five retired
`6d4596c8f4` pods. Complete backend-membership cleanup was not captured during
this experiment; the separate follow-up below records its later completion.

## Backend-cleanup follow-up, 2026-11-19 15:10 UTC

A read-only review observation at **15:10:57.403529 UTC**, after the manual
experiments, returned exactly **three backend entries, all `HEALTHY`**, with
zero unhealthy entries. The five unhealthy retired entries in the restoration
capture were no longer present as unhealthy backend entries.

The [machine-readable closure](evidence/manual-20261119T135844Z/backend-cleanup-closure.json)
records the timestamp, project/backend, command, reduced health counts, and
observation limits. It is a reduced observation, not an included raw API dump
or a screenshot.

No scaling, pod deletion, routing change, or teardown was performed to obtain
this observation. It establishes healthy backend membership by the follow-up
time, not the exact convergence delay, uninterrupted availability, or a
repetition of the earlier failure/rollout experiments. The original
three-healthy/five-unhealthy restoration snapshot remains unchanged.

## GitOps traceability

Every phase's Application snapshot is **Healthy/Synced**, records a successful
last operation, and has no reported Application conditions.

| Stage | Captured infrastructure revision |
| --- | --- |
| Baseline | [`3c0cfe5`](https://github.com/cohavisi/utila-gRPC-Infrastructure/commit/3c0cfe542a10220a04334bc99b77b38fca3f5fbb) |
| Scale-out and pod replacement | [`45437c2`](https://github.com/cohavisi/utila-gRPC-Infrastructure/commit/45437c2aee6664324046b903e475cd7765d0af3c) |
| Server rollout | [`65908e5`](https://github.com/cohavisi/utila-gRPC-Infrastructure/commit/65908e52549c1c84a133cfcf305dda2846d0a007) |
| Restoration | [`e56f211`](https://github.com/cohavisi/utila-gRPC-Infrastructure/commit/e56f2119442955864fdc1d95d7b8425caf9054ff) |

Git diffs confirm the replica and rollout-marker changes. Only the server
template was changed; the client template and application image were not.
Matching changes to inactive Helm files maintained parity during the first
two changes and did not switch the live renderer.

### Restoration defect: inactive Helm defaults and CI

The restoration commit correctly restored live Kustomize replicas and its
marker, but did not restore equivalent inactive chart defaults:

| Setting | Kustomize baseline | Helm chart defaults at `e56f211` |
| --- | --- | --- |
| Server replicas | 3 | 5 |
| PDB `minAvailable` | 2 | 3 |
| Rollout marker | `verified-1` | `verified-1` |

The [restoration CI run](https://github.com/cohavisi/utila-gRPC-Infrastructure/actions/runs/44545168018)
failed `test_chart_defaults_preserve_kustomize_resource_identities_and_behavior`
with `Helm/Kustomize behavior differs for Deployment/greeter-server`.
The mismatch was also reproduced locally while preparing this report.

This explains why a Healthy/Synced Argo CD snapshot does **not** establish
green CI: Argo CD reconciled the Kustomize source despite the separate parity
failure. This mismatch was subsequently resolved by removing Helm support and
the renderer-parity requirement, rather than restoring unused chart defaults.
The historical snapshot and failure above are unchanged.

## Coverage limits and remaining evidence

The selected logs cover call numbers `44604` through `52259`, but include only
4,435 of the 7,656 numbers in that span. The other **3,221 call numbers were
not supplied** between captured segments; they must not be counted as either
successes or failures. This is not a full client-lifetime availability report.

The server-rollout test marker is `14:24:45Z`, while its first captured record
is `14:25:01.949991592Z`: approximately **16.95 seconds** at the beginning are
unobserved. The cause was not recorded. Other snapshot commands also ran after
the client-log capture, so test-end markers are not exact RPC coverage ends.

The evidence does not establish zero latency impact: the client uses
`WaitForReady`, and the captures have no per-RPC latency measurements.
Long-lived streams, node loss, network partitions, sustained load limits,
and application mTLS were not demonstrated. Startup logs explicitly state
that application traffic is plaintext.

Follow-up disposition:

1. Backend cleanup was subsequently observed in the separately dated
   [closure](evidence/manual-20261119T135844Z/backend-cleanup-closure.json);
   the original mixed-health snapshot is retained.
2. The inactive Helm defaults and parity checks have since been removed.
   Keep the Application on Kustomize and retain the subsequent CI result.
3. This manual run has no supplied screenshots. The
   [original deployment evidence](deployment-evidence.md#screenshots-and-final-deployment)
   supplies the assignment's screenshots, labeled with their original revision;
   they are not screenshots of this later run.

## Reviewer conclusion

The supplied captures support proxyless xDS operation and continued successful
unary RPCs through Git-controlled scaling and server replacement, using the
same client with zero observed restarts. They demonstrate a working runtime,
with explicit capture and screenshot limitations. Backend cleanup and the
historical CI mismatch have subsequently been resolved as documented above.
No deployment changes were made to create this report or its read-only
backend-cleanup follow-up.
