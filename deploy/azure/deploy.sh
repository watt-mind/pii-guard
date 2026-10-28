#!/usr/bin/env bash
# No secret values accepted. Run secrets provisioning separately through an in-memory SDK.
set -Eeuo pipefail
set +x
cd "$(dirname "$0")/../.."
mode=${1:-validate}
case "$mode" in validate|bootstrap|stage|enable|disable) ;; *) echo 'Use validate|bootstrap|stage|enable|disable' >&2; exit 2;; esac
az bicep build --file deploy/azure/main.bicep --stdout >/dev/null
[[ "$mode" != validate ]] || exit 0
: "${AZURE_SUBSCRIPTION_ID:?Set the explicit target subscription}"
: "${AZURE_RESOURCE_GROUP:?Use a dedicated pii-guard hosted resource group}"
: "${AZURE_LOCATION:?Set the reviewed region, for example swedencentral}"
: "${AZURE_PREFIX:=piiguarddemo}"
[[ "$AZURE_RESOURCE_GROUP" == rg-pii-guard-hosted-* ]] || { echo 'Refusing non-dedicated resource group' >&2; exit 2; }
[[ "$AZURE_PREFIX" =~ ^[a-z][a-z0-9-]{2,14}$ ]] || { echo 'Invalid dedicated resource prefix' >&2; exit 2; }
app="${AZURE_PREFIX}-app"
public_attempt=false
rollback_public() {
  code=$?
  trap - ERR
  if [[ "$public_attempt" == true ]]; then
    az containerapp ingress update --name "$app" --resource-group "$AZURE_RESOURCE_GROUP" --type internal --output none || true
    echo 'Enablement failed; attempted to restore internal ingress. Verify isolation before retry.' >&2
  fi
  exit "$code"
}
trap rollback_public ERR
account=$(az account show --query id --output tsv)
[[ "$account" == "$AZURE_SUBSCRIPTION_ID" ]] || { echo 'Active Azure subscription differs from explicit target' >&2; exit 2; }
params=(--parameters "prefix=$AZURE_PREFIX" "location=$AZURE_LOCATION")
if [[ "$mode" == bootstrap ]]; then
  if [[ $(az group exists --name "$AZURE_RESOURCE_GROUP") == true ]]; then
    [[ $(az group show --name "$AZURE_RESOURCE_GROUP" --query tags.project --output tsv) == pii-guard ]] || { echo 'Existing group is not owned by pii-guard' >&2; exit 2; }
    # A bootstrap deployment omits the app, but never intentionally deletes it.
  else
    az group create --name "$AZURE_RESOURCE_GROUP" --location "$AZURE_LOCATION" --tags project=pii-guard purpose=hosted-demo --output none
  fi
