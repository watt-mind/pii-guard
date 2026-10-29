"""Compile and check the release writer's scope without contacting Azure."""

import json
import re
import runpy
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

TEMPLATE = Path(__file__).with_name("release.bicep").resolve()
SMOKE = Path(__file__).with_name("smoke.py").resolve()


class _FakeHttps:
    """A fictional public origin: ``/readyz`` answers 503 ``loads`` times, then 200."""

    def __init__(self, loads: int) -> None:
        self.loads = loads
        self.paths: list[str] = []

    def __call__(self, *args: object, **kwargs: object) -> "_FakeHttps":
        return self

    def request(self, method: str, path: str, **kwargs: object) -> None:
        self.paths.append(path)

    def getresponse(self) -> mock.Mock:
        path = self.paths[-1]
        status, body = 200, b"{}"
        if path == "/readyz" and self.paths.count("/readyz") <= self.loads:
            status = 503
        elif path == "/healthz":
            body = b'{"status": "ok", "ner": "ready"}'
        elif path == "/v1/analyze":
            status = 401
        return mock.Mock(status=status, read=mock.Mock(return_value=body))

    def close(self) -> None:
        pass


class SmokeTests(unittest.TestCase):
    def run_smoke(self, loads: int, clock: list[float]) -> _FakeHttps:
        fake = _FakeHttps(loads)
        with (
            mock.patch("http.client.HTTPSConnection", fake),
            mock.patch("time.sleep"),
            mock.patch("time.monotonic", side_effect=clock),
            mock.patch.object(sys, "argv", ["smoke.py", "https://guard.example"]),
            mock.patch("builtins.print"),
        ):
            runpy.run_path(str(SMOKE), run_name="__main__")
        return fake

    def test_smoke_waits_for_the_model_after_the_revision_is_ready(self) -> None:
        # LAB-1548: the revision is admitted while NER loads; smoke waits for full /readyz.
        fake = self.run_smoke(loads=2, clock=[0.0, 5.0, 10.0])
        self.assertEqual(fake.paths[:4], ["/", "/readyz", "/readyz", "/readyz"])

    def test_smoke_fails_when_the_model_never_becomes_ready(self) -> None:
        with self.assertRaisesRegex(SystemExit, "public readiness failed"):
            self.run_smoke(loads=99, clock=[0.0, 100.0, 200.0])


class ReleaseSourceTests(unittest.TestCase):
    def test_no_credential_lookup_or_nested_deployment(self) -> None:
        source = TEMPLATE.read_text()
        self.assertNotRegex(source.lower(), r"\b(?:listkeys|listsecrets)\s*\(")
        self.assertNotRegex(source, r"(?m)^module\s")
        # Existing declarations may be read, but the release must not write foundations.
        for declaration in re.finditer(r"resource\s+\w+\s+'([^']+)'\s+(existing\s+)?=", source):
            resource_type = declaration[1].split("@")[0]
            if resource_type not in {
                "Microsoft.App/containerApps",
                "Microsoft.App/containerApps/authConfigs",
                "Microsoft.Insights/metricAlerts",
            }:
                self.assertIsNotNone(declaration[2], resource_type)


