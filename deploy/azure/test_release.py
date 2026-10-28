"""Compile and check the release writer's scope without contacting Azure."""

import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

TEMPLATE = Path(__file__).with_name("release.bicep").resolve()


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

    def env(self) -> dict:
        container = self.resource("Microsoft.App/containerApps")["properties"]["template"][
            "containers"
        ][0]
        return {entry["name"]: entry for entry in container["env"]}

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
        self.assertEqual(
            ingress["external"],
            "[if(equals(parameters('environmentName'), 'dev'), true(), "
            "parameters('publicEnabled'))]",
        )
        self.assertFalse(params["publicEnabled"]["defaultValue"])
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
            "PII_GUARD_HOSTED_MODELS": "muse-spark-1.3",
            "PII_GUARD_TRAFFIC_LOG": "off",
            "PII_GUARD_METRICS": "false",
        }.items():
            self.assertEqual(env[key]["value"], value)
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
        self.assertEqual(probes["Readiness"]["httpGet"]["path"], "/readyz")
        self.assertEqual(probes["Startup"]["failureThreshold"], 60)

    def test_client_ip_attribution_defaults_off_and_dev_forces_off(self) -> None:
        parameter = self.template["parameters"]["clientIpSource"]
        self.assertEqual(parameter["defaultValue"], "off")
        self.assertEqual(parameter["allowedValues"], ["off", "aca_xff_rightmost"])
        self.assertEqual(
            self.env()["PII_GUARD_HOSTED_CLIENT_IP_SOURCE"]["value"],
            "[if(equals(parameters('environmentName'), 'dev'), 'off', "
            "parameters('clientIpSource'))]",
        )

    def test_blob_ledger_is_existing_separate_and_never_automatically_funded(self) -> None:
        parameters = self.template["parameters"]
        self.assertNotIn("defaultValue", parameters["ledgerAccountUrl"])
        ceiling = parameters["sponsoredMicrodollars"]
        self.assertEqual(ceiling["defaultValue"], 0)
        self.assertEqual(ceiling["minValue"], 0)
        self.assertEqual(ceiling["maxValue"], 10_000_000)
        self.assertEqual(parameters["allocationId"]["defaultValue"], "")
        self.assertEqual(parameters["allocationExpiresAt"]["defaultValue"], 0)
        env = self.env()
        for key, value in {
            "PII_GUARD_HOSTED_SPEND_STORE": "azure_blob",
            "PII_GUARD_HOSTED_SPEND_ACCOUNT_URL": "[parameters('ledgerAccountUrl')]",
            "PII_GUARD_HOSTED_SPEND_CONTAINER": "sponsored-allowance",
            "PII_GUARD_HOSTED_SPEND_ENVIRONMENT": "[parameters('environmentName')]",
            "PII_GUARD_HOSTED_SPONSORED_MICRODOLLARS": (
                "[string(parameters('sponsoredMicrodollars'))]"
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


if __name__ == "__main__":
    unittest.main()
