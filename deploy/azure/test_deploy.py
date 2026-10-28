"""Compile production contracts and exercise admission without contacting Azure."""

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
GROUP = (
    "/subscriptions/test-subscription/resourceGroups/rg-operations/"
    "providers/Microsoft.Insights/actionGroups/existing-alerts"
)


@unittest.skipUnless(shutil.which("az"), "Azure CLI is required to compile Bicep")
class TemplateContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
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
        cls.template = json.loads(result.stdout)

    def resource(self, kind: str) -> dict:
        resources = [r for r in self.template["resources"] if r["type"] == kind]
        self.assertEqual(len(resources), 1)
        return resources[0]

    def test_disabled_log_export_serializes_as_null(self) -> None:
        logs = self.resource("Microsoft.App/managedEnvironments")["properties"][
            "appLogsConfiguration"
        ]
        self.assertIn("destination", logs)
        self.assertIsNone(logs["destination"])

    def test_environment_names_and_tags(self) -> None:
        params = self.template["parameters"]
        self.assertEqual(params["environmentName"]["defaultValue"], "prod")
        self.assertEqual(params["environmentName"]["allowedValues"], ["prod", "staging"])
        self.assertEqual(params["projectPrefix"]["defaultValue"], "piiguard")
        tags = self.template["variables"]["tags"]
        self.assertEqual(tags["project"], "pii-guard")
        self.assertIn("environmentName", tags["environment"])
        self.assertNotIn("purpose", tags)
        for resource in self.template["resources"]:
            if resource.get("tags"):
                self.assertEqual(resource["tags"], "[variables('tags')]")
        for kind in (
            "Microsoft.ContainerRegistry/registries",
            "Microsoft.KeyVault/vaults",
            "Microsoft.Storage/storageAccounts",
        ):
            self.assertIn("environmentName", self.resource(kind)["name"])

    def test_hosts_probes_and_scale_to_zero(self) -> None:
        template = self.resource("Microsoft.App/containerApps")["properties"]["template"]
        self.assertEqual(template["scale"], {"minReplicas": 0, "maxReplicas": 1})
        container = template["containers"][0]
        allowed = next(
            e["value"] for e in container["env"] if e["name"] == "PII_GUARD_ALLOWED_HOSTS"
        )
        self.assertIn("publicOrigin", allowed)
        self.assertIn("defaultDomain", allowed)
        for probe in container["probes"]:
            self.assertEqual(
                probe["httpGet"]["httpHeaders"], [{"name": "Host", "value": "localhost"}]
            )

    def test_budget_and_secret_recovery_contract(self) -> None:
        budget = self.resource("Microsoft.Consumption/budgets")["properties"]
        self.assertEqual(budget["timeGrain"], "Monthly")
        notifications = budget["notifications"].values()
        self.assertEqual(sorted(n["threshold"] for n in notifications), [50, 80, 100])
        for notification in notifications:
            self.assertTrue(notification["enabled"])
            self.assertEqual(notification["contactEmails"], [])
            self.assertIn("alertActionGroupIds", notification["contactGroups"])
        self.assertEqual(self.template["parameters"]["alertActionGroupIds"]["minLength"], 1)
        vault = self.resource("Microsoft.KeyVault/vaults")["properties"]
        self.assertEqual(vault["softDeleteRetentionInDays"], 7)
        self.assertTrue(vault["enablePurgeProtection"])