@unittest.skipUnless(shutil.which("az"), "Azure CLI is required to compile Bicep")
class ReleaseTemplateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        result = subprocess.run(  # noqa: S603 - local compiler, no cloud mutation
            [
                shutil.which("az") or "/unavailable-azure-cli",
                "bicep",
                "build",
                "--file",
                str(TEMPLATE),
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

    def container(self) -> dict:
        return self.resource("Microsoft.App/containerApps")["properties"]["template"]["containers"][
            0
        ]

    def env(self) -> dict:
        return {entry["name"]: entry for entry in self.container()["env"]}

    def test_only_application_auth_and_alert_writes(self) -> None:
        self.assertCountEqual(
            [r["type"] for r in self.template["resources"]],
            [
                "Microsoft.App/containerApps",
                "Microsoft.App/containerApps/authConfigs",
                "Microsoft.Insights/metricAlerts",
            ],
        )
        serialized = json.dumps(self.template).lower()
        for forbidden in ("listkeys(", "listsecrets(", "accountkey", "azurefile"):
            self.assertNotIn(forbidden, serialized)

    def test_dev_requires_review_and_uses_environment_external_ingress(self) -> None:
        params = self.template["parameters"]
        self.assertFalse(params["privateDevReviewed"]["defaultValue"])
        self.assertEqual(
            self.template["variables"]["appDeploymentEnabled"],
            "[or(equals(parameters('environmentName'), 'prod'), parameters('privateDevReviewed'))]",
        )
        for resource in self.template["resources"]:
            self.assertEqual(resource["condition"], "[variables('appDeploymentEnabled')]")
        ingress = self.resource("Microsoft.App/containerApps")["properties"]["configuration"][
            "ingress"
        ]
        # LAB-1541: a prod stage keeps whatever external flag the live app already has;
        # only the explicit enable gate (publicEnabled) can open a closed app.
        self.assertEqual(
            ingress["external"],
            "[if(equals(parameters('environmentName'), 'dev'), true(), "
            "or(parameters('publicEnabled'), parameters('preserveExternalIngress')))]",
        )
        self.assertFalse(params["publicEnabled"]["defaultValue"])
        self.assertFalse(params["preserveExternalIngress"]["defaultValue"])
        self.assertFalse(ingress["allowInsecure"])
        self.assertEqual(ingress["targetPort"], 8787)
        self.assertEqual(ingress["customDomains"], "[parameters('customDomains')]")

    def test_existing_custom_domain_bindings_are_explicitly_preserved(self) -> None:
        # An omitted parameter must fail admission instead of silently clearing bindings.
        parameter = self.template["parameters"]["customDomains"]
        self.assertEqual(parameter["type"], "array")
        self.assertNotIn("defaultValue", parameter)
        configuration = self.resource("Microsoft.App/containerApps")["properties"]["configuration"]
        self.assertEqual(configuration["ingress"]["customDomains"], "[parameters('customDomains')]")
        self.assertNotIn("certificates", configuration)

    def test_auth_keeps_google_and_uses_dedicated_dev_proxy_headers(self) -> None:
        auth = self.resource("Microsoft.App/containerApps/authConfigs")["properties"]
        self.assertTrue(auth["platform"]["enabled"])
        self.assertEqual(auth["globalValidation"]["unauthenticatedClientAction"], "AllowAnonymous")
        self.assertTrue(auth["httpSettings"]["requireHttps"])
        proxy = auth["httpSettings"]["forwardProxy"]
        self.assertIn("equals(parameters('environmentName'), 'dev')", proxy)
        for part in (
            "'convention', 'Custom'",
            "'customHostHeaderName', 'X-Pii-Guard-External-Host'",
            "'customProtoHeaderName', 'X-Pii-Guard-External-Proto'",
            "'convention', 'NoProxy'",
        ):
            self.assertIn(part, proxy)
        google = auth["identityProviders"]["google"]
        self.assertTrue(google["enabled"])
        self.assertEqual(google["login"]["scopes"], ["openid", "profile", "email"])
        self.assertEqual(google["registration"]["clientSecretSettingName"], "google-client-secret")
        self.assertFalse(auth["login"]["tokenStore"]["enabled"])
        self.assertEqual(auth["login"]["allowedExternalRedirectUrls"], [])

    def test_single_replica_offline_ner_health_and_hosts(self) -> None:
        template = self.resource("Microsoft.App/containerApps")["properties"]["template"]
        self.assertEqual(template["scale"], {"minReplicas": 0, "maxReplicas": 1})
        self.assertNotIn("volumes", template)
        container = template["containers"][0]
        self.assertEqual(container["image"], "[parameters('image')]")
        self.assertEqual(container["resources"], {"cpu": 2, "memory": "4Gi"})
        self.assertNotIn("volumeMounts", container)
        env = self.env()
        for key, value in {
            "PII_GUARD_HOSTED": "true",
            "PII_GUARD_HOSTED_SINGLE_PROCESS": "true",
            "PII_GUARD_HOSTED_TRUST_EASY_AUTH": "true",
            "PII_GUARD_NER_MODEL": "/app/models/ner",
            "PII_GUARD_DETECTORS": "rules,ner",
            "PII_GUARD_HOSTED_IMAGES": "true",
            "PII_GUARD_SEGMENTER": "local",
            "PII_GUARD_HOSTED_MODELS": "muse-spark-1.3",
            "PII_GUARD_TRAFFIC_LOG": "off",
            "PII_GUARD_METRICS": "false",
        }.items():
            self.assertEqual(env[key]["value"], value)
        # Signatures are masked on-device by the owner's policy: no server override (LAB-1444).
        self.assertNotIn("PII_GUARD_POLICY_OVERRIDES", env)
        hosts = env["PII_GUARD_ALLOWED_HOSTS"]["value"]
        self.assertIn("publicOrigin", hosts)
        self.assertIn("defaultDomain", hosts)
        probes = {probe["type"]: probe for probe in container["probes"]}
        self.assertEqual(set(probes), {"Startup", "Readiness", "Liveness"})
        for probe in probes.values():
            self.assertEqual(probe["httpGet"]["port"], 8787)
            self.assertEqual(
                probe["httpGet"]["httpHeaders"], [{"name": "Host", "value": "localhost"}]
            )
        self.assertEqual(probes["Startup"]["failureThreshold"], 60)

    def test_readiness_admits_the_replica_while_the_model_loads(self) -> None:
        # LAB-1548: scale to zero holds a cold request until a replica is Ready, so Readiness
        # must not wait for the 1 GB NER load (detecting routes do). Startup and Liveness stay
        # on /healthz; a failed model load is never ready on either /readyz form.
        probes = {probe["type"]: probe["httpGet"]["path"] for probe in self.container()["probes"]}
        self.assertEqual(
            probes,
            {"Startup": "/healthz", "Readiness": "/readyz?ner=loading", "Liveness": "/healthz"},
        )

    def test_client_ip_attribution_defaults_off_and_dev_forces_off(self) -> None:
        parameter = self.template["parameters"]["clientIpSource"]
        self.assertEqual(parameter["defaultValue"], "off")
        self.assertEqual(parameter["allowedValues"], ["off", "aca_xff_rightmost"])
        self.assertEqual(
            self.env()["PII_GUARD_HOSTED_CLIENT_IP_SOURCE"]["value"],
            "[if(equals(parameters('environmentName'), 'dev'), 'off', "
            "parameters('clientIpSource'))]",
        )

    def test_sponsored_ceiling_is_per_environment(self) -> None:
        # LAB-1508: prod USD 50 (owner, 2026-10-29); dev stays USD 10. An over-cap release
        # fails template evaluation (int() of a non-numeric string) before any write.
        variables = self.template["variables"]
        self.assertEqual(
            variables["sponsoredCeilingMicrodollars"],
            "[if(equals(parameters('environmentName'), 'prod'), 50000000, 10000000)]",
        )
        self.assertEqual(
            variables["admittedSponsoredMicrodollars"],
            "[if(lessOrEquals(parameters('sponsoredMicrodollars'), "
            "variables('sponsoredCeilingMicrodollars')), parameters('sponsoredMicrodollars'), "
            "int('sponsoredMicrodollars-exceeds-environment-ceiling'))]",
        )
        self.assertNotIn("[string(parameters('sponsoredMicrodollars'))]", json.dumps(self.env()))

    def test_blob_ledger_is_existing_separate_and_never_automatically_funded(self) -> None:
        parameters = self.template["parameters"]
        self.assertNotIn("defaultValue", parameters["ledgerAccountUrl"])
        ceiling = parameters["sponsoredMicrodollars"]
        self.assertEqual(ceiling["defaultValue"], 0)
        self.assertEqual(ceiling["minValue"], 0)
        # @maxValue holds the larger prod cap; the per-environment cap is a template variable.
        self.assertEqual(ceiling["maxValue"], 50_000_000)
        self.assertEqual(parameters["allocationId"]["defaultValue"], "")
        self.assertEqual(parameters["allocationExpiresAt"]["defaultValue"], 0)
        env = self.env()
        for key, value in {
            "PII_GUARD_HOSTED_SPEND_STORE": "azure_blob",
            "PII_GUARD_HOSTED_SPEND_ACCOUNT_URL": "[parameters('ledgerAccountUrl')]",
            "PII_GUARD_HOSTED_SPEND_CONTAINER": "sponsored-allowance",
            "PII_GUARD_HOSTED_SPEND_ENVIRONMENT": "[parameters('environmentName')]",
            "PII_GUARD_HOSTED_SPONSORED_MICRODOLLARS": (
                "[string(variables('admittedSponsoredMicrodollars'))]"
            ),
            "PII_GUARD_HOSTED_SPONSORED_ALLOCATION_ID": "[parameters('allocationId')]",
            "PII_GUARD_HOSTED_ALLOCATION_EXPIRES_AT": (
                "[string(parameters('allocationExpiresAt'))]"
            ),
        }.items():
            self.assertEqual(env[key]["value"], value)
        client = env["PII_GUARD_HOSTED_SPEND_MANAGED_IDENTITY_CLIENT_ID"]["value"]
        self.assertIn("Microsoft.ManagedIdentity/userAssignedIdentities", client)
        self.assertIn(".clientId", client)
        self.assertNotIn("PII_GUARD_HOSTED_ALLOCATION_DIRECTORY", env)
        self.assertNotIn("fund", " ".join(parameters).lower())

    def test_projects_use_encrypted_blob_and_same_environment_runtime_identity(self) -> None:
        parameter = self.template["parameters"]["projectAccountUrl"]
        self.assertEqual(parameter["minLength"], 1)
        self.assertNotIn("defaultValue", parameter)
        env = self.env()
        for key, value in {
            "PII_GUARD_HOSTED_PROJECT_STORE": "azure_blob",
            "PII_GUARD_HOSTED_PROJECT_ACCOUNT_URL": "[parameters('projectAccountUrl')]",
            "PII_GUARD_HOSTED_PROJECT_CONTAINER": "project-configuration",
            "PII_GUARD_HOSTED_PROJECT_ENVIRONMENT": "[parameters('environmentName')]",
        }.items():
            self.assertEqual(env[key]["value"], value)
        self.assertEqual(
            env["PII_GUARD_HOSTED_PROJECT_MANAGED_IDENTITY_CLIENT_ID"],
            {
                "name": "PII_GUARD_HOSTED_PROJECT_MANAGED_IDENTITY_CLIENT_ID",
                "value": env["PII_GUARD_HOSTED_SPEND_MANAGED_IDENTITY_CLIENT_ID"]["value"],
            },
        )
        self.assertEqual(env["PII_GUARD_TENANT_KEY"]["secretRef"], "tenant-key")
        self.assertNotIn("PII_GUARD_PROJECT_STATE_PATH", env)
        for path in (TEMPLATE.parent / "deploy.sh", TEMPLATE.parent / "entrypoint.py"):
            self.assertNotIn("--initialize-empty", path.read_text())

    def test_secret_references_and_preserved_alert_groups_are_required(self) -> None:
        params = self.template["parameters"]
        groups = params["alertActionGroupIds"]
        self.assertEqual(groups["minLength"], 1)
        self.assertNotIn("defaultValue", groups)
        for name in (
            "image",
            "publicOrigin",
            "googleClientId",
            "metaKeySecretUri",
            "tenantKeySecretUri",
            "googleSecretUri",
        ):
            self.assertEqual(params[name]["minLength"], 1)
            self.assertNotIn("defaultValue", params[name])
        secrets = self.resource("Microsoft.App/containerApps")["properties"]["configuration"][
            "secrets"
        ]
        self.assertEqual(len(secrets), 3)
        for secret in secrets:
            self.assertEqual(set(secret), {"name", "keyVaultUrl", "identity"})
            self.assertIn("parameters(", secret["keyVaultUrl"])
        alerts = self.resource("Microsoft.Insights/metricAlerts")["properties"]
        self.assertIn("alertActionGroupIds", json.dumps(alerts["copy"]))


FAKE_SUBSCRIPTION = "00000000-0000-4000-8000-000000000000"
FAKE_VAULT = "https://piiguardkv.vault.azure.net/"
FAKE_REGISTRY = "piiguardprod.azurecr.io"
FAKE_ACCOUNT = "https://piiguardsp.blob.core.windows.net"
FAKE_GROUP = (
    f"/subscriptions/{FAKE_SUBSCRIPTION}/resourceGroups/rg-pii-guard-prod"
    "/providers/Microsoft.Insights/actionGroups/fictional-oncall"
)

# Stand-in for the Azure CLI: answers only the read-only queries deploy.sh makes, records
# every call, and refuses anything unexpected. The real az is never on PATH for these runs.
FAKE_AZ = r"""#!PYTHON
import json, os, sys
args = sys.argv[1:]
with open(os.environ["FAKE_AZ_LOG"], "a") as log:
    log.write(json.dumps(args) + "\n")
def arg(flag):
    return args[args.index(flag) + 1] if flag in args else ""
def out(value):
    print(value)
    raise SystemExit(0)
query, head = arg("--query"), args[:3]
if args[:2] == ["bicep", "build"]: out("{}")
if args[:2] == ["account", "show"]: out(os.environ["FAKE_SUBSCRIPTION"])
if args[:2] == ["resource", "show"] and query == "properties.amount": out("50")
if args[:2] == ["resource", "show"] and query == "properties.notifications":
    out(json.dumps({"actual50": {"enabled": True, "operator": "GreaterThan", "threshold": 50,
        "thresholdType": "Actual", "contactGroups": [os.environ["FAKE_GROUP"]]}}))
if args[:2] == ["monitor", "action-group"]: out("true")
if args[:2] == ["group", "exists"]: out("true")
if args[:2] == ["group", "show"]:
    out({"tags.project": "pii-guard", "tags.environment": "prod",
         "location": "swedencentral"}[query])
if head == ["deployment", "group", "show"]:
    out({"properties.outputs.vaultUri.value": os.environ["FAKE_VAULT"],
         "properties.outputs.registryServer.value": os.environ["FAKE_REGISTRY"],
         "properties.outputs.ledgerAccountUrl.value": os.environ["FAKE_ACCOUNT"],
         "properties.outputs.projectAccountUrl.value": os.environ["FAKE_ACCOUNT"]}[query])
if args[:2] == ["containerapp", "show"]:
    live = os.environ["FAKE_LIVE_EXTERNAL"]
    if live == "missing" and "ingress" in query:
        print("ERROR: (ResourceNotFound) The Resource was not found.", file=sys.stderr)
        raise SystemExit(3)
    if live == "unavailable" and query == "properties.configuration.ingress.external":
        print("ERROR: (AuthorizationFailed) transient", file=sys.stderr)
        raise SystemExit(1)
    if query == "properties.configuration.ingress.customDomains": out("[]")
    if query == "properties.configuration.ingress.external": out(live)
    if query in ("properties.latestRevisionName", "properties.latestReadyRevisionName"):
        out("piiguard-prod-app--r1")
if args[:2] == ["rest", "--method"] and arg("--method") == "get": out("true")
if head in (["deployment", "group", "validate"], ["deployment", "group", "create"]):
    if head[2] == "create" and os.environ.get("FAKE_FAIL_CREATE") == "1": raise SystemExit(1)
    raise SystemExit(0)
if args[:3] == ["containerapp", "ingress", "update"]: raise SystemExit(0)
print("fake az: unexpected call", file=sys.stderr)
raise SystemExit(97)
"""


@unittest.skipUnless(shutil.which("bash"), "bash is required to run the release driver")
class ReleaseDriverIngressTests(unittest.TestCase):
    """Run deploy.sh against a recording fake az: nothing here can reach Azure."""

    def run_driver(self, mode: str, live: str, **extra: str) -> tuple:
        root = Path(tempfile.mkdtemp(prefix="lab1541-"))
        self.addCleanup(shutil.rmtree, root, True)
        bin_dir = root / "bin"
        bin_dir.mkdir()
        fake = bin_dir / "az"
        fake.write_text(FAKE_AZ.replace("PYTHON", sys.executable, 1))
        fake.chmod(0o755)
        (bin_dir / "python3").symlink_to(sys.executable)
        log = root / "az.jsonl"
        evidence = root / "evidence.json"
        image = f"{FAKE_REGISTRY}/pii-guard@sha256:{'a' * 64}"
        evidence.write_text(
            json.dumps(
                {
                    "image": image,
                    **dict.fromkeys(
                        [
                            "lab_1372_done",
                            "isolation",
                            "csrf",
                            "identity_header_spoofing",
                            "quotas_restart",
                            "ssrf",
                            "synthetic_roundtrip",
                            "streaming",
                            "privacy_review",
                        ],
                        True,
                    ),
                }
            )
        )
        secret = FAKE_VAULT + "secrets/{}/" + "b" * 32
        env = {
            # Only the fake az is reachable; the real CLI's directory is never on PATH.
            "PATH": f"{bin_dir}:/usr/bin:/bin",
            "HOME": str(root),
            "FAKE_AZ_LOG": str(log),
            "FAKE_LIVE_EXTERNAL": live,
            "FAKE_SUBSCRIPTION": FAKE_SUBSCRIPTION,
            "FAKE_VAULT": FAKE_VAULT,
            "FAKE_REGISTRY": FAKE_REGISTRY,
            "FAKE_ACCOUNT": FAKE_ACCOUNT,
            "FAKE_GROUP": FAKE_GROUP,
            "AZURE_SUBSCRIPTION_ID": FAKE_SUBSCRIPTION,
            "AZURE_ENVIRONMENT": "prod",
            "HOSTED_IMAGE": image,
            "HOSTED_PUBLIC_ORIGIN": "https://guard.example.test",
            "HOSTED_RELEASE_EVIDENCE": str(evidence),
            "GOOGLE_CLIENT_ID": "fictional-client.apps.example.test",
            "META_KEY_SECRET_URI": secret.format("meta-key"),
            "TENANT_KEY_SECRET_URI": secret.format("tenant-key"),
            "GOOGLE_SECRET_URI": secret.format("google-client-secret"),
            **extra,
        }
        result = subprocess.run(  # noqa: S603 - local driver against a fake az, no cloud
            [shutil.which("bash") or "/bin/bash", str(TEMPLATE.parent / "deploy.sh"), mode],
            capture_output=True,
            text=True,
            env=env,
            check=False,
            timeout=120,
        )
        calls = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
        return result, calls

    @staticmethod
    def deployment_parameters(calls: list, verb: str) -> dict:
        found = [c for c in calls if c[:3] == ["deployment", "group", verb]]
        assert len(found) == 1, found  # noqa: S101 - test helper
        values = {}
        for item in found[0]:
            name, sep, value = item.partition("=")
            if sep and re.fullmatch(r"[A-Za-z]+", name):
                values[name] = value
        return values

    def test_prod_stage_preserves_live_public_ingress(self) -> None:
        # The LAB-1541 outage: staging a release on a live public app rewrote it internal.
        result, calls = self.run_driver("stage", "true")
        self.assertEqual(result.returncode, 0, result.stderr)
        for verb in ("validate", "create"):
            params = self.deployment_parameters(calls, verb)
            self.assertEqual(params["publicEnabled"], "false")
            self.assertEqual(params["preserveExternalIngress"], "true")
        self.assertNotIn(["containerapp", "ingress", "update"], [c[:3] for c in calls])

    def test_prod_stage_keeps_internal_app_internal(self) -> None:
        for live in ("false", ""):
            with self.subTest(live=live):
                result, calls = self.run_driver("stage", live)
                self.assertEqual(result.returncode, 0, result.stderr)
                params = self.deployment_parameters(calls, "create")
                self.assertEqual(params["publicEnabled"], "false")
                self.assertEqual(params["preserveExternalIngress"], "false")

    def test_prod_stage_of_new_app_stays_internal(self) -> None:
        result, calls = self.run_driver("stage", "missing")
        self.assertEqual(result.returncode, 0, result.stderr)
        params = self.deployment_parameters(calls, "create")
        self.assertEqual(params["preserveExternalIngress"], "false")

    def test_unreadable_ingress_refuses_before_any_write(self) -> None:
        result, calls = self.run_driver("stage", "unavailable")
        self.assertNotEqual(result.returncode, 0)
        verbs = [c[:3] for c in calls]
        self.assertNotIn(["deployment", "group", "create"], verbs)
        self.assertNotIn(["deployment", "group", "validate"], verbs)

    def test_enable_remains_the_only_mode_that_opens_ingress(self) -> None:
        # Fail the write so the driver stops before its public smoke; the arguments are what
        # matter, and the failed enable must still roll ingress back to internal.
        result, calls = self.run_driver("enable", "false", FAKE_FAIL_CREATE="1")
        self.assertNotEqual(result.returncode, 0)
        params = self.deployment_parameters(calls, "create")
        self.assertEqual(params["publicEnabled"], "true")
        self.assertEqual(params["preserveExternalIngress"], "false")
        self.assertIn(["containerapp", "ingress", "update"], [c[:3] for c in calls])


@unittest.skipUnless(shutil.which("az"), "Azure CLI is required to compile Bicep")
class SpendLedgerFoundationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        result = subprocess.run(  # noqa: S603 - local compiler, no cloud mutation
            [
                shutil.which("az") or "/unavailable-azure-cli",
                "bicep",
                "build",
                "--file",
                str(TEMPLATE.parent / "modules" / "spend-ledger.bicep"),
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

    def test_storage_requires_identity_and_https(self) -> None:
        account = self.resource("Microsoft.Storage/storageAccounts")
        self.assertEqual(account["kind"], "StorageV2")
        self.assertEqual(account["sku"]["name"], "Standard_LRS")
        properties = account["properties"]
        self.assertEqual(properties["minimumTlsVersion"], "TLS1_2")
        self.assertTrue(properties["supportsHttpsTrafficOnly"])
        self.assertFalse(properties["allowSharedKeyAccess"])
        self.assertFalse(properties["allowBlobPublicAccess"])
        self.assertFalse(properties["isHnsEnabled"])
        self.assertTrue(properties["defaultToOAuthAuthentication"])
        self.assertIn("sp", account["name"])
        container = self.resource("Microsoft.Storage/storageAccounts/blobServices/containers")
        self.assertEqual(container["properties"]["publicAccess"], "None")
        self.assertEqual(self.template["variables"]["ledgerContainer"], "sponsored-allowance")

    def test_role_only_reads_and_writes_one_container_for_runtime_identity(self) -> None:
        role = self.resource("Microsoft.Authorization/roleDefinitions")["properties"]
        self.assertEqual(role["type"], "CustomRole")
        self.assertEqual(role["assignableScopes"], ["[resourceGroup().id]"])
        self.assertEqual(
            role["permissions"],
            [
                {
                    "actions": [],
                    "notActions": [],
                    "dataActions": [
                        "Microsoft.Storage/storageAccounts/blobServices/containers/blobs/read",
                        "Microsoft.Storage/storageAccounts/blobServices/containers/blobs/write",
                    ],
                    "notDataActions": [],
                }
            ],
        )
        writer = self.resource("Microsoft.Authorization/roleAssignments")
        self.assertIn("blobServices/containers", writer["scope"])
        self.assertEqual(
            writer["properties"]["principalId"], "[parameters('runtimeIdentityPrincipalId')]"
        )
        self.assertEqual(writer["properties"]["principalType"], "ServicePrincipal")
        self.assertIn(
            "Microsoft.Authorization/roleDefinitions", writer["properties"]["roleDefinitionId"]
        )

    def test_abac_restricts_exact_blob_path_and_refuses_listing(self) -> None:
        writer = self.resource("Microsoft.Authorization/roleAssignments")["properties"]
        self.assertEqual(writer["conditionVersion"], "2.0")
        self.assertEqual(writer["condition"], "[variables('pathCondition')]")
        condition = self.template["variables"]["pathCondition"].replace("''", "'")
        self.assertIn("!(ActionMatches{", condition)
        self.assertIn("AND SubOperationMatches{'Blob.List'}", condition)
        self.assertIn(
            "Microsoft.Storage/storageAccounts/blobServices/containers/blobs/read", condition
        )
        self.assertIn(
            "Microsoft.Storage/storageAccounts/blobServices/containers/blobs/write", condition
        )
        self.assertIn(
            "@Resource[Microsoft.Storage/storageAccounts/blobServices/containers/blobs:path] "
            "StringEquals",
            condition,
        )
        self.assertIn("parameters('envName')", condition)
        self.assertIn(".json", condition)
        self.assertNotIn("StringLike", condition)

    def test_dev_is_private_with_endpoint_and_dns_no_public_fallback(self) -> None:
        properties = self.resource("Microsoft.Storage/storageAccounts")["properties"]
        self.assertEqual(
            properties["publicNetworkAccess"],
            "[if(equals(parameters('envName'), 'dev'), 'Disabled', 'Enabled')]",
        )
        self.assertEqual(properties["networkAcls"]["bypass"], "None")
        self.assertEqual(
            properties["networkAcls"]["defaultAction"],
            "[if(equals(parameters('envName'), 'dev'), 'Deny', 'Allow')]",
        )
        for kind in (
            "Microsoft.Network/privateDnsZones",
            "Microsoft.Network/privateDnsZones/virtualNetworkLinks",
            "Microsoft.Network/privateEndpoints",
            "Microsoft.Network/privateEndpoints/privateDnsZoneGroups",
        ):
            self.assertEqual(
                self.resource(kind)["condition"], "[equals(parameters('envName'), 'dev')]"
            )
        endpoint = self.resource("Microsoft.Network/privateEndpoints")["properties"]
        self.assertEqual(endpoint["subnet"]["id"], "[parameters('devPrivateEndpointSubnetId')]")
        self.assertEqual(
            endpoint["privateLinkServiceConnections"][0]["properties"]["groupIds"], ["blob"]
        )
        link = self.resource("Microsoft.Network/privateDnsZones/virtualNetworkLinks")["properties"]
        self.assertEqual(link["virtualNetwork"]["id"], "[parameters('devVnetId')]")
        self.assertFalse(link["registrationEnabled"])
        zone = self.resource("Microsoft.Network/privateDnsZones")
        self.assertIn("privatelink.blob.", zone["name"])
        self.assertIn("suffixes.storage", zone["name"])

    def test_foundation_has_no_funding_blob_or_credential_lookup(self) -> None:
        self.assertCountEqual(
            [r["type"] for r in self.template["resources"]],
            [
                "Microsoft.Storage/storageAccounts",
                "Microsoft.Storage/storageAccounts/blobServices",
                "Microsoft.Storage/storageAccounts/blobServices/containers",
                "Microsoft.Authorization/roleDefinitions",
                "Microsoft.Authorization/roleAssignments",
                "Microsoft.Network/privateDnsZones",
                "Microsoft.Network/privateDnsZones/virtualNetworkLinks",
                "Microsoft.Network/privateEndpoints",
                "Microsoft.Network/privateEndpoints/privateDnsZoneGroups",
            ],
        )
        serialized = json.dumps(self.template).lower()
        for forbidden in ("listkeys(", "listsecrets(", "accountkey", "sasurl", "funding"):
            self.assertNotIn(forbidden, serialized)
        self.assertEqual(set(self.template["outputs"]), {"accountUrl", "accountName", "container"})


@unittest.skipUnless(shutil.which("az"), "Azure CLI is required to compile Bicep")
class DevNetworkTemplateTests(unittest.TestCase):
    def test_platform_defaults_need_no_allow_rules_and_egress_stays_restricted(self) -> None:
        result = subprocess.run(  # noqa: S603 - local compiler, no cloud mutation
            [
                shutil.which("az") or "/unavailable-azure-cli",
                "bicep",
                "build",
                "--file",
                str(TEMPLATE.parent / "modules" / "dev-network.bicep"),
                "--stdout",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        template = json.loads(result.stdout)
        nsg = next(
            resource
            for resource in template["resources"]
            if resource["type"] == "Microsoft.Network/networkSecurityGroups"
            and "router-nsg" in resource["name"]
        )
        rules = {rule["name"]: rule["properties"] for rule in nsg["properties"]["securityRules"]}
        for rule in rules.values():
            self.assertNotIn(
                rule["destinationAddressPrefix"], {"AzurePlatformDNS", "AzurePlatformIMDS"}
            )
        for name, direction in (
            ("deny-other-outbound", "Outbound"),
            ("deny-unsolicited-inbound", "Inbound"),
        ):
            self.assertEqual(rules[name]["direction"], direction)
            self.assertEqual(rules[name]["access"], "Deny")
            self.assertEqual(rules[name]["destinationAddressPrefix"], "*")
        self.assertEqual(rules["private-aca-https"]["access"], "Allow")


@unittest.skipUnless(shutil.which("az"), "Azure CLI is required to compile Bicep")
class ProjectConfigurationFoundationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        result = subprocess.run(  # noqa: S603 - local compiler, no cloud mutation
            [
                shutil.which("az") or "/unavailable-azure-cli",
                "bicep",
                "build",
                "--file",
                str(TEMPLATE.parent / "modules" / "project-configuration.bicep"),
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

    def test_only_private_container_and_bounded_role_are_written(self) -> None:
        self.assertCountEqual(
            [r["type"] for r in self.template["resources"]],
            [
                "Microsoft.Storage/storageAccounts/blobServices/containers",
                "Microsoft.Authorization/roleDefinitions",
                "Microsoft.Authorization/roleAssignments",
            ],
        )
        container = self.resource("Microsoft.Storage/storageAccounts/blobServices/containers")
        self.assertIn("'project-configuration'", container["name"])
        self.assertEqual(container["properties"], {"publicAccess": "None"})
        for forbidden in ("listkeys(", "listsecrets(", "accountkey", "sasurl"):
            self.assertNotIn(forbidden, json.dumps(self.template).lower())
        self.assertEqual(self.template["parameters"]["envName"]["allowedValues"], ["prod", "dev"])

    def test_runtime_permission_is_container_scoped_read_write_only(self) -> None:
        permissions = self.resource("Microsoft.Authorization/roleDefinitions")["properties"][
            "permissions"
        ]
        self.assertEqual(
            permissions,
            [
                {
                    "actions": [],
                    "notActions": [],
                    "dataActions": [
                        "Microsoft.Storage/storageAccounts/blobServices/containers/blobs/read",
                        "Microsoft.Storage/storageAccounts/blobServices/containers/blobs/write",
                    ],
                    "notDataActions": [],
                }
            ],
        )
        assignment = self.resource("Microsoft.Authorization/roleAssignments")
        self.assertIn("project-configuration", assignment["scope"])
        self.assertEqual(
            assignment["properties"]["principalId"], "[parameters('runtimeIdentityPrincipalId')]"
        )
        self.assertEqual(assignment["properties"]["principalType"], "ServicePrincipal")
        self.assertEqual(assignment["properties"]["conditionVersion"], "2.0")
        self.assertEqual(
            assignment["properties"]["condition"], "[variables('projectPathCondition')]"
        )
        condition = self.template["variables"]["projectPathCondition"].replace("''", "'")
        self.assertIn("AND SubOperationMatches{'Blob.List'}", condition)
        self.assertIn("containers/blobs:path] StringEquals", condition)
        self.assertIn("parameters('envName')", condition)
        self.assertIn(".projects.v1.enc", condition)
        self.assertNotIn("StringLike", condition)

    def test_foundation_reuses_identity_only_private_account_and_environment_identity(self) -> None:
        # Parent module dependencies reuse the spend account's private endpoint and DNS.
        source = (TEMPLATE.parent / "main.bicep").read_text()
        self.assertIn("storageAccountName: spendLedger.outputs.accountName", source)
        self.assertIn("runtimeIdentityPrincipalId: identity.properties.principalId", source)
        self.assertIn(
            "output projectAccountUrl string = projectConfiguration.outputs.accountUrl", source
        )


if __name__ == "__main__":
    unittest.main()
