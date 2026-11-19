from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch

import yaml

import configure_demo
from configure_demo import render_helm_values, render_settings


class ConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.repository = "us-central1-docker.pkg.dev/test-project/utila-grpc/greeter"
        self.outputs = {key: {"value": value} for key, value in {
            "image_repository": self.repository,
            "project_number": "123456789",
            "zone": "us-central1-a",
            "cluster_name": "utila-grpc",
            "mesh_name": "utila-grpc",
            "network_name": "utila-grpc",
            "workload_service_accounts": {
                "greeter-server": "server@test-project.iam.gserviceaccount.com",
                "greeter-client": "client@test-project.iam.gserviceaccount.com",
            },
        }.items()}

    def test_derives_separate_workload_identities_from_platform(self):
        settings, repository, digest = render_settings(
            self.outputs, self.repository + "@sha256:" + "a" * 64,
        )
        self.assertIn("SERVER_GSA=server@test-project.iam.gserviceaccount.com\n", settings)
        self.assertIn("CLIENT_GSA=client@test-project.iam.gserviceaccount.com\n", settings)
        self.assertEqual(repository + "@" + digest, self.repository + "@sha256:" + "a" * 64)

    def test_rejects_mutable_or_wrong_repository_images(self):
        for image in [
            self.repository + ":latest",
            self.repository + "@sha256:" + "0" * 64,
            "other.example/greeter@sha256:" + "a" * 64,
        ]:
            with self.subTest(image=image), self.assertRaises(ValueError):
                render_settings(self.outputs, image)

    def test_rejects_unconfigured_project(self):
        self.outputs["project_number"]["value"] = "REPLACE_PROJECT_NUMBER"
        with self.assertRaises(ValueError):
            render_settings(self.outputs, self.repository + "@sha256:" + "a" * 64)

    def test_helm_and_kustomize_share_the_same_platform_configuration(self):
        image = self.repository + "@sha256:" + "a" * 64
        settings, repository, digest = render_settings(self.outputs, image)
        helm = render_helm_values(self.outputs, image)
        self.assertEqual(helm["settings"], dict(line.split("=", 1) for line in settings.splitlines()))
        self.assertEqual(helm["image"], {"repository": repository, "digest": digest})

    def test_helm_configuration_preserves_workload_overrides(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "gitops/helm/demo-values.yaml"
            path.parent.mkdir(parents=True)
            path.write_text(yaml.safe_dump({"namespace": {"create": True}, "server": {"replicas": 5}}))
            with patch.object(configure_demo, "ROOT", root), \
                 patch("sys.argv", ["configure_demo.py", "--format", "helm", "--image",
                                    self.repository + "@sha256:" + "a" * 64]), \
                 patch.object(configure_demo.subprocess, "run") as run:
                run.return_value.stdout = json.dumps(self.outputs)
                configure_demo.main()
            values = yaml.safe_load(path.read_text())
            self.assertEqual(values["server"]["replicas"], 5)
            self.assertTrue(values["namespace"]["create"])
            self.assertEqual(values["settings"]["PROJECT_NUMBER"], "123456789")


if __name__ == "__main__":
    unittest.main()
