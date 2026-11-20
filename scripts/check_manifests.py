import argparse
import json
import os
import subprocess
import tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def require(condition, message):
    if not condition:
        raise SystemExit(message)


def main():
    parser = argparse.ArgumentParser(
        description="Render and check cross-resource proxyless wiring."
    )
    parser.add_argument("--require-configured", action="store_true")
    args = parser.parse_args()
    rendered = subprocess.run(
        ["kubectl", "kustomize", str(ROOT / "gitops/overlays/demo")],
        check=True,
        stdout=subprocess.PIPE,
        text=True,
    ).stdout
    if args.require_configured:
        require(
            "REPLACE_" not in rendered and "sha256:" + "0" * 64 not in rendered,
            "Deployment is not configured. Run scripts/configure_demo.py first.",
        )
    documents = [item for item in yaml.safe_load_all(rendered) if item]
    resources = {(item["kind"], item["metadata"]["name"]): item for item in documents}
    require(
        len(resources) == len(documents),
        "Rendered resources contain duplicate kind/name identities",
    )
    settings = next(
        value for (kind, _), value in resources.items() if kind == "ConfigMap"
    )
    for role, app in [("server", "greeter"), ("client", "greeter-client")]:
        name = f"greeter-{role}"
        deployment = resources["Deployment", name]
        pod = deployment["spec"]["template"]["spec"]
        require(
            len(pod["containers"]) == 1, f"{name}: unexpected traffic sidecar/container"
        )
        require(pod["serviceAccountName"] == name, f"{name}: wrong Kubernetes identity")
        annotation = resources["ServiceAccount", name]["metadata"]["annotations"]
        require(
            annotation["iam.gke.io/gcp-service-account"]
            == settings["data"][f"{role.upper()}_GSA"],
            f"{name}: Workload Identity binding differs from platform settings",
        )
        container = pod["containers"][0]
        require(
            "@sha256:" in container["image"],
            f"{name}: application image is not immutable",
        )
        require(
            {"name": "GRPC_XDS_BOOTSTRAP", "value": "/bootstrap/bootstrap.json"}
            in container["env"],
            f"{name}: missing xDS bootstrap",
        )
        init = pod["initContainers"][0]
        require(
            "@sha256:" in init["image"], f"{name}: bootstrap image is not immutable"
        )
        require(
            f"--node-metadata=app={app}" in init["args"],
            f"{name}: wrong endpoint-policy metadata",
        )
        require(
            init["envFrom"][0]["configMapRef"]["name"] == settings["metadata"]["name"],
            f"{name}: init container does not reference the rendered settings",
        )
    server = resources["Deployment", "greeter-server"]["spec"]["template"]["spec"][
        "containers"
    ][0]
    require(
        server["readinessProbe"]["grpc"] == {"port": 50052},
        "Server readiness must reflect xDS serving mode on the health service",
    )
    require(
        server["livenessProbe"]["grpc"] == {"port": 50052, "service": "liveness"},
        "Control-plane availability must not cause liveness restart loops",
    )
    service = resources["Service", "greeter"]
    neg = json.loads(service["metadata"]["annotations"]["cloud.google.com/neg"])
    require(
        neg["exposed_ports"]["50051"]["name"] == "utila-grpc",
        "Standalone NEG name/port differs from the routing stack",
    )
    validator = os.environ.get("KUBECONFORM", "kubeconform")
    validate_command = [
        validator,
        "-strict",
        "-summary",
        "-kubernetes-version",
        "1.35.0",
    ]
    subprocess.run(validate_command, input=rendered, text=True, check=True)
    argo_install = subprocess.run(
        ["kubectl", "kustomize", str(ROOT / "gitops/argocd/install")],
        check=True,
        stdout=subprocess.PIPE,
        text=True,
    ).stdout
    with tempfile.TemporaryDirectory(prefix="utila-argo-schemas-") as directory:
        for resource in yaml.safe_load_all(argo_install):
            if resource and resource["kind"] == "CustomResourceDefinition":
                for version in resource["spec"]["versions"]:
                    if version["name"] == "v1alpha1":
                        schema_path = Path(directory) / (
                            resource["spec"]["names"]["kind"].lower() + ".json"
                        )
                        schema_path.write_text(
                            json.dumps(version["schema"]["openAPIV3Schema"])
                        )
        subprocess.run(
            validate_command
            + ["-schema-location", directory + "/{{.ResourceKind}}.json"],
            input=(ROOT / "gitops/argocd/application.yaml").read_text(),
            text=True,
            check=True,
        )
    print("GitOps render, proxyless wiring, and Argo schemas are valid.")


if __name__ == "__main__":
    main()
