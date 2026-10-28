"""Exercise fail-closed deployment admission without contacting Azure."""

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).with_name("deploy.sh").resolve()
IMAGE = "piiguardexample.azurecr.io/pii-guard@sha256:" + "a" * 64
VAULT = "https://piiguardexample.vault.azure.net/"


class TemplateContractTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("az"), "Azure CLI is required to compile Bicep")
    def test_disabled_log_export_serializes_as_null(self) -> None:
        result = subprocess.run(  # noqa: S603 - fixed read-only compiler invocation
            [
                shutil.which("az") or "/unavailable-azure-cli",
                "bicep",
                "build",
                "--file",
                str(SCRIPT.with_name("main.bicep")),
                "--stdout",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        template = json.loads(result.stdout)
        environments = [
            resource
            for resource in template["resources"]
            if resource["type"] == "Microsoft.App/managedEnvironments"
        ]
        self.assertEqual(len(environments), 1)
        logs = environments[0]["properties"]["appLogsConfiguration"]
        self.assertIn("destination", logs)
        self.assertIsNone(logs["destination"])


class DeploymentAdmissionTests(unittest.TestCase):
    def run_deploy(self, mode: str, **overrides: str) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as directory:
            fake = Path(directory) / "az"
            fake.write_text(
                "#!/bin/sh\n"
                'case "$*" in\n'
                '  "bicep build "*) exit 0;;\n'
                '  "account show "*) echo test-subscription;;\n'
                '  "group show "*) echo pii-guard;;\n'
                f"  *properties.outputs.vaultUri.value*) echo {VAULT};;\n"
                "  *properties.outputs.registryServer.value*) echo piiguardexample.azurecr.io;;\n"
                '  *) echo "UNEXPECTED AZURE CALL" >&2; exit 99;;\n'
                "esac\n"
            )
            fake.chmod(0o700)
            env = {
                "PATH": directory + os.pathsep + os.defpath,
                "AZURE_SUBSCRIPTION_ID": "test-subscription",
                "AZURE_RESOURCE_GROUP": "rg-pii-guard-hosted-test",
                "AZURE_LOCATION": "swedencentral",
                "HOSTED_IMAGE": IMAGE,
                "HOSTED_PUBLIC_ORIGIN": "https://guard.example.com",
                "GOOGLE_CLIENT_ID": "synthetic-client",
                "META_KEY_SECRET_URI": VAULT + "secrets/meta/" + "b" * 32,
                "TENANT_KEY_SECRET_URI": VAULT + "secrets/tenant/" + "c" * 32,
                "GOOGLE_SECRET_URI": VAULT + "secrets/google/" + "d" * 32,
                **overrides,
            }
            return subprocess.run(  # noqa: S603 - repository script and controlled env
                ["/bin/bash", str(SCRIPT), mode],
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )

    def assert_refused(self, result: subprocess.CompletedProcess[str], reason: str) -> None:
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(reason, result.stderr)
        self.assertNotIn("UNEXPECTED AZURE CALL", result.stderr)

    def test_validate_is_cloud_free(self) -> None:
        result = self.run_deploy("validate")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_shared_group_is_refused(self) -> None:
        self.assert_refused(
            self.run_deploy("bootstrap", AZURE_RESOURCE_GROUP="rg-shared-prod"),
            "Refusing non-dedicated",
        )

    def test_wrong_subscription_is_refused(self) -> None:
        self.assert_refused(
            self.run_deploy("bootstrap", AZURE_SUBSCRIPTION_ID="different-subscription"),
            "subscription differs",
        )

    def test_mutable_image_is_refused(self) -> None:
        self.assert_refused(
            self.run_deploy("stage", HOSTED_IMAGE="piiguardexample.azurecr.io/pii-guard:latest"),
            "immutable ACR digest",
        )

    def test_other_vault_is_refused(self) -> None:
        self.assert_refused(
            self.run_deploy(
                "stage",
                **{"META_KEY_SECRET_URI": "https://other.example.com/secrets/meta"},
            ),
            "versioned secrets from this deployment",
        )

    def test_budget_over_ceiling_is_refused(self) -> None:
        self.assert_refused(
            self.run_deploy("stage", HOSTED_SPONSORED_MICRODOLLARS="10000001"),
            "USD 10 deployment ceiling",
        )

    def test_public_enable_requires_review_evidence(self) -> None:
        self.assert_refused(self.run_deploy("enable"), "HOSTED_RELEASE_EVIDENCE")


if __name__ == "__main__":
    unittest.main()
