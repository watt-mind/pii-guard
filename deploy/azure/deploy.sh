#!/usr/bin/env bash
# Secret values are never accepted; migrate them separately in memory.
set -Eeuo pipefail
set +x
cd "$(dirname "$0")/../.."
mode=${1:-validate}
case "$mode" in validate|bootstrap|stage|enable|disable) ;; *) echo 'Use validate|bootstrap|stage|enable|disable' >&2; exit 2;; esac
az bicep build --file deploy/azure/main.bicep --stdout >/dev/null
[[ "$mode" != validate ]] || exit 0
: "${AZURE_SUBSCRIPTION_ID:?Set the explicit target subscription}"
AZURE_ENVIRONMENT=${AZURE_ENVIRONMENT:-prod}
AZURE_PROJECT_PREFIX=${AZURE_PROJECT_PREFIX:-piiguard}
AZURE_RESOURCE_GROUP=${AZURE_RESOURCE_GROUP:-rg-pii-guard-${AZURE_ENVIRONMENT}}
AZURE_LOCATION=${AZURE_LOCATION:-swedencentral}
[[ "$AZURE_ENVIRONMENT" == prod || "$AZURE_ENVIRONMENT" == staging ]] || { echo 'Environment must be prod or staging' >&2; exit 2; }
[[ "$AZURE_PROJECT_PREFIX" =~ ^[a-z][a-z0-9]{2,9}$ ]] || { echo 'Invalid project prefix' >&2; exit 2; }
[[ "$AZURE_RESOURCE_GROUP" == "rg-pii-guard-${AZURE_ENVIRONMENT}" ]] || { echo 'Refusing non-dedicated resource group' >&2; exit 2; }
name_prefix="${AZURE_PROJECT_PREFIX}-${AZURE_ENVIRONMENT}"
app="${name_prefix}-app"
budget_id="/subscriptions/$AZURE_SUBSCRIPTION_ID/resourceGroups/$AZURE_RESOURCE_GROUP/providers/Microsoft.Consumption/budgets/${name_prefix}-budget"
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
params=(--parameters "projectPrefix=$AZURE_PROJECT_PREFIX" "environmentName=$AZURE_ENVIRONMENT" "location=$AZURE_LOCATION")
if [[ "$mode" == bootstrap ]]; then
  : "${AZURE_MONTHLY_BUDGET_AMOUNT:?Set the owner-approved amount in subscription billing currency}"
  : "${AZURE_ALERT_ACTION_GROUP_ID:?Select an existing Azure Monitor action group}"
  [[ "$AZURE_MONTHLY_BUDGET_AMOUNT" =~ ^[1-9][0-9]{0,5}$ ]] || { echo 'Invalid monthly budget amount' >&2; exit 2; }
  groups=$(python3 -c 'import json,os; print(json.dumps([os.environ["AZURE_ALERT_ACTION_GROUP_ID"]]))')
  provisioner=${AZURE_SECRET_PROVISIONER_OBJECT_ID:-$(az ad signed-in-user show --query id --output tsv)}
  [[ "$provisioner" =~ ^[a-fA-F0-9-]{36}$ ]] || { echo 'Set the secret provisioning principal object ID' >&2; exit 2; }
  params+=(--parameters "provisioningPrincipalObjectId=$provisioner")
else
  # A real group budget is mandatory before every application deployment, even staging.
  if [[ "$mode" != disable ]]; then
    AZURE_MONTHLY_BUDGET_AMOUNT=$(az resource show --ids "$budget_id" --api-version 2023-11-01 --query properties.amount --output tsv 2>/dev/null) || { echo 'A resource-group budget must exist before stage or enable' >&2; exit 2; }
    groups=$(az resource show --ids "$budget_id" --api-version 2023-11-01 --query properties.notifications.Actual50.contactGroups --output json)
    budget_start=$(az resource show --ids "$budget_id" --api-version 2023-11-01 --query properties.timePeriod.startDate --output tsv)
    [[ "$AZURE_MONTHLY_BUDGET_AMOUNT" =~ ^[1-9][0-9]*$ ]] || { echo 'Existing budget amount is invalid' >&2; exit 2; }
    params+=(--parameters "budgetStartDate=$budget_start")
    # Preserve budget/metric notification recipients when stage has no override.
    if [[ -n "${AZURE_ALERT_ACTION_GROUP_ID:-}" ]]; then
      groups=$(python3 -c 'import json,os; print(json.dumps([os.environ["AZURE_ALERT_ACTION_GROUP_ID"]]))')
    fi
  fi
