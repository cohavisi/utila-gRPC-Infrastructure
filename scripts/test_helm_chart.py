import subprocess
import unittest

from check_manifests import ROOT, compare_baseline, read_resources, render_helm, render_kustomize


class HelmChartTests(unittest.TestCase):
    def render(self, *arguments):
        return subprocess.run(
            ["helm", "template", "utila-grpc", str(ROOT / "gitops/helm/greeter"),
             "--namespace", "utila-grpc", "--values", str(ROOT / "gitops/helm/demo-values.yaml"),
             *arguments],
            text=True, capture_output=True,
        )

    def test_chart_defaults_preserve_kustomize_resource_identities_and_behavior(self):
        compare_baseline(render_kustomize())

    def test_bootstrap_settings_changes_roll_both_workloads(self):
        before = read_resources(render_helm())
        result = self.render("--set-string", "settings.NETWORK_NAME=changed-network")
        self.assertEqual(result.returncode, 0, result.stderr)
        after = read_resources(result.stdout)
        for role in ["server", "client"]:
            key = "Deployment", f"greeter-{role}"
            old = before[key]["spec"]["template"]["metadata"]["annotations"]
            new = after[key]["spec"]["template"]["metadata"]["annotations"]
            self.assertNotEqual(old["checksum/bootstrap-settings"], new["checksum/bootstrap-settings"])
        self.assertEqual(after["ConfigMap", "deployment-settings"]["data"]["NETWORK_NAME"], "changed-network")

    def test_native_helm_can_leave_namespace_creation_to_the_cli(self):
        result = self.render("--set", "namespace.create=false")
        self.assertEqual(result.returncode, 0, result.stderr)
        resources = read_resources(result.stdout)
        self.assertNotIn(("Namespace", "utila-grpc"), resources)
        self.assertIn(("Service", "greeter"), resources)

    def test_rejects_unsafe_or_unconfigured_values(self):
        for arguments, message in [
            (["--set-string", "image.digest=latest"], "digest"),
            (["--set-string", "image.digest=sha256:" + "0" * 64], "digest"),
            (["--set-string", "settings.PROJECT_NUMBER=REPLACE_PROJECT_NUMBER"], "PROJECT_NUMBER"),
            (["--set-string", "bootstrapImage=example/bootstrap:latest"], "bootstrapImage"),
            (["--namespace", "other-namespace"], "Workload Identity"),
            (["--set", "server.replicas=1,server.minAvailable=2"], "minAvailable"),
        ]:
            with self.subTest(arguments=arguments):
                result = self.render(*arguments)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(message, result.stderr)


if __name__ == "__main__":
    unittest.main()
