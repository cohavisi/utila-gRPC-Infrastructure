import argparse
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import tempfile

import yaml


ROOT = Path(__file__).resolve().parents[1]


def require(condition, message):
    if not condition:
        raise SystemExit(message)


def render_kustomize():
    return subprocess.run(
        ["kubectl", "kustomize", str(ROOT / "gitops/overlays/demo")],
        check=True, stdout=subprocess.PIPE, text=True,
    ).stdout


def render_helm(values_file=None):
    return subprocess.run(
        ["helm", "template", "utila-grpc", str(ROOT / "gitops/helm/greeter"),
         "--namespace", "utila-grpc", "--values", str(values_file or ROOT / "gitops/helm/demo-values.yaml")],
        check=True, stdout=subprocess.PIPE, text=True,
    ).stdout


def read_resources(rendered):
    documents = [item for item in yaml.safe_load_all(rendered) if item]
    resources = {(item["kind"], item["metadata"]["name"]): item for item in documents}
    require(len(resources) == len(documents), "Rendered resources contain duplicate kind/name identities")
    return resources


def check_resources(rendered, require_configured):
    if require_configured:
        require("REPLACE_" not in rendered and "sha256:" + "0" * 64 not in rendered,
                "Deployment is not configured. Run scripts/configure_demo.py first.")
    resources = read_resources(rendered)
    settings = next(value for (kind, _), value in resources.items() if kind == "ConfigMap")
    for role, app in [("server", "greeter"), ("client", "greeter-client")]:
        name = f"greeter-{role}"
        deployment = resources["Deployment", name]
        pod = deployment["spec"]["template"]["spec"]
        require(len(pod["containers"]) == 1, f"{name}: unexpected traffic sidecar/container")
        require(pod["serviceAccountName"] == name, f"{name}: wrong Kubernetes identity")
        annotation = resources["ServiceAccount", name]["metadata"]["annotations"]
        require(annotation["iam.gke.io/gcp-service-account"] == settings["data"][f"{role.upper()}_GSA"],
                f"{name}: Workload Identity binding differs from platform settings")
        container = pod["containers"][0]
        require("@sha256:" in container["image"], f"{name}: application image is not immutable")
        require({"name": "GRPC_XDS_BOOTSTRAP", "value": "/bootstrap/bootstrap.json"}
                in container["env"], f"{name}: missing xDS bootstrap")
        init = pod["initContainers"][0]
        require("@sha256:" in init["image"], f"{name}: bootstrap image is not immutable")
        require(f"--node-metadata=app={app}" in init["args"], f"{name}: wrong endpoint-policy metadata")
        require(init["envFrom"][0]["configMapRef"]["name"] == settings["metadata"]["name"],
                f"{name}: init container does not reference the rendered settings")
    server = resources["Deployment", "greeter-server"]["spec"]["template"]["spec"]["containers"][0]
    require(server["readinessProbe"]["grpc"] == {"port": 50052},
            "Server readiness must reflect xDS serving mode on the health service")
    require(server["livenessProbe"]["grpc"] == {"port": 50052, "service": "liveness"},
            "Control-plane availability must not cause liveness restart loops")
    service = resources["Service", "greeter"]
    neg = json.loads(service["metadata"]["annotations"]["cloud.google.com/neg"])
    require(neg["exposed_ports"]["50051"]["name"] == "utila-grpc",
            "Standalone NEG name/port differs from the routing stack")


def normalized_resources(rendered):
    resources = deepcopy(read_resources(rendered))
    settings = next(value for (kind, _), value in resources.items() if kind == "ConfigMap")
    old_name = settings["metadata"]["name"]
    resources.pop(("ConfigMap", old_name))
    settings["metadata"]["name"] = "deployment-settings"
    resources["ConfigMap", "deployment-settings"] = settings
    for role in ["server", "client"]:
        template = resources["Deployment", f"greeter-{role}"]["spec"]["template"]
        template["metadata"]["annotations"].pop("checksum/bootstrap-settings", None)
        template["spec"]["initContainers"][0]["envFrom"][0]["configMapRef"]["name"] = "deployment-settings"
    return resources