fi
if [[ "$mode" != disable ]]; then
  python3 - "$groups" <<'PY'
import json, re, sys
ids = json.loads(sys.argv[1])
pattern = r'/subscriptions/[^/]+/resourceGroups/[^/]+/providers/Microsoft.Insights/actionGroups/[^/]+'
if not isinstance(ids, list) or not ids or not all(isinstance(x,str) and re.fullmatch(pattern,x,re.I) for x in ids):
    raise SystemExit('At least one existing Azure action group is required')
PY
  while IFS= read -r group_id; do
    enabled=$(az monitor action-group show --ids "$group_id" --query enabled --output tsv)
    [[ "$enabled" == true ]] || { echo 'Budget action group must exist and be enabled' >&2; exit 2; }
  done < <(python3 -c 'import json,sys; print("\n".join(json.loads(sys.argv[1])))' "$groups")
  params+=(--parameters "monthlyBudgetAmount=$AZURE_MONTHLY_BUDGET_AMOUNT" "alertActionGroupIds=$groups")
fi
if [[ $(az group exists --name "$AZURE_RESOURCE_GROUP") == true ]]; then
  [[ $(az group show --name "$AZURE_RESOURCE_GROUP" --query tags.project --output tsv) == pii-guard ]] || { echo 'Existing group is not owned by pii-guard' >&2; exit 2; }
  [[ $(az group show --name "$AZURE_RESOURCE_GROUP" --query tags.environment --output tsv) == "$AZURE_ENVIRONMENT" ]] || { echo 'Existing group environment differs' >&2; exit 2; }
  [[ $(az group show --name "$AZURE_RESOURCE_GROUP" --query location --output tsv) == "$AZURE_LOCATION" ]] || { echo 'Resource group region differs; do not deploy across regions' >&2; exit 2; }
  if [[ "$mode" == bootstrap ]]; then
    budget_start=$(az resource show --ids "$budget_id" --api-version 2023-11-01 --query properties.timePeriod.startDate --output tsv 2>/dev/null || true)
    [[ -z "$budget_start" ]] || params+=(--parameters "budgetStartDate=$budget_start")
  fi
else
  [[ "$mode" == bootstrap ]] || { echo 'Bootstrap the dedicated foundation first' >&2; exit 2; }
  az group create --name "$AZURE_RESOURCE_GROUP" --location "$AZURE_LOCATION" --tags project=pii-guard "environment=$AZURE_ENVIRONMENT" --output none
fi
if [[ "$mode" == disable ]]; then
  az containerapp ingress update --name "$app" --resource-group "$AZURE_RESOURCE_GROUP" --type internal --output none
  echo 'External ingress disabled; reconcile sponsored allocation before any restart.'
  exit 0
fi
if [[ "$mode" != bootstrap ]]; then
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
  if [[ "$mode" == enable ]] || ((sponsored > 0)); then
    : "${HOSTED_RELEASE_EVIDENCE:?Review LAB-1372 Done and release evidence before enable or sponsored spend}"
    python3 - "$HOSTED_RELEASE_EVIDENCE" "$HOSTED_IMAGE" "$mode" "$sponsored" <<'PY'
import json, sys
with open(sys.argv[1]) as stream:
    evidence = json.load(stream)