else
  [[ $(az group show --name "$AZURE_RESOURCE_GROUP" --query tags.project --output tsv) == pii-guard ]] || { echo 'Missing dedicated group ownership tag' >&2; exit 2; }
  if [[ "$mode" == disable ]]; then
    az containerapp ingress update --name "$app" --resource-group "$AZURE_RESOURCE_GROUP" --type internal --output none
    echo 'External ingress disabled; sponsored allocation must be reconciled before any restart.'
    exit 0
  fi
  : "${HOSTED_IMAGE:?Set immutable registry image@sha256 digest}"
  : "${HOSTED_PUBLIC_ORIGIN:?Set canonical HTTPS origin}"
  : "${GOOGLE_CLIENT_ID:?Set Google OAuth web client id}"
  : "${META_KEY_SECRET_URI:?Set a versioned Key Vault secret URI}"
  : "${TENANT_KEY_SECRET_URI:?Set a versioned Key Vault secret URI}"
  : "${GOOGLE_SECRET_URI:?Set a versioned Key Vault secret URI}"
  [[ "$HOSTED_IMAGE" =~ ^[a-z0-9]+\.azurecr\.io/pii-guard@sha256:[a-f0-9]{64}$ ]] || { echo 'An immutable ACR digest is required' >&2; exit 2; }
  [[ "$HOSTED_PUBLIC_ORIGIN" =~ ^https://[a-z0-9.-]+$ ]] || { echo 'Origin must be a canonical HTTPS hostname' >&2; exit 2; }
  vault_uri=$(az deployment group show --resource-group "$AZURE_RESOURCE_GROUP" --name hosted-foundation --query properties.outputs.vaultUri.value --output tsv)
  for uri in "$META_KEY_SECRET_URI" "$TENANT_KEY_SECRET_URI" "$GOOGLE_SECRET_URI"; do
    [[ "$uri" == "${vault_uri}secrets/"* && "$uri" =~ /secrets/[a-zA-Z0-9-]+/[a-f0-9]{32}$ ]] || { echo 'Use versioned secrets from this deployment Key Vault' >&2; exit 2; }
  done
  registry=$(az deployment group show --resource-group "$AZURE_RESOURCE_GROUP" --name hosted-foundation --query properties.outputs.registryServer.value --output tsv)
  [[ "$HOSTED_IMAGE" == "$registry/"* ]] || { echo 'Image must come from this dedicated registry' >&2; exit 2; }
  sponsored=${HOSTED_SPONSORED_MICRODOLLARS:-0}
  [[ "$sponsored" =~ ^[0-9]+$ && ${#sponsored} -le 8 ]] || { echo 'Invalid sponsored allocation' >&2; exit 2; }
  ((sponsored <= 10000000)) || { echo 'Allocation exceeds the USD 10 deployment ceiling' >&2; exit 2; }
  if ((sponsored > 0)); then
    : "${HOSTED_ALLOCATION_ID:?Set a fresh reconciled allocation id}"
    : "${HOSTED_ALLOCATION_EXPIRES_AT:?Set Unix UTC allocation expiry}"
    [[ "$HOSTED_ALLOCATION_ID" =~ ^[a-zA-Z0-9_-]{8,128}$ ]] || { echo 'Invalid allocation id' >&2; exit 2; }
    [[ "$HOSTED_ALLOCATION_EXPIRES_AT" =~ ^[0-9]{10}$ ]] || { echo 'Invalid allocation expiry' >&2; exit 2; }
    ((HOSTED_ALLOCATION_EXPIRES_AT > $(date +%s))) || { echo 'Allocation is already expired' >&2; exit 2; }
    params+=(--parameters "sponsoredMicrodollars=$sponsored" "allocationId=$HOSTED_ALLOCATION_ID" "allocationExpiresAt=$HOSTED_ALLOCATION_EXPIRES_AT")
  fi
  public=false
  if [[ "$mode" == enable ]]; then
    : "${HOSTED_RELEASE_EVIDENCE:?Path to reviewed release evidence JSON}"
    # Evidence is bound to the exact image, and must be supplied by the release reviewer.
    python3 - "$HOSTED_RELEASE_EVIDENCE" "$HOSTED_IMAGE" <<'PY'
import json, sys
with open(sys.argv[1]) as stream:
    evidence = json.load(stream)
required = ('isolation', 'csrf', 'identity_header_spoofing', 'quotas_restart',
            'ssrf', 'synthetic_roundtrip', 'streaming', 'privacy_review')
if evidence.get('image') != sys.argv[2] or not all(evidence.get(k) is True for k in required):
    raise SystemExit('Release gates incomplete or evidence belongs to a different image')
PY
    # Auth must already exist before opening external ingress: avoid an auth-less first PUT.
    auth_enabled=$(az rest --method get --url "https://management.azure.com/subscriptions/$AZURE_SUBSCRIPTION_ID/resourceGroups/$AZURE_RESOURCE_GROUP/providers/Microsoft.App/containerApps/$app/authConfigs/current?api-version=2025-01-01" --query properties.platform.enabled --output tsv)
    [[ "$auth_enabled" == true ]] || { echo 'Stage Easy Auth before external ingress' >&2; exit 2; }
    public=true
    if [[ -n "${HOSTED_ALERT_ACTION_GROUP_ID:-}" ]]; then
      params+=(--parameters "alertActionGroupIds=[\"$HOSTED_ALERT_ACTION_GROUP_ID\"]")
    fi
  fi
  params+=(--parameters deployApp=true "publicEnabled=$public" "image=$HOSTED_IMAGE" "publicOrigin=$HOSTED_PUBLIC_ORIGIN" "googleClientId=$GOOGLE_CLIENT_ID" "metaKeySecretUri=$META_KEY_SECRET_URI" "tenantKeySecretUri=$TENANT_KEY_SECRET_URI" "googleSecretUri=$GOOGLE_SECRET_URI")
fi
name=hosted-release
[[ "$mode" != bootstrap ]] || name=hosted-foundation
az deployment group validate --resource-group "$AZURE_RESOURCE_GROUP" --template-file deploy/azure/main.bicep "${params[@]}" --output none
[[ "$mode" != enable ]] || public_attempt=true
az deployment group create --resource-group "$AZURE_RESOURCE_GROUP" --name "$name" --template-file deploy/azure/main.bicep "${params[@]}" --output none
if [[ "$mode" == stage || "$mode" == enable ]]; then
  # Poll boundedly; don't emit app config, environment variables or deployment dumps.
  ready=false
  for ((attempt=0; attempt<60; attempt++)); do
    status=$(az containerapp show --name "$app" --resource-group "$AZURE_RESOURCE_GROUP" --query properties.runningStatus --output tsv)
    latest=$(az containerapp show --name "$app" --resource-group "$AZURE_RESOURCE_GROUP" --query properties.latestRevisionName --output tsv)
    admitted=$(az containerapp show --name "$app" --resource-group "$AZURE_RESOURCE_GROUP" --query properties.latestReadyRevisionName --output tsv)
    if [[ "$status" == Running && -n "$latest" && "$latest" == "$admitted" ]]; then ready=true; break; fi
    sleep 10
  done
  [[ "$ready" == true ]] || { echo 'App did not reach Running; keep ingress internal and inspect content-free events' >&2; exit 1; }
fi
if [[ "$mode" == enable ]]; then
  fqdn=$(az containerapp show --name "$app" --resource-group "$AZURE_RESOURCE_GROUP" --query properties.configuration.ingress.fqdn --output tsv)
  hostname=${HOSTED_PUBLIC_ORIGIN#https://}
  if [[ "$hostname" != "$fqdn" ]]; then
    # DNS CNAME and asuid TXT must already be configured. Use platform-managed TLS.
    az containerapp hostname add --name "$app" --resource-group "$AZURE_RESOURCE_GROUP" --hostname "$hostname" --output none
    az containerapp hostname bind --name "$app" --resource-group "$AZURE_RESOURCE_GROUP" --hostname "$hostname" --environment "${AZURE_PREFIX}-env" --validation-method CNAME --output none
  fi
  if ! python3 deploy/azure/smoke.py "$HOSTED_PUBLIC_ORIGIN"; then
    az containerapp ingress update --name "$app" --resource-group "$AZURE_RESOURCE_GROUP" --type internal --output none
    echo 'Public smoke failed; external ingress disabled. Review before retry.' >&2
    exit 1
  fi
fi
echo "Completed $mode; verify readiness and review the configured sponsored allocation before announcing availability."
