"""Compile production contracts and exercise admission without contacting Azure."""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import ClassVar

SCRIPT = Path(__file__).with_name("deploy.sh").resolve()
IMAGE = "piiguardexample.azurecr.io/pii-guard@sha256:" + "a" * 64
VAULT = "https://piiguardexample.vault.azure.net/"
GROUP = (
    "/subscriptions/test-subscription/resourceGroups/rg-operations/"
    "providers/Microsoft.Insights/actionGroups/existing-alerts"
)


FAKE_AZ = r"""#!/bin/sh
echo "$*" >> "$AZURE_TEST_LOG"
case "$*" in
  "bicep build "*) exit 0;;
  "account show "*"user.type"*) echo "${TEST_ACCOUNT_TYPE:-user}";;
  "account show "*) echo test-subscription;;
  "group exists "*) echo true;;
  "group show "*"tags.project"*) echo pii-guard;;
  "group show "*"tags.environment"*) echo "${AZURE_ENVIRONMENT:-prod}";;
  "group show "*"location"*) echo swedencentral;;
  "monitor action-group show "*) echo "${TEST_ALERT_ENABLED:-true}";;
  "resource show "*"properties.amount"*)
    [ "${TEST_BUDGET_EXISTS:-true}" = true ] || exit 1
    echo "${TEST_BUDGET_AMOUNT:-25.0}";;
  "resource show "*"properties.notifications"*)
    if [ "${TEST_BUDGET_NOTIFICATIONS+x}" = x ]; then
      printf '%s\n' "$TEST_BUDGET_NOTIFICATIONS"
    else
      echo '{"Actual50":{"enabled":true,"operator":"GreaterThanOrEqualTo",
             "threshold":50.0,"thresholdType":"Actual","contactGroups":["__GROUP__"]}}'
    fi;;
  "resource show "*"startDate"*) echo 2026-10-01T00:00:00Z;;
  *properties.outputs.vaultUri.value*) echo __VAULT__;;
  *properties.outputs.registryServer.value*) echo piiguardexample.azurecr.io;;
  *properties.outputs.ledgerAccountUrl.value*) echo https://ledgerexample.blob.core.windows.net;;
  *properties.outputs.projectAccountUrl.value*) echo "${TEST_PROJECT_ACCOUNT:-https://ledgerexample.blob.core.windows.net}";;
  "containerapp env show "*)
    printf '{"internal":%s,"public":"%s"}\n' \
      "${TEST_INTERNAL:-true}" "${TEST_PUBLIC_NETWORK:-Disabled}";;
  "vm show "*) echo Succeeded;;
  "containerapp show "*"customDomains"*)
    case "${TEST_BINDINGS_ERROR:-}" in
      forbidden) echo 'ERROR: (AuthorizationFailed) synthetic refusal' >&2; exit 1;;
      absent) echo 'ERROR: (ContainerAppNotFound) synthetic missing' >&2; exit 3;;
    esac
    echo '[{"name":"guard.example.com","bindingType":"SniEnabled",
           "certificateId":"/synthetic/cert"}]';;
  "deployment group validate "*|"deployment group create "*) exit 0;;
  "rest "*) echo true;;
  "containerapp ingress update "*) exit 0;;
  "containerapp show "*"ingress.external"*) echo "${TEST_LIVE_EXTERNAL:-false}";;
  "containerapp show "*"latestReadyRevisionName"*)
    echo "${TEST_READY_REVISION:-reviewed-revision}";;
  "containerapp show "*) echo reviewed-revision;;
  *) echo 'UNEXPECTED AZURE CALL' >&2; exit 99;;
esac
"""


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
        self.assertEqual(params["environmentName"]["allowedValues"], ["prod", "dev"])
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

    def test_operator_foundation_never_deploys_an_application(self) -> None:
        types = {r["type"] for r in self.template["resources"]}
        self.assertNotIn("Microsoft.App/containerApps", types)
        self.assertNotIn("Microsoft.App/containerApps/authConfigs", types)
        self.assertNotIn("Microsoft.Insights/metricAlerts", types)

    def test_dev_environment_requires_internal_network(self) -> None:
        props = self.resource("Microsoft.App/managedEnvironments")["properties"]
        self.assertIn("Disabled", props["publicNetworkAccess"])
        self.assertIn("environmentName", props["publicNetworkAccess"])
        self.assertIn("true", props["vnetConfiguration"])
        self.assertIn("acaSubnetId", props["vnetConfiguration"])

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
            fake.write_text(FAKE_AZ.replace("__GROUP__", GROUP).replace("__VAULT__", VAULT))
            fake.chmod(0o700)
            python = Path(directory) / "python3"
            python.write_text(
                '#!/bin/sh\nif [ "$1" = deploy/azure/smoke.py ]; then\n'
                '  echo synthetic-smoke >> "$AZURE_TEST_LOG"; exit 0; fi\n'
                + "exec "
                + shlex.quote(sys.executable)
                + ' "$@"\n'
            )
            python.chmod(0o700)
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
                ["/bin/bash", str(SCRIPT), *mode.split()],
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.calls = log.read_text() if log.exists() else ""
            return result

    def run_technical_stage(
        self, *, mode: str = "technical-stage", evidence: dict | None = None, **overrides: str
    ) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as directory:
            review = Path(directory) / "technical.json"
            review.write_text(
                json.dumps(
                    evidence
                    if evidence is not None
                    else {
                        "image": IMAGE,
                        "purpose": "private-synthetic-verification",
                        "network_reviewed": True,
                        "tailnet_acl": True,
                        "proxy_tls": True,
                        "synthetic_only": True,
                    }
                )
            )
            return self.run_deploy(
                mode,
                **{
                    "AZURE_ENVIRONMENT": "dev",
                    "AZURE_RESOURCE_GROUP": "rg-pii-guard-dev",
                    "AZURE_DEV_NETWORK_APPROVED": "true",
                    "AZURE_TECHNICAL_STAGE_APPROVED": "true",
                    "HOSTED_PUBLIC_ORIGIN": "https://guard-dev.watt-mind.com",
                    "HOSTED_TECHNICAL_STAGE_EVIDENCE": str(review),
                    **overrides,
                },
            )

    def test_private_technical_stage_allows_initial_app_without_claiming_acceptance(self) -> None:
        result = self.run_technical_stage(TEST_BINDINGS_ERROR="absent")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("full live acceptance remains pending", result.stdout)
        self.assertIn("--query user.type", self.calls)
        self.assertIn("privateDevReviewed=true", self.calls)
        self.assertIn("publicEnabled=false", self.calls)
        self.assertIn("customDomains=[]", self.calls)
        self.assertIn("--template-file deploy/azure/release.bicep", self.calls)
        self.assertIn("synthetic-smoke", self.calls)
        self.assertNotIn("allocationId=", self.calls)
        self.assertNotIn("allocationExpiresAt=", self.calls)
        self.assertNotIn("sponsoredMicrodollars=", self.calls)

    def test_technical_stage_operator_environment_and_funding_admission(self) -> None:
        cases = [
            ({"AZURE_TECHNICAL_STAGE_APPROVED": "false"}, "Explicit operator"),
            ({"GITHUB_ACTIONS": "true"}, "unavailable to CI"),
            ({"CI": "true"}, "unavailable to CI"),
            ({"TEST_ACCOUNT_TYPE": "servicePrincipal"}, "interactive operator"),
            ({"HOSTED_SPONSORED_MICRODOLLARS": "1"}, "zero sponsorship"),
            ({"HOSTED_SPONSORED_MICRODOLLARS": "00"}, "zero sponsorship"),
            ({"HOSTED_ALLOCATION_ID": "synthetic-allocation"}, "no allocation pins"),
            ({"HOSTED_ALLOCATION_EXPIRES_AT": "0"}, "no allocation pins"),
            ({"HOSTED_PUBLIC_ORIGIN": "https://other.example.com"}, "exact private dev"),
            (
                {"AZURE_ENVIRONMENT": "prod", "AZURE_RESOURCE_GROUP": "rg-pii-guard-prod"},
                "exact private dev",
            ),
        ]
        for overrides, reason in cases:
            with self.subTest(overrides=overrides):
                self.assert_refused(self.run_technical_stage(**overrides), reason)

    def test_technical_stage_keeps_actual_network_and_budget_checks(self) -> None:
        for overrides, reason in [
            ({"TEST_PUBLIC_NETWORK": "Enabled"}, "actual internal environment"),
            ({"TEST_BUDGET_EXISTS": "false"}, "budget must exist"),
            ({"TEST_ALERT_ENABLED": "false"}, "Budget action group"),
            ({"TEST_BINDINGS_ERROR": "forbidden"}, "existing_app_bindings_unavailable"),
        ]:
            with self.subTest(overrides=overrides):
                self.assert_refused(self.run_technical_stage(**overrides), reason)

    def test_technical_evidence_cannot_replace_normal_release_acceptance(self) -> None:
        self.assert_refused(self.run_technical_stage(mode="stage"), "HOSTED_RELEASE_EVIDENCE")
        for evidence in (
            {},
            {
                "image": IMAGE,
                "purpose": "private-synthetic-verification",
                "network_reviewed": True,
                "tailnet_acl": True,
                "proxy_tls": True,
                "synthetic_only": True,
                "lab_1372_done": True,
            },
            {
                "image": IMAGE,
                "purpose": "private-synthetic-verification",
                "network_reviewed": True,
                "tailnet_acl": True,
                "proxy_tls": True,
                "synthetic_only": False,
            },
            {
                "image": "different",
                "purpose": "private-synthetic-verification",
                "network_reviewed": True,
                "tailnet_acl": True,
                "proxy_tls": True,
                "synthetic_only": True,
            },
        ):
            with self.subTest(evidence=evidence):
                self.assert_refused(
                    self.run_technical_stage(evidence=evidence),
                    "Technical-stage evidence incomplete",
                )

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
            self.run_deploy("bootstrap", AZURE_ENVIRONMENT="dev"), "Refusing non-dedicated"
        )

    def test_dev_cannot_create_public_foundation_or_app(self) -> None:
        for mode in ("bootstrap", "stage", "enable"):
            with self.subTest(mode=mode):
                self.assert_refused(
                    self.run_deploy(
                        mode, AZURE_ENVIRONMENT="dev", AZURE_RESOURCE_GROUP="rg-pii-guard-dev"
                    ),
                    "tailnet-only private network",
                )
                self.assertNotIn("account show", self.calls)

    def test_ci_preflight_has_no_azure_calls(self) -> None:
        result = self.run_deploy("ci-preflight dev")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)["app_only"])
        self.assertTrue(json.loads(result.stdout)["private_dev"])
        self.assertEqual(self.calls, "")

    def test_binding_read_failure_blocks_all_writes(self) -> None:
        self.assert_refused(
            self.run_deploy("stage", TEST_BINDINGS_ERROR="forbidden"),
            "existing_app_bindings_unavailable",
        )

    def test_proven_missing_bindings_allow_first_stage(self) -> None:
        result = self.run_deploy("stage", TEST_BINDINGS_ERROR="absent")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("customDomains=[]", self.calls)

    def test_disabled_budget_action_group_blocks_release(self) -> None:
        self.assert_refused(
            self.run_deploy("stage", TEST_ALERT_ENABLED="false"),
            "Budget action group must remain enabled",
        )

    def test_actual_public_dev_environment_is_refused(self) -> None:
        result = self.run_deploy(
            "stage",
            AZURE_ENVIRONMENT="dev",
            AZURE_RESOURCE_GROUP="rg-pii-guard-dev",
            AZURE_DEV_NETWORK_APPROVED="true",
            HOSTED_PUBLIC_ORIGIN="https://guard-dev.watt-mind.com",
            TEST_PUBLIC_NETWORK="Enabled",
        )
        self.assert_refused(result, "actual internal environment")

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

    def test_release_requires_reviewed_project_configuration_account(self) -> None:
        self.assert_refused(
            self.run_deploy("stage", TEST_PROJECT_ACCOUNT="None"), "project configuration"
        )
        self.assert_refused(
            self.run_deploy(
                "stage", TEST_PROJECT_ACCOUNT="https://different.blob.core.windows.net"
            ),
            "project configuration",
        )

    def test_budget_notification_map_casing_does_not_change_release_admission(self) -> None:
        for key in ("Actual50", "actual50", "arbitraryReviewedName"):
            with self.subTest(key=key):
                notifications = {
                    key: {
                        "enabled": True,
                        "operator": "GreaterThanOrEqualTo",
                        "threshold": 50.0,
                        "thresholdType": "Actual",
                        "contactGroups": [GROUP],
                    }
                }
                result = self.run_deploy(
                    "stage", TEST_BUDGET_NOTIFICATIONS=json.dumps(notifications)
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn(GROUP, self.calls)
                self.assertIn("monitor action-group show", self.calls)
                self.assertIn("deployment group create", self.calls)
                self.assertNotIn("notifications.Actual50", self.calls)

    def test_unmonitored_budget_notification_refuses_deployment(self) -> None:
        for notification in (
            {
                "enabled": False,
                "operator": "GreaterThanOrEqualTo",
                "threshold": 50,
                "thresholdType": "Actual",
                "contactGroups": [GROUP],
            },
            {
                "enabled": True,
                "operator": "GreaterThanOrEqualTo",
                "threshold": 80,
                "thresholdType": "Actual",
                "contactGroups": [GROUP],
            },
            {
                "enabled": True,
                "operator": "GreaterThanOrEqualTo",
                "threshold": 50,
                "thresholdType": "Forecasted",
                "contactGroups": [GROUP],
            },
            {
                "enabled": True,
                "operator": "GreaterThanOrEqualTo",
                "threshold": 50,
                "thresholdType": "Actual",
                "contactGroups": [],
            },
        ):
            with self.subTest(notification=notification):
                self.assert_refused(
                    self.run_deploy(
                        "stage", TEST_BUDGET_NOTIFICATIONS=json.dumps({"actual50": notification})
                    ),
                    "Enabled Actual 50%",
                )

    def test_stage_refuses_missing_budget(self) -> None:
        self.assert_refused(
            self.run_deploy("stage", TEST_BUDGET_EXISTS="false"), "budget must exist"
        )

    def test_mutable_image_is_refused(self) -> None:
        self.assert_refused(
            self.run_deploy("stage", HOSTED_IMAGE="piiguardexample.azurecr.io/pii-guard:latest"),
            "Canonical HTTPS origin and immutable ACR digest",
        )

    def test_other_vault_is_refused(self) -> None:
        self.assert_refused(
            self.run_deploy(
                "stage", **{"META_KEY_SECRET_URI": "https://other.example.com/secrets/meta"}
            ),
            "versioned secrets from this foundation",
        )

    def test_budget_over_ceiling_is_refused(self) -> None:
        # LAB-1508: the cap is per environment; prod USD 50, dev stays USD 10.
        self.assert_refused(
            self.run_deploy("stage", HOSTED_SPONSORED_MICRODOLLARS="50000001"),
            "maximum USD 50 for prod",
        )
        self.assert_refused(
            self.run_deploy(
                "stage",
                HOSTED_SPONSORED_MICRODOLLARS="10000001",
                AZURE_ENVIRONMENT="dev",
                AZURE_RESOURCE_GROUP="rg-pii-guard-dev",
                AZURE_DEV_NETWORK_APPROVED="true",
                HOSTED_PUBLIC_ORIGIN="https://guard-dev.watt-mind.com",
            ),
            "maximum USD 10 for dev",
        )

    def test_prod_ceiling_admits_exactly_usd_50_and_dev_exactly_usd_10(self) -> None:
        base = {
            "image": IMAGE,
            "lab_1372_done": True,
            "meta_proxy_owner_risk_accepted": self.WAIVER,
        }
        prod = self.run_sponsored_stage(base, budget="50000000")
        self.assertEqual(prod.returncode, 0, prod.stderr)
        self.assertIn("sponsoredMicrodollars=50000000", self.calls)
        dev_keys = ("private_dev_reviewed", "tailnet_acl", "proxy_tls", "proxy_headers")
        dev_evidence = {**base, **dict.fromkeys(dev_keys, True)}
        dev = self.run_sponsored_stage(dev_evidence, dev=True, budget="10000000")
        self.assertEqual(dev.returncode, 0, dev.stderr)
        self.assertIn("sponsoredMicrodollars=10000000", self.calls)
        self.assert_refused(
            self.run_sponsored_stage(dev_evidence, dev=True, budget="10000001"),
            "maximum USD 10 for dev",
        )

    def test_enable_and_positive_budget_require_lab_gate(self) -> None:
        for mode, budget in (("enable", "0"), ("stage", "1")):
            with self.subTest(mode=mode):
                self.assert_refused(
                    self.run_deploy(mode, HOSTED_SPONSORED_MICRODOLLARS=budget),
                    "HOSTED_RELEASE_EVIDENCE",
                )

    WAIVER: ClassVar[dict[str, str]] = {
        "by": "owner",
        "ref": "LAB-1389",
        "date": "2026-10-28",
        "scope": "hackathon-demo",
    }

    def run_sponsored_stage(self, evidence: object, *, dev: bool = False, budget: str = "1"):
        with tempfile.TemporaryDirectory() as directory:
            review = Path(directory) / "review.json"
            review.write_text(json.dumps(evidence))
            overrides = {
                "HOSTED_RELEASE_EVIDENCE": str(review),
                "HOSTED_SPONSORED_MICRODOLLARS": budget,
                "HOSTED_ALLOCATION_ID": "synthetic-allocation-1",
                "HOSTED_ALLOCATION_EXPIRES_AT": "4102444800",
            }
            if dev:
                overrides.update(
                    AZURE_ENVIRONMENT="dev",
                    AZURE_RESOURCE_GROUP="rg-pii-guard-dev",
                    AZURE_DEV_NETWORK_APPROVED="true",
                    HOSTED_PUBLIC_ORIGIN="https://guard-dev.watt-mind.com",
                )
            return self.run_deploy("stage", **overrides)

    def test_positive_allocation_accepts_authorization_or_named_owner_risk_acceptance(self) -> None:
        base = {"image": IMAGE, "lab_1372_done": True}
        authorized = self.run_sponsored_stage({**base, "meta_proxy_authorized": True})
        self.assertEqual(authorized.returncode, 0, authorized.stderr)
        self.assertNotIn("risk acceptance", authorized.stderr)
        self.assertIn("sponsoredMicrodollars=1", self.calls)
        waived = self.run_sponsored_stage({**base, "meta_proxy_owner_risk_accepted": self.WAIVER})
        self.assertEqual(waived.returncode, 0, waived.stderr)
        self.assertIn("not Meta authorization", waived.stderr)
        self.assertIn("sponsoredMicrodollars=1", self.calls)
        dev = self.run_sponsored_stage(
            {
                **base,
                **dict.fromkeys(
                    ("private_dev_reviewed", "tailnet_acl", "proxy_tls", "proxy_headers"), True
                ),
                "meta_proxy_owner_risk_accepted": self.WAIVER,
            },
            dev=True,
        )
        self.assertEqual(dev.returncode, 0, dev.stderr)
        self.assertIn("sponsoredMicrodollars=1", self.calls)

    def test_positive_allocation_without_authorization_or_waiver_is_refused(self) -> None:
        base = {"image": IMAGE, "lab_1372_done": True}
        for evidence in (base, {**base, "meta_proxy_authorized": False}):
            with self.subTest(evidence=evidence):
                self.assert_refused(self.run_sponsored_stage(evidence), "positive allocation")
        # The waiver never substitutes for other gates: LAB-1372 and image binding still apply.
        for evidence in (
            {"image": IMAGE, "meta_proxy_owner_risk_accepted": self.WAIVER},
            {**base, "image": "other", "meta_proxy_owner_risk_accepted": self.WAIVER},
        ):
            with self.subTest(evidence=evidence):
                self.assert_refused(
                    self.run_sponsored_stage(evidence), "Release evidence incomplete"
                )

    def test_malformed_owner_risk_acceptance_is_refused(self) -> None:
        base = {"image": IMAGE, "lab_1372_done": True}
        for waiver in (
            True,
            "LAB-1389",
            {},
            {**self.WAIVER, "by": "agent"},
            {**self.WAIVER, "ref": "LAB-1372"},
            {**self.WAIVER, "scope": "general-availability"},
            {**self.WAIVER, "date": "28/10/2026"},
            {**self.WAIVER, "date": "2026-02-30"},
            {**self.WAIVER, "date": "2999-01-01"},
            {**self.WAIVER, "extra": True},
            {k: v for k, v in self.WAIVER.items() if k != "date"},
        ):
            with self.subTest(waiver=waiver):
                self.assert_refused(
                    self.run_sponsored_stage({**base, "meta_proxy_owner_risk_accepted": waiver}),
                    "Malformed owner risk acceptance",
                )
        # Even alongside written authorization, a malformed waiver is refused, not ignored.
        self.assert_refused(
            self.run_sponsored_stage(
                {**base, "meta_proxy_authorized": True, "meta_proxy_owner_risk_accepted": {}}
            ),
            "Malformed owner risk acceptance",
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

    def test_invalid_budget_amounts_are_refused_without_rounding(self) -> None:
        for amount in ("NaN", "inf", "-25.0", "25.5"):
            with self.subTest(amount=amount):
                self.assert_refused(
                    self.run_deploy("stage", TEST_BUDGET_AMOUNT=amount), "positive whole amount"
                )

    def test_stage_preserves_existing_action_groups(self) -> None:
        result = self.run_deploy("stage", TEST_BUDGET_AMOUNT="25.0")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(GROUP, self.calls)
        self.assertIn("alertActionGroupIds=", self.calls)
        self.assertNotIn("alertActionGroupIds=[]", self.calls)
        self.assertNotIn("budgetStartDate=", self.calls)
        self.assertNotIn("monthlyBudgetAmount=", self.calls)
        self.assertIn("--template-file deploy/azure/release.bicep", self.calls)
        self.assertIn("projectAccountUrl=https://ledgerexample.blob.core.windows.net", self.calls)
        self.assertIn("customDomains=", self.calls)
        self.assertIn("guard.example.com", self.calls)
        self.assertIn("monitor action-group show", self.calls)


if __name__ == "__main__":
    unittest.main()
