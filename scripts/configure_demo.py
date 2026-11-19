import argparse
import json
from pathlib import Path
import re
import subprocess


ROOT = Path(__file__).resolve().parents[1]


def render_settings(outputs, image):
    match = re.fullmatch(r"([a-z0-9][a-z0-9./_-]+)@(sha256:[0-9a-f]{64})", image)
    if not match or match[2] == "sha256:" + "0" * 64:
        raise ValueError("image must contain a real immutable sha256 digest")
    if match[1] != outputs["image_repository"]["value"]:
        raise ValueError("image must belong to this platform's Artifact Registry repository")
    project_number = str(outputs["project_number"]["value"])
    if not project_number.isdigit() or int(project_number) <= 0:
        raise ValueError("platform output project_number must be a positive number")
    accounts = outputs["workload_service_accounts"]["value"]
    settings = {
        "PROJECT_NUMBER": project_number,
        "ZONE": outputs["zone"]["value"],
        "CLUSTER_NAME": outputs["cluster_name"]["value"],
        "MESH_NAME": outputs["mesh_name"]["value"],
        "NETWORK_NAME": outputs["network_name"]["value"],
        "SERVER_GSA": accounts["greeter-server"],
        "CLIENT_GSA": accounts["greeter-client"],
    }
    if any(not isinstance(value, str) or not value or "\n" in value or "\r" in value
           for value in settings.values()):
        raise ValueError("platform outputs must be non-empty, single-line strings")
    return "".join(f"{key}={value}\n" for key, value in settings.items()), match[1], match[2]


def main():
    parser = argparse.ArgumentParser(description="Configure the GitOps demo from applied platform outputs.")
    parser.add_argument("--image", required=True, help="Artifact Registry image@sha256:digest")
    args = parser.parse_args()
    result = subprocess.run(
        ["terraform", f"-chdir={ROOT / 'terraform/platform'}", "output", "-json"],
        check=True, stdout=subprocess.PIPE, text=True,
    )
    try:
        settings, repository, digest = render_settings(json.loads(result.stdout), args.image)
    except (ValueError, KeyError) as error:
        parser.error(str(error))
    overlay = ROOT / "gitops/overlays/demo"
    configuration = (overlay / "kustomization.yaml").read_text()
    for key, value in [("newName", repository), ("digest", digest)]:
        configuration, count = re.subn(
            rf"(?m)^    {key}: .+$", f"    {key}: {value}", configuration,
        )
        if count != 1:
            parser.error(f"expected exactly one image {key} in the demo overlay")
    (overlay / "settings.env").write_text(settings)
    (overlay / "kustomization.yaml").write_text(configuration)
    print("Configured GitOps files locally. Review and push them before bootstrapping Argo CD.")


if __name__ == "__main__":
    main()
