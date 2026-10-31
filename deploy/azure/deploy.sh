#!/usr/bin/env bash
# Operator foundation and least-privilege app release are deliberately separate templates.
set -Eeuo pipefail
set +x
cd "$(dirname "$0")/../.."
mode=${1:-validate}
if [[ "$mode" == ci-preflight ]]; then
  exec python3 deploy/azure/release_contract.py "${2:?Specify dev or prod}"
fi
case "$mode" in validate|bootstrap|bootstrap-router|stage|technical-stage|enable|disable|bind-domain) ;; *) echo 'Use validate|ci-preflight|bootstrap|bootstrap-router|stage|technical-stage|enable|disable|bind-domain' >&2; exit 2;; esac
operator=false
[[ "$mode" != bootstrap && "$mode" != bootstrap-router ]] || operator=true
template=deploy/azure/release.bicep
[[ "$operator" != true ]] || template=deploy/azure/main.bicep
az bicep build --file "$template" --stdout >/dev/null
if [[ "$mode" == validate ]]; then
  az bicep build --file deploy/azure/main.bicep --stdout >/dev/null
  exit 0
fi
: "${AZURE_SUBSCRIPTION_ID:?Set the explicit target subscription}"
AZURE_ENVIRONMENT=${AZURE_ENVIRONMENT:-prod}
AZURE_PROJECT_PREFIX=${AZURE_PROJECT_PREFIX:-piiguard}
AZURE_RESOURCE_GROUP=${AZURE_RESOURCE_GROUP:-rg-pii-guard-${AZURE_ENVIRONMENT}}
AZURE_LOCATION=${AZURE_LOCATION:-swedencentral}
[[ "$AZURE_ENVIRONMENT" == prod || "$AZURE_ENVIRONMENT" == dev ]] || { echo 'Environment must be prod or dev' >&2; exit 2; }
[[ "$AZURE_PROJECT_PREFIX" =~ ^[a-z][a-z0-9]{2,9}$ ]] || { echo 'Invalid project prefix' >&2; exit 2; }
[[ "$AZURE_RESOURCE_GROUP" == "rg-pii-guard-${AZURE_ENVIRONMENT}" ]] || { echo 'Refusing non-dedicated resource group' >&2; exit 2; }
if [[ "$AZURE_ENVIRONMENT" == dev && "$mode" != disable ]]; then
  [[ "${AZURE_DEV_NETWORK_APPROVED:-false}" == true ]] || { echo 'Reviewed tailnet-only private network is required for dev' >&2; exit 2; }
  [[ "$mode" != enable && "$mode" != bind-domain ]] || { echo 'Dev uses private stage; public enable/domain binding is forbidden' >&2; exit 2; }