class DeploymentAdmissionTests(unittest.TestCase):
    def run_deploy(self, mode: str, **overrides: str) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as directory:
            fake = Path(directory) / "az"
            fake.write_text(
                "#!/bin/sh\n"
                'echo "$*" >> "$AZURE_TEST_LOG"\n'
                'case "$*" in\n'
                '  "bicep build "*) exit 0;;\n'
                '  "account show "*) echo test-subscription;;\n'
                '  "group exists "*) echo true;;\n'
                '  "group show "*"tags.project"*) echo pii-guard;;\n'
                '  "group show "*"tags.environment"*) echo "${AZURE_ENVIRONMENT:-prod}";;\n'
                '  "group show "*"location"*) echo swedencentral;;\n'
                '  "monitor action-group show "*) echo true;;\n'
                '  "resource show "*"properties.amount"*) '
                '[ "${TEST_BUDGET_EXISTS:-true}" = true ] || exit 1; echo 25;;\n'
                f'  "resource show "*"Actual50.contactGroups"*) echo \'["{GROUP}"]\';;\n'
                '  "resource show "*"startDate"*) echo 2026-10-01T00:00:00Z;;\n'
                f"  *properties.outputs.vaultUri.value*) echo {VAULT};;\n"
                "  *properties.outputs.registryServer.value*) echo piiguardexample.azurecr.io;;\n"
                '  "deployment group validate "*|"deployment group create "*) exit 0;;\n'
                '  "rest "*) echo true;;\n'
                '  "containerapp ingress update "*) exit 0;;\n'
                '  "containerapp show "*"latestReadyRevisionName"*) '
                'echo "${TEST_READY_REVISION:-reviewed-revision}";;\n'
                '  "containerapp show "*) echo reviewed-revision;;\n'
                '  *) echo "UNEXPECTED AZURE CALL" >&2; exit 99;;\n'
                "esac\n"
            )
            fake.chmod(0o700)
            sleeper = Path(directory) / "sleep"
            sleeper.write_text("#!/bin/sh\nexit 0\n")
            sleeper.chmod(0o700)
            log = Path(directory) / "calls"
            env = {
                "PATH": directory + os.pathsep + os.defpath,
                "AZURE_TEST_LOG": str(log),
                "AZURE_SUBSCRIPTION_ID": "test-subscription",
                "AZURE_RESOURCE_GROUP": "rg-pii-guard-prod",
                "AZURE_LOCATION": "swedencentral",
                "AZURE_MONTHLY_BUDGET_AMOUNT": "25",
                "AZURE_SECRET_PROVISIONER_OBJECT_ID": "00000000-0000-0000-0000-000000000001",
                "HOSTED_IMAGE": IMAGE,
                "HOSTED_PUBLIC_ORIGIN": "https://guard.example.com",
                "GOOGLE_CLIENT_ID": "synthetic-client",
                "META_KEY_SECRET_URI": VAULT + "secrets/meta/" + "b" * 32,
                "TENANT_KEY_SECRET_URI": VAULT + "secrets/tenant/" + "c" * 32,
                "GOOGLE_SECRET_URI": VAULT + "secrets/google/" + "d" * 32,
                **overrides,
            }
            result = subprocess.run(  # noqa: S603 - repository script and controlled env
                ["/bin/bash", str(SCRIPT), mode],
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.calls = log.read_text() if log.exists() else ""
            return result

    def assert_refused(self, result: subprocess.CompletedProcess[str], reason: str) -> None:
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(reason, result.stderr)
        self.assertNotIn("UNEXPECTED AZURE CALL", result.stderr)
        self.assertNotIn("deployment group create", self.calls)

    def test_validate_is_cloud_free(self) -> None:
        result = self.run_deploy("validate")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("account show", self.calls)

    def test_shared_group_is_refused(self) -> None:
        self.assert_refused(
            self.run_deploy("bootstrap", AZURE_RESOURCE_GROUP="rg-shared-prod"),
            "Refusing non-dedicated",
        )

    def test_environment_mismatch_is_refused(self) -> None:
        self.assert_refused(
            self.run_deploy("bootstrap", AZURE_ENVIRONMENT="staging"), "Refusing non-dedicated"
        )

    def test_wrong_subscription_is_refused(self) -> None:
        self.assert_refused(
            self.run_deploy("bootstrap", AZURE_SUBSCRIPTION_ID="different-subscription"),
            "subscription differs",
        )

    def test_bootstrap_requires_explicit_existing_alert_group(self) -> None:
        self.assert_refused(self.run_deploy("bootstrap"), "AZURE_ALERT_ACTION_GROUP_ID")

    def test_bootstrap_uses_production_names_without_app(self) -> None:
        result = self.run_deploy("bootstrap", AZURE_ALERT_ACTION_GROUP_ID=GROUP)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("environmentName=prod", self.calls)
        self.assertNotIn("deployApp=true", self.calls)

    def test_stage_refuses_missing_budget(self) -> None:
        self.assert_refused(
            self.run_deploy("stage", TEST_BUDGET_EXISTS="false"), "budget must exist"
        )

    def test_mutable_image_is_refused(self) -> None:
        self.assert_refused(
            self.run_deploy("stage", HOSTED_IMAGE="piiguardexample.azurecr.io/pii-guard:latest"),
            "immutable ACR digest",
        )

    def test_other_vault_is_refused(self) -> None:
        self.assert_refused(
            self.run_deploy(
                "stage", **{"META_KEY_SECRET_URI": "https://other.example.com/secrets/meta"}
            ),
            "versioned secrets from this deployment",
        )

    def test_budget_over_ceiling_is_refused(self) -> None:
        self.assert_refused(
            self.run_deploy("stage", HOSTED_SPONSORED_MICRODOLLARS="10000001"),
            "USD 10 deployment ceiling",
        )

    def test_enable_and_positive_budget_require_lab_gate(self) -> None:
        for mode, budget in (("enable", "0"), ("stage", "1")):
            with self.subTest(mode=mode):
                self.assert_refused(
                    self.run_deploy(mode, HOSTED_SPONSORED_MICRODOLLARS=budget),
                    "HOSTED_RELEASE_EVIDENCE",
                )

    def test_enable_readiness_timeout_restores_internal_ingress(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            evidence = Path(directory) / "review.json"
            evidence.write_text(
                json.dumps(
                    {
                        "image": IMAGE,
                        **dict.fromkeys(
                            (
                                "lab_1372_done",
                                "isolation",
                                "csrf",
                                "identity_header_spoofing",
                                "quotas_restart",
                                "ssrf",
                                "synthetic_roundtrip",
                                "streaming",
                                "privacy_review",
                            ),
                            True,
                        ),
                    }
                )
            )
            result = self.run_deploy(
                "enable", HOSTED_RELEASE_EVIDENCE=str(evidence), TEST_READY_REVISION="old-revision"
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("did not become ready", result.stderr)
            self.assertIn("deployment group create", self.calls)
            self.assertIn("containerapp ingress update --name piiguard-prod-app", self.calls)
            self.assertIn("--type internal --output none", self.calls)

    def test_stage_preserves_existing_action_groups(self) -> None:
        result = self.run_deploy("stage")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(GROUP, self.calls)
        self.assertIn("alertActionGroupIds=", self.calls)
        self.assertNotIn("alertActionGroupIds=[]", self.calls)
        self.assertIn("budgetStartDate=2026-10-01T00:00:00Z", self.calls)


if __name__ == "__main__":
    unittest.main()