required = ['lab_1372_done']
if sys.argv[3] == 'enable':
    required += ['isolation', 'csrf', 'identity_header_spoofing', 'quotas_restart',
                 'ssrf', 'synthetic_roundtrip', 'streaming', 'privacy_review']
if int(sys.argv[4]) > 0:
    required += ['meta_proxy_authorized']
if evidence.get('image') != sys.argv[2] or not all(evidence.get(k) is True for k in required):
    raise SystemExit('Release gates incomplete: LAB-1372 must be Done; sponsored Meta needs written authorization')
PY
  fi
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
    auth_enabled=$(az rest --method get --url "https://management.azure.com/subscriptions/$AZURE_SUBSCRIPTION_ID/resourceGroups/$AZURE_RESOURCE_GROUP/providers/Microsoft.App/containerApps/$app/authConfigs/current?api-version=2025-01-01" --query properties.platform.enabled --output tsv)
    [[ "$auth_enabled" == true ]] || { echo 'Stage Easy Auth before external ingress' >&2; exit 2; }
    public=true
  fi
  params+=(--parameters deployApp=true "publicEnabled=$public" "image=$HOSTED_IMAGE" "publicOrigin=$HOSTED_PUBLIC_ORIGIN" "googleClientId=$GOOGLE_CLIENT_ID" "metaKeySecretUri=$META_KEY_SECRET_URI" "tenantKeySecretUri=$TENANT_KEY_SECRET_URI" "googleSecretUri=$GOOGLE_SECRET_URI")
fi
name=hosted-release
[[ "$mode" != bootstrap ]] || name=hosted-foundation
az deployment group validate --resource-group "$AZURE_RESOURCE_GROUP" --template-file deploy/azure/main.bicep "${params[@]}" --output none
[[ "$mode" != enable ]] || public_attempt=true
az deployment group create --resource-group "$AZURE_RESOURCE_GROUP" --name "$name" --template-file deploy/azure/main.bicep "${params[@]}" --output none
if [[ "$mode" == stage || "$mode" == enable ]]; then
  ready=false
  for ((attempt=0; attempt<60; attempt++)); do
    latest=$(az containerapp show --name "$app" --resource-group "$AZURE_RESOURCE_GROUP" --query properties.latestRevisionName --output tsv)
    admitted=$(az containerapp show --name "$app" --resource-group "$AZURE_RESOURCE_GROUP" --query properties.latestReadyRevisionName --output tsv)
    if [[ -n "$latest" && "$latest" == "$admitted" ]]; then ready=true; break; fi
    sleep 10
  done
  if [[ "$ready" != true ]]; then
    echo 'App revision did not become ready; restoring internal ingress' >&2
    if [[ "$mode" == enable ]]; then
      az containerapp ingress update --name "$app" --resource-group "$AZURE_RESOURCE_GROUP" --type internal --output none
    fi
    exit 1
  fi
fi
if [[ "$mode" == enable ]]; then
  fqdn=$(az containerapp show --name "$app" --resource-group "$AZURE_RESOURCE_GROUP" --query properties.configuration.ingress.fqdn --output tsv)
  hostname=${HOSTED_PUBLIC_ORIGIN#https://}
  if [[ "$hostname" != "$fqdn" ]]; then
    az containerapp hostname add --name "$app" --resource-group "$AZURE_RESOURCE_GROUP" --hostname "$hostname" --output none
    az containerapp hostname bind --name "$app" --resource-group "$AZURE_RESOURCE_GROUP" --hostname "$hostname" --environment "${name_prefix}-env" --validation-method CNAME --output none
  fi
  if ! python3 deploy/azure/smoke.py "$HOSTED_PUBLIC_ORIGIN"; then
    az containerapp ingress update --name "$app" --resource-group "$AZURE_RESOURCE_GROUP" --type internal --output none
    echo 'Public smoke failed; external ingress disabled. Review before retry.' >&2
    exit 1
  fi
fi
echo "Completed $mode; budget alerts are not a hard cap. No old resource group was deleted."