def compare_renderers(kustomize, helm):
    left, right = normalized_resources(kustomize), normalized_resources(helm)
    require(left.keys() == right.keys(), "Helm and Kustomize render different resource identities")
    for key in left:
        require(left[key] == right[key], f"Helm/Kustomize behavior differs for {key[0]}/{key[1]}")


def compare_baseline(kustomize):
    resources = read_resources(kustomize)
    settings = next(value["data"] for (kind, _), value in resources.items() if kind == "ConfigMap")
    image = resources["Deployment", "greeter-server"]["spec"]["template"]["spec"]["containers"][0]["image"]
    repository, digest = image.rsplit("@", 1)
    values = {
        "namespace": {"create": True},
        "image": {"repository": repository, "digest": digest},
        "settings": settings,
    }
    with tempfile.TemporaryDirectory(prefix="utila-helm-parity-") as directory:
        path = Path(directory) / "baseline-values.yaml"
        path.write_text(yaml.safe_dump(values))
        compare_renderers(kustomize, render_helm(path))


def main():
    parser = argparse.ArgumentParser(description="Render and check cross-resource proxyless wiring.")
    parser.add_argument("--require-configured", action="store_true")
    parser.add_argument("--renderer", choices=["kustomize", "helm", "both"], default="kustomize")
    args = parser.parse_args()
    rendered = {}
    if args.renderer in ["kustomize", "both"]:
        rendered["kustomize"] = render_kustomize()
    if args.renderer in ["helm", "both"]:
        subprocess.run(
            ["helm", "lint", str(ROOT / "gitops/helm/greeter"), "--strict",
             "--namespace", "utila-grpc", "--values", str(ROOT / "gitops/helm/demo-values.yaml")],
            check=True,
        )
        rendered["helm"] = render_helm()
    for document in rendered.values():
        check_resources(document, args.require_configured)
    if args.renderer == "both":
        compare_baseline(rendered["kustomize"])
    validator = os.environ.get("KUBECONFORM", "kubeconform")
    validate_command = [validator, "-strict", "-summary", "-kubernetes-version", "1.35.0"]
    for document in rendered.values():
        subprocess.run(validate_command, input=document, text=True, check=True)
    argo_paths = [
        ROOT / "gitops/argocd/project.yaml",
        ROOT / "gitops/argocd/application.yaml",
        ROOT / "gitops/argocd/application-helm.yaml",
    ]
    project, kustomize_app, helm_app = [yaml.safe_load(path.read_text()) for path in argo_paths]
    require(kustomize_app["metadata"] == helm_app["metadata"],
            "Migration must reuse the same Argo CD Application identity")
    require(kustomize_app["spec"]["project"] == helm_app["spec"]["project"] == project["metadata"]["name"],
            "Both Applications must use the shared AppProject")
    require(kustomize_app["spec"]["destination"] == helm_app["spec"]["destination"],
            "Migration must retain the destination cluster/namespace")
    require(helm_app["spec"]["syncPolicy"]["automated"]["prune"] is False,
            "Keep Helm auto-prune disabled to protect the Service/NEG lifecycle")
    argo_install = subprocess.run(
        ["kubectl", "kustomize", str(ROOT / "gitops/argocd/install")],
        check=True, stdout=subprocess.PIPE, text=True,
    ).stdout
    with tempfile.TemporaryDirectory(prefix="utila-argo-schemas-") as directory:
        for resource in yaml.safe_load_all(argo_install):
            if resource and resource["kind"] == "CustomResourceDefinition":
                for version in resource["spec"]["versions"]:
                    if version["name"] == "v1alpha1":
                        schema_path = Path(directory) / (resource["spec"]["names"]["kind"].lower() + ".json")
                        schema_path.write_text(json.dumps(version["schema"]["openAPIV3Schema"]))
        subprocess.run(
            validate_command + ["-schema-location", directory + "/{{.ResourceKind}}.json"],
            input="\n---\n".join(path.read_text() for path in argo_paths),
            text=True, check=True,
        )
    print(f"GitOps render, proxyless wiring, and Argo schemas are valid ({args.renderer}).")


if __name__ == "__main__":
    main()