fi
technical_stage=false
if [[ "$mode" == technical-stage ]]; then
  technical_stage=true
  [[ "$AZURE_ENVIRONMENT" == dev && "${HOSTED_PUBLIC_ORIGIN:-}" == https://guard-dev.watt-mind.com ]] || { echo 'Technical stage requires the exact private dev environment and origin' >&2; exit 2; }
  [[ "${AZURE_TECHNICAL_STAGE_APPROVED:-false}" == true ]] || { echo 'Explicit operator technical-stage approval is required' >&2; exit 2; }
  [[ -z "${GITHUB_ACTIONS:-}" && -z "${CI:-}" ]] || { echo 'Technical stage is unavailable to CI' >&2; exit 2; }
  [[ "${HOSTED_SPONSORED_MICRODOLLARS:-0}" == 0 && -z "${HOSTED_ALLOCATION_ID:-}" && -z "${HOSTED_ALLOCATION_EXPIRES_AT:-}" ]] || { echo 'Technical stage requires zero sponsorship and no allocation pins' >&2; exit 2; }
  : "${HOSTED_TECHNICAL_STAGE_EVIDENCE:?Provide image-bound private synthetic verification evidence}"
  python3 - "$HOSTED_TECHNICAL_STAGE_EVIDENCE" "${HOSTED_IMAGE:-}" <<'PYTECHNICAL'
import json, sys
with open(sys.argv[1]) as stream: evidence = json.load(stream)
required = {'network_reviewed', 'tailnet_acl', 'proxy_tls', 'synthetic_only'}
if (not isinstance(evidence, dict) or set(evidence) != required | {'image', 'purpose'}
    or evidence.get('image') != sys.argv[2]
    or evidence.get('purpose') != 'private-synthetic-verification'
    or not all(evidence.get(key) is True for key in required)):
    raise SystemExit('Technical-stage evidence incomplete')
PYTECHNICAL
fi
name_prefix="${AZURE_PROJECT_PREFIX}-${AZURE_ENVIRONMENT}"
app="${name_prefix}-app"
budget_id="/subscriptions/$AZURE_SUBSCRIPTION_ID/resourceGroups/$AZURE_RESOURCE_GROUP/providers/Microsoft.Consumption/budgets/${name_prefix}-budget"
public_attempt=false
rollback_public() {
  code=$?
  trap - ERR
  if [[ "$public_attempt" == true ]]; then
    az containerapp ingress update --name "$app" --resource-group "$AZURE_RESOURCE_GROUP" --type internal --output none || true
    echo 'Enablement failed; attempted internal ingress rollback. Verify before retry.' >&2
  fi
  exit "$code"
}
trap rollback_public ERR
[[ $(az account show --query id --output tsv) == "$AZURE_SUBSCRIPTION_ID" ]] || { echo 'Active Azure subscription differs from explicit target' >&2; exit 2; }
if [[ "$technical_stage" == true ]]; then
  [[ $(az account show --query user.type --output tsv) == user ]] || { echo 'Technical stage requires an interactive operator account' >&2; exit 2; }
fi
params=(--parameters "projectPrefix=$AZURE_PROJECT_PREFIX" "environmentName=$AZURE_ENVIRONMENT" "location=$AZURE_LOCATION")
if [[ "$operator" == true ]]; then
  : "${AZURE_MONTHLY_BUDGET_AMOUNT:?Set owner-approved amount in subscription billing currency}"
  : "${AZURE_ALERT_ACTION_GROUP_ID:?Select an existing Azure Monitor action group}"
  [[ "$AZURE_MONTHLY_BUDGET_AMOUNT" =~ ^[1-9][0-9]{0,5}$ ]] || { echo 'Invalid monthly budget amount' >&2; exit 2; }
  groups=$(python3 -c 'import json,os; print(json.dumps([os.environ["AZURE_ALERT_ACTION_GROUP_ID"]]))')
  provisioner=${AZURE_SECRET_PROVISIONER_OBJECT_ID:-$(az ad signed-in-user show --query id --output tsv)}
  [[ "$provisioner" =~ ^[a-fA-F0-9-]{36}$ ]] || { echo 'Set the provisioning principal object ID' >&2; exit 2; }
  [[ $(az monitor action-group show --ids "$AZURE_ALERT_ACTION_GROUP_ID" --query enabled --output tsv) == true ]] || { echo 'Existing action group must be enabled' >&2; exit 2; }
  params+=(--parameters "monthlyBudgetAmount=$AZURE_MONTHLY_BUDGET_AMOUNT" "provisioningPrincipalObjectId=$provisioner")
else
  if [[ "$mode" != disable && "$mode" != bind-domain ]]; then
    amount=$(az resource show --ids "$budget_id" --api-version 2023-11-01 --query properties.amount --output tsv 2>/dev/null) || { echo 'A resource-group budget must exist before app release' >&2; exit 2; }
    python3 - "$amount" <<'PYBUDGET'
from decimal import Decimal, InvalidOperation
import sys
try:
    amount = Decimal(sys.argv[1])
except InvalidOperation:
    raise SystemExit('Existing budget must have a positive whole amount') from None
if not amount.is_finite() or amount < 1 or amount != amount.to_integral_value():
    raise SystemExit('Existing budget must have a positive whole amount')
PYBUDGET
    notifications=$(az resource show --ids "$budget_id" --api-version 2023-11-01 --query properties.notifications --output json)
    groups=$(python3 deploy/azure/budget_alerts.py <<< "$notifications")
  fi
fi
if [[ "$mode" != disable && "$mode" != bind-domain ]]; then
  python3 - "$groups" <<'PYGROUPS'
import json, re, sys
ids = json.loads(sys.argv[1])
pattern = r'/subscriptions/[^/]+/resourceGroups/[^/]+/providers/Microsoft.Insights/actionGroups/[^/]+'
if not isinstance(ids,list) or not ids or not all(isinstance(x,str) and re.fullmatch(pattern,x,re.I) for x in ids):
    raise SystemExit('At least one existing action group is required')
PYGROUPS
  if [[ "$operator" != true ]]; then
    while IFS= read -r group_id; do
      enabled=$(az monitor action-group show --ids "$group_id" --query enabled --output tsv)
      [[ "$enabled" == true ]] || { echo 'Budget action group must remain enabled' >&2; exit 2; }
    done < <(python3 -c 'import json,sys; print("\n".join(json.loads(sys.argv[1])))' "$groups")
  fi
  params+=(--parameters "alertActionGroupIds=$groups")
fi
if [[ $(az group exists --name "$AZURE_RESOURCE_GROUP") == true ]]; then
  [[ $(az group show --name "$AZURE_RESOURCE_GROUP" --query tags.project --output tsv) == pii-guard ]] || { echo 'Existing group has different owner' >&2; exit 2; }
  [[ $(az group show --name "$AZURE_RESOURCE_GROUP" --query tags.environment --output tsv) == "$AZURE_ENVIRONMENT" ]] || { echo 'Existing group environment differs' >&2; exit 2; }
  [[ $(az group show --name "$AZURE_RESOURCE_GROUP" --query location --output tsv) == "$AZURE_LOCATION" ]] || { echo 'Group region differs' >&2; exit 2; }
  if [[ "$operator" == true ]]; then
    start=$(az resource show --ids "$budget_id" --api-version 2023-11-01 --query properties.timePeriod.startDate --output tsv 2>/dev/null || true)
    [[ -z "$start" ]] || params+=(--parameters "budgetStartDate=$start")
  fi
else
  [[ "$mode" == bootstrap ]] || { echo 'Bootstrap the dedicated foundation first' >&2; exit 2; }
  az group create --name "$AZURE_RESOURCE_GROUP" --location "$AZURE_LOCATION" --tags project=pii-guard "environment=$AZURE_ENVIRONMENT" --output none
fi
if [[ "$mode" == disable ]]; then
  if [[ "$AZURE_ENVIRONMENT" == dev ]]; then
    az containerapp ingress disable --name "$app" --resource-group "$AZURE_RESOURCE_GROUP" --output none
  else
    az containerapp ingress update --name "$app" --resource-group "$AZURE_RESOURCE_GROUP" --type internal --output none
  fi
  exit 0
fi
if [[ "$mode" == bind-domain ]]; then
  : "${HOSTED_PUBLIC_ORIGIN:?Set canonical HTTPS origin}"
  hostname=${HOSTED_PUBLIC_ORIGIN#https://}
  [[ "$HOSTED_PUBLIC_ORIGIN" =~ ^https://[a-z0-9.-]+$ ]] || exit 2
  existing=$(az containerapp show --name "$app" --resource-group "$AZURE_RESOURCE_GROUP" --query "properties.configuration.ingress.customDomains[].name" --output tsv)
  if ! printf '%s\n' "$existing" | grep -qxF "$hostname"; then
    az containerapp hostname add --name "$app" --resource-group "$AZURE_RESOURCE_GROUP" --hostname "$hostname" --output none
  fi
  az containerapp hostname bind --name "$app" --resource-group "$AZURE_RESOURCE_GROUP" --hostname "$hostname" --environment "${name_prefix}-env" --validation-method CNAME --output none
  exit 0
fi
if [[ "$mode" == bootstrap-router ]]; then
  [[ "$AZURE_ENVIRONMENT" == dev ]] || { echo 'Router exists only in dev' >&2; exit 2; }
  [[ "${AZURE_ROUTER_DEPLOY_APPROVED:-false}" == true ]] || { echo 'Independent code review and concrete tailnet ACL/credentials required' >&2; exit 2; }
  : "${AZURE_ROUTER_ENROLLMENT_SECRET_URI:?Set versioned dev enrollment reference}"
  : "${AZURE_ROUTER_TLS_SECRET_URI:?Set versioned dev combined PEM reference}"
  : "${AZURE_ROUTER_SSH_PUBLIC_KEY:?Set Azure-required public key; SSH remains disabled}"
  vault_uri=$(az deployment group show --resource-group "$AZURE_RESOURCE_GROUP" --name hosted-foundation --query properties.outputs.vaultUri.value --output tsv)
  for uri in "$AZURE_ROUTER_ENROLLMENT_SECRET_URI" "$AZURE_ROUTER_TLS_SECRET_URI"; do
    [[ "$uri" == "${vault_uri}secrets/"* && "$uri" =~ /secrets/[a-zA-Z0-9-]+/[a-f0-9]{32}$ ]] || { echo 'Router references must be versioned secrets in dev vault' >&2; exit 2; }
  done
  params+=(--parameters deployDevRouter=true "routerEnrollmentSecretUri=$AZURE_ROUTER_ENROLLMENT_SECRET_URI" "routerTlsSecretUri=$AZURE_ROUTER_TLS_SECRET_URI" "routerAdminSshPublicKey=$AZURE_ROUTER_SSH_PUBLIC_KEY" "routerVmSize=${AZURE_ROUTER_VM_SIZE:-Standard_B1s}")
fi
if [[ "$operator" != true ]]; then
  : "${HOSTED_IMAGE:?Set immutable registry image@sha256 digest}"
  : "${HOSTED_PUBLIC_ORIGIN:?Set canonical HTTPS origin}"
  : "${GOOGLE_CLIENT_ID:?Set environment-specific Google client id}"
  : "${META_KEY_SECRET_URI:?Set versioned Meta reference}"
  : "${TENANT_KEY_SECRET_URI:?Set versioned tenant key reference}"
  : "${GOOGLE_SECRET_URI:?Set versioned Google reference}"
  : "${METRICS_TOKEN_SECRET_URI:?Set versioned metrics scrape token reference}"
  [[ "$HOSTED_IMAGE" =~ ^[a-z0-9]+\.azurecr\.io/pii-guard@sha256:[a-f0-9]{64}$ && "$HOSTED_PUBLIC_ORIGIN" =~ ^https://[a-z0-9.-]+$ ]] || { echo 'Canonical HTTPS origin and immutable ACR digest required' >&2; exit 2; }
  vault_uri=$(az deployment group show --resource-group "$AZURE_RESOURCE_GROUP" --name hosted-foundation --query properties.outputs.vaultUri.value --output tsv)
  for uri in "$META_KEY_SECRET_URI" "$TENANT_KEY_SECRET_URI" "$GOOGLE_SECRET_URI" "$METRICS_TOKEN_SECRET_URI"; do
    [[ "$uri" == "${vault_uri}secrets/"* && "$uri" =~ /secrets/[a-zA-Z0-9-]+/[a-f0-9]{32}$ ]] || { echo 'Use versioned secrets from this foundation vault' >&2; exit 2; }
  done
  registry=$(az deployment group show --resource-group "$AZURE_RESOURCE_GROUP" --name hosted-foundation --query properties.outputs.registryServer.value --output tsv)
  ledger=$(az deployment group show --resource-group "$AZURE_RESOURCE_GROUP" --name hosted-foundation --query properties.outputs.ledgerAccountUrl.value --output tsv)
  [[ "$HOSTED_IMAGE" == "$registry/"* ]] || { echo 'Image must come from this environment registry' >&2; exit 2; }
  [[ "$ledger" =~ ^https://[a-z0-9]+\.blob\.core\.windows\.net$ ]] || { echo 'Operator must provision durable identity-only ledger first' >&2; exit 2; }
  projects=$(az deployment group show --resource-group "$AZURE_RESOURCE_GROUP" --name hosted-foundation --query properties.outputs.projectAccountUrl.value --output tsv)
  [[ "$projects" == "$ledger" ]] || { echo 'Operator must provision project configuration in the reviewed durable account first' >&2; exit 2; }
  bindings_mode=$mode
  [[ "$technical_stage" != true ]] || bindings_mode=stage
  domains=$(python3 deploy/azure/app_bindings.py "$app" "$AZURE_RESOURCE_GROUP" "$bindings_mode")
  private=false
  if [[ "$AZURE_ENVIRONMENT" == dev ]]; then
    [[ "$HOSTED_PUBLIC_ORIGIN" == https://guard-dev.watt-mind.com ]] || { echo 'Dev requires its exact private origin' >&2; exit 2; }
    network=$(az containerapp env show --name "${name_prefix}-env" --resource-group "$AZURE_RESOURCE_GROUP" --query '{internal:properties.vnetConfiguration.internal,public:properties.publicNetworkAccess}' --output json)
    python3 - "$network" <<'PYPRIVATE'
import json, sys
n=json.loads(sys.argv[1])
if n.get('internal') is not True or n.get('public') != 'Disabled':
    raise SystemExit('Dev requires actual internal environment with public network disabled')
PYPRIVATE
    [[ $(az vm show --name "${name_prefix}-router" --resource-group "$AZURE_RESOURCE_GROUP" --query provisioningState --output tsv) == Succeeded ]] || { echo 'Dedicated reviewed dev router is required' >&2; exit 2; }
    private=true
  fi
  sponsored=${HOSTED_SPONSORED_MICRODOLLARS:-0}
  [[ "$sponsored" =~ ^[0-9]+$ && ${#sponsored} -le 8 ]] || { echo 'Invalid cumulative allowance ceiling' >&2; exit 2; }
  # Per-environment cap (LAB-1508): prod USD 50 (owner, 2026-10-29), dev stays USD 10.
  if [[ "$AZURE_ENVIRONMENT" == prod ]]; then ceiling=50000000 ceiling_usd=50; else ceiling=10000000 ceiling_usd=10; fi
  ((10#$sponsored <= ceiling)) || { echo "Invalid cumulative allowance ceiling (maximum USD $ceiling_usd for $AZURE_ENVIRONMENT)" >&2; exit 2; }
  if [[ "$technical_stage" != true ]] && { [[ "$mode" == enable || "$AZURE_ENVIRONMENT" == dev ]] || ((sponsored > 0)); }; then
    : "${HOSTED_RELEASE_EVIDENCE:?Provide reviewed image-bound release evidence}"
    python3 - "$HOSTED_RELEASE_EVIDENCE" "$HOSTED_IMAGE" "$mode" "$sponsored" "$AZURE_ENVIRONMENT" <<'PYEVIDENCE'
import datetime,json,re,sys
with open(sys.argv[1]) as stream: e=json.load(stream)
if not isinstance(e,dict): raise SystemExit('Release evidence incomplete')
required=['lab_1372_done']
if sys.argv[3]=='enable': required += ['isolation','csrf','identity_header_spoofing','quotas_restart','ssrf','synthetic_roundtrip','streaming','privacy_review']
if sys.argv[5]=='dev': required += ['private_dev_reviewed','tailnet_acl','proxy_tls','proxy_headers']
if e.get('image')!=sys.argv[2] or not all(e.get(k) is True for k in required): raise SystemExit('Release evidence incomplete')
# A positive allocation needs written Meta authorization OR the owner's recorded risk
# acceptance (LAB-1389). The waiver is not authorization and is never read as one.
waiver=e.get('meta_proxy_owner_risk_accepted')
if waiver is not None:
    date=waiver.get('date') if isinstance(waiver,dict) else None
    try: day=datetime.date.fromisoformat(date) if isinstance(date,str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}',date) else None
    except ValueError: day=None
    if (not isinstance(waiver,dict) or set(waiver)!={'by','ref','date','scope'} or waiver['by']!='owner'
            or waiver['ref']!='LAB-1389' or waiver['scope']!='hackathon-demo'
            or day is None or day>datetime.datetime.now(datetime.timezone.utc).date()):
        raise SystemExit('Malformed owner risk acceptance')
if int(sys.argv[4])>0:
    if e.get('meta_proxy_authorized') is True: pass
    elif waiver is not None:
        print('Positive allocation admitted under owner risk acceptance LAB-1389; this is not Meta authorization.',file=sys.stderr)
    else: raise SystemExit('Release evidence incomplete: positive allocation needs meta_proxy_authorized or meta_proxy_owner_risk_accepted')
PYEVIDENCE
  fi
  if ((sponsored > 0)); then
    : "${HOSTED_ALLOCATION_ID:?Reuse approved allocation id; never mint one on release}"
    : "${HOSTED_ALLOCATION_EXPIRES_AT:?Reuse approved expiry; never extend it on release}"
    [[ "$HOSTED_ALLOCATION_ID" =~ ^[a-zA-Z0-9_-]{8,128}$ && "$HOSTED_ALLOCATION_EXPIRES_AT" =~ ^[0-9]{10}$ ]] || exit 2
    ((HOSTED_ALLOCATION_EXPIRES_AT > $(date +%s))) || { echo 'Approved allocation expired' >&2; exit 2; }
    params+=(--parameters "sponsoredMicrodollars=$sponsored" "allocationId=$HOSTED_ALLOCATION_ID" "allocationExpiresAt=$HOSTED_ALLOCATION_EXPIRES_AT")
  fi
  public=false
  preserve_external=false
  if [[ "$mode" == enable ]]; then
    [[ $(az rest --method get --url "https://management.azure.com/subscriptions/$AZURE_SUBSCRIPTION_ID/resourceGroups/$AZURE_RESOURCE_GROUP/providers/Microsoft.App/containerApps/$app/authConfigs/current?api-version=2025-01-01" --query properties.platform.enabled --output tsv) == true ]] || { echo 'Stage Easy Auth first' >&2; exit 2; }
    public=true
  elif [[ "$AZURE_ENVIRONMENT" == prod ]]; then
    # LAB-1541: a stage must not close a live public app. Read its current ingress (read-only)
    # and keep it; only enable may open ingress. Only an explicit not-found means a new app.
    preserve_external=$(python3 - "$app" "$AZURE_RESOURCE_GROUP" <<'PYINGRESS'
import json, re, subprocess, sys
r = subprocess.run(['az', 'containerapp', 'show', '--name', sys.argv[1], '--resource-group', sys.argv[2],
                    '--query', 'properties.configuration.ingress.external', '--output', 'json'],
                   capture_output=True, text=True, check=False)
if r.returncode:
    if re.search(r'^ERROR:\s+\((ResourceNotFound|ContainerAppNotFound)\)', r.stderr, re.M):
        print('false'); raise SystemExit(0)
    raise SystemExit('Current app ingress is unreadable; release refused')
try:
    value = json.loads(r.stdout) if r.stdout.strip() else None
except ValueError:
    raise SystemExit('Current app ingress is invalid; release refused') from None
if value not in (True, False, None):
    raise SystemExit('Current app ingress is invalid; release refused')
print('true' if value is True else 'false')
PYINGRESS
)
  fi
  params+=(--parameters "privateDevReviewed=$private" "publicEnabled=$public" "preserveExternalIngress=$preserve_external" "image=$HOSTED_IMAGE" "publicOrigin=$HOSTED_PUBLIC_ORIGIN" "googleClientId=$GOOGLE_CLIENT_ID" "metaKeySecretUri=$META_KEY_SECRET_URI" "tenantKeySecretUri=$TENANT_KEY_SECRET_URI" "googleSecretUri=$GOOGLE_SECRET_URI" "metricsTokenSecretUri=$METRICS_TOKEN_SECRET_URI" "ledgerAccountUrl=$ledger" "projectAccountUrl=$projects" "customDomains=$domains" "clientIpSource=${HOSTED_CLIENT_IP_SOURCE:-off}")
fi
name=hosted-release
[[ "$operator" != true ]] || name=hosted-foundation
az deployment group validate --resource-group "$AZURE_RESOURCE_GROUP" --template-file "$template" "${params[@]}" --output none
[[ "$mode" != enable ]] || public_attempt=true
az deployment group create --resource-group "$AZURE_RESOURCE_GROUP" --name "$name" --template-file "$template" "${params[@]}" --output none
if [[ "$operator" != true ]]; then
  ready=false
  for ((attempt=0;attempt<60;attempt++)); do
    latest=$(az containerapp show --name "$app" --resource-group "$AZURE_RESOURCE_GROUP" --query properties.latestRevisionName --output tsv)
    admitted=$(az containerapp show --name "$app" --resource-group "$AZURE_RESOURCE_GROUP" --query properties.latestReadyRevisionName --output tsv)
    if [[ -n "$latest" && "$latest" == "$admitted" ]]; then ready=true;break;fi
    sleep 10
  done
  if [[ "$ready" != true ]]; then
    if [[ "$mode" == enable ]]; then az containerapp ingress update --name "$app" --resource-group "$AZURE_RESOURCE_GROUP" --type internal --output none;fi
    echo 'App revision did not become ready; keep ingress restricted' >&2
    exit 1
  fi
  if [[ "$mode" == enable || "$AZURE_ENVIRONMENT" == dev ]]; then
    python3 deploy/azure/smoke.py "$HOSTED_PUBLIC_ORIGIN"
  fi
fi
echo "Completed $mode using $template; no ledger was created, funded or reset by app release."
if [[ "$technical_stage" == true ]]; then
  echo 'Private synthetic technical stage completed with zero sponsorship; full live acceptance remains pending. Normal stage/enable evidence is still required.'
fi
