# Hosted PII Guard: deployment and privacy

The hosted image and Azure templates are opt-in. Their presence does **not** mean a public
service has passed review. Start with internal ingress and zero sponsored budget. Read
[ADR 0011](decisions/0011-hosted-saas.md), [ADR 0012](decisions/0012-hosted-projects-and-endpoint-configuration.md),
[contracts](contracts.md) and the [privacy model](privacy-model.md) before enabling a deployment.

## What each mode processes

| Mode | Original input and detector | Downstream generation | Access |
|---|---|---|---|
| Anonymous walkthrough | Curated server-owned HU/EN synthetic sample; local rules and CPU NER | Masked sample to sponsored Meta, only when budget permits | Public; sample IDs only |
| Signed-in editable text | Azure hosted service receives original text; local rules and CPU NER | Masked text to configured sponsored Meta or approved BYOK destination | Google identity or owner API key; owner-scoped vault |
| Signed-in images | Azure hosted service receives the original image in memory; local Tesseract OCR, on-device face/ID-photo detector, local rules and CPU NER; never stored | None: the masked image returns to the owner | Google identity only (no API keys, no guests); owner-scoped vault |
| BYOK | The service receives the provider key and configured endpoint | Masked input, key sent only to that approved public HTTPS destination | Signed-in owner; the endpoint credential is encrypted in project configuration (see [projects](projects.md)) |
| Self-hosted | Original input stays in the operator's chosen guard/detector infrastructure | Masked input to the operator's provider | The operator controls access and retention |

Hosted images are processed on the replica only ([ADR 0014](decisions/0014-hosted-local-images.md)):
no SAM, no remote detector, no image spend. The on-device segmenter cannot find signatures or
stamps, so the deployment sets `SIGNATURE=keep` (they stay visible) or every image is refused.
Document uploads (PDF/DOCX) and remote LLM detection are outside the initial scope. A remote detector
is different from downstream generation: it receives originals. Never enable one without an
explicitly approved trust boundary and terms review. See [models](models.md) and LAB-1139 for
remote detector terms still requiring confirmation.

Azure operators can access process memory and administer the deployment. Google receives
sign-in information. Azure receives original text in the hosted process. The downstream model
normally receives masked text, but **detection can miss values and context can identify people**.
Pseudonymization is not anonymization. Do not submit highly sensitive data or content you lack
authority to process. Respect provider terms, quotas and endpoint restrictions; do not attempt
to bypass them. The project maintainer must review the final public privacy and acceptable-use
notice before editable inputs are enabled. Put that notice beside the editable text/BYOK form,
with an explicit acknowledgement before the first submission, not only on the landing page.

## Sponsored provider launch gate

Technical readiness does not authorize sponsored Meta access. The
[Meta Model API terms](https://dev.meta.ai/legal/terms-of-service), section 10.1(i), require
written Meta authorization for providing access through an API gateway, proxy or similar
offering. Keep sponsorship at zero until the maintainer records the applicable written
authorization. This also applies when testing a hosted proxy with synthetic inputs.

Standard Services exclude training on submitted content (section 5.1), but allow need-based
retention (section 4.4). No fixed deletion period or EU-only processing is established here.
An Azure EU region does not establish downstream residency. Confirm actual Standard routing,
applicable processing terms and public disclosure before activating paid calls.

## Retention, deletion and keys

This deployment keeps originals during processing, reversible mappings, request/session state,
masked traffic events, counters and account-level temporary profiles in bounded process memory.
Those values are lost on process/runtime loss; closing a browser tab alone is not a deletion
request. Use implemented owner session/profile/key deletion and expiry controls documented in
[contracts](contracts.md). Expiry/removal makes records unavailable to the application but does
not prove physical memory erasure. Raw originals can remain in language runtime caches after
logical vault deletion (LAB-1364); do not promise immediate secure erasure.
No mapping backup or content archive is provisioned. Encrypted project configuration has a
separate durable store described below and in [projects](projects.md). Azure platform and
provider retention are separate; review the current terms for the actual account.

The Key Vault holds versioned sponsored credentials, the runtime tenant key and Google OAuth
client secret. The runtime identity has Secrets User access only within this dedicated vault.
These durable credentials remain until an operator rotates/deletes them. Key Vault soft delete
is seven days and purge protection is enabled; that is a secret-recovery policy, **not** prompt
retention. Tenant-key rotation invalidates old pseudonyms and makes existing encrypted project
configuration unreadable. It requires a separately reviewed project-key migration; changing the
secret version alone is not a safe rotation procedure. Ephemeral sessions are also lost.
Delete temporary BYOK connections, project endpoints and their endpoint keys, and account API
keys through the owner controls. Revoke the original provider credential at its provider if
compromised.
Google's Easy Auth cookie is configured for one hour; it is not a mapping TTL. The auth token
store is disabled. Application cookies/CSRF and profile expiry follow the backend contract.

The backend's current default application expiries are:

| Record | Expiry and removal |
|---|---|
| Owner runtime | One hour idle; periodic cleanup every 30 seconds, active requests pinned |
| Guest owner cookie | Fixed one hour |
| Vault session | Sliding one hour |
| BYOK connection | Fixed one hour from creation; five per owner, 256 globally |
| Project endpoint configuration and endpoint-key verifiers | Durable encrypted configuration Blob until explicit owner deletion/revocation; raw endpoint keys are shown once and not stored |
| Masked traffic log | Last 50 events per owner; freed on owner purge or process restart |
| Spend ledger | Durable finite authority and total/daily counters in isolated Blob; no prompt/mapping/key content |
| User API key | Fixed 24 hours; five per owner, 1,000 globally; process loss can revoke earlier |

Account and endpoint guard keys are stored as verifiers, not recoverable raw keys. Deleting a
connection/session/key prevents subsequent lookup; disabling an endpoint blocks its keys from
new admission. A request that already selected a connection or endpoint may finish. Runtime cleanup
closes the owner's vault and clears provider connections. These are application defaults,
not a guarantee that sensitive memory is physically erased on expiry. Review changes to these
limits together with the backend contract and public notice.

The legacy Azure Files share contains only allocation claim markers (allocation identifiers, never
prompts, mappings or keys). Retain markers while an allocation could be reused and preserve the
share during deployment/rollback. No automatic marker deletion or backup policy is configured.
Storage account keys used by the platform SMB mount stay in ARM's secret handling; they never
appear in source, CLI parameters or template outputs. Limit access to environment configuration
and storage administration accordingly.

The global traffic log, public metrics and uvicorn request access log are off. Each hosted
owner nevertheless has an in-memory **masked** traffic log of its last 50 events, readable
only through that owner's `/v1/traffic` routes. It contains the masked upstream request and
upstream response, not an intentionally captured original/restored pair. Masked content can
still contain missed personal data or identifying context. It is freed on owner purge or
process restart and is not exported as console logs. The template disables Log Analytics app-console export. Azure platform metrics and
control-plane activity still exist under Azure retention policies; they contain resource usage
and operation metadata, not application bodies by design. Never enable request-body tracing,
identity-header dumps, `az --debug`, shell tracing or exception dumps to investigate real inputs.

Project configuration has a separate durable boundary in the combined project-store release.
The private `project-configuration/<environment>.projects.v1.enc` Blob snapshot stores project
ownership, policy versions, endpoint settings, encrypted provider credentials and endpoint-key
verifier/revocation records. It uses the environment's stable tenant key and runtime managed
identity; it contains no request text, mappings, owner sessions or traffic archive. An operator
must explicitly initialize it once; startup and app releases never create missing state.
Project configuration and revocations survive replacement revisions; temporary connection
profiles and owner-session API keys retain their existing ephemeral lifecycle. Never reset or
roll back the snapshot to roll back app code. See [Azure setup and initialization](private-dev.md#durable-encrypted-project-configuration).

## Build and configuration

The self-hosted `Dockerfile`, Compose stack and wheel packaging remain separate. The hosted
build reuses the bundled UI mechanism and the existing CPU `ner` extra/pinned checkpoint
verifier. It builds the UI with `VITE_PII_GUARD_HOSTED=true` and `VITE_PII_GUARD_MODE=api`, bundles
the NER model under `/app/models/ner`, performs a warm-up forward pass, then runs offline. A
missing/broken configured model stops startup. No OCR dependency is installed; images must be
refused by the hosted backend, not forwarded for partial masking.

```bash
docker build --platform linux/amd64 -f Dockerfile.hosted -t pii-guard-hosted:review .
az bicep build --file deploy/azure/main.bicep
bash -n deploy/azure/deploy.sh
python3 deploy/azure/test_deploy.py
scripts/ci/lychee.sh --offline
```

Use an immutable image digest for deployment. Azure Container Apps uses Linux amd64; building
on an ARM workstation may use emulation and take longer. The NER image has its own size and
startup characteristics and is not subject to the self-hosted image's 550 MB OCR/vision image budget.

| Setting | Hosted deployment |
|---|---|
| `PII_GUARD_HOSTED` | `true`; backend support is mandatory |
| `PII_GUARD_HOSTED_SINGLE_PROCESS` | `true`; one worker per replica, zero to one replicas |
| `PII_GUARD_HOSTED_PUBLIC_ORIGIN` | Canonical HTTPS origin, no trailing slash |
| `PII_GUARD_HOSTED_TRUST_EASY_AUTH` | `true` only behind the platform's trusted ingress |
| `PII_GUARD_PROJECT_STATE_PATH` | Image default `/var/lib/pii-guard/projects/state.sqlite3`; unused when the Azure templates select `azure_blob` |
| `PII_GUARD_TENANT_KEY` | Versioned Key Vault reference; random 32-byte hex key |
| `PII_GUARD_UPSTREAM_API_KEY` | Versioned Key Vault reference; sponsored Meta Standard key |
| `PII_GUARD_UPSTREAM_BASE_URL` | `https://api.meta.ai/v1`; server-owned sponsored route |
| `PII_GUARD_HOSTED_MODELS` | `muse-spark-1.3` allowlist |
| `PII_GUARD_NER_MODEL`, `PII_GUARD_DETECTORS` | `/app/models/ner`, `rules,ner`; cannot silently drop NER |
| `PII_GUARD_HOSTED_SPONSORED_MICRODOLLARS` | Default `0`; approved cumulative ceiling, max USD 10 |
| `PII_GUARD_HOSTED_SPONSORED_ALLOCATION_ID` | Exact operator-approved ID; reused across Blob-backed restarts |
| `PII_GUARD_HOSTED_SPEND_STORE` | `azure_blob`; requires LAB-1398 and the image SDK extra |
| `PII_GUARD_HOSTED_SPEND_ACCOUNT_URL` | Environment-specific identity-only Blob account |
| `PII_GUARD_HOSTED_SPEND_CONTAINER` | `sponsored-allowance`; fixed `<environment>.json` object |
| `PII_GUARD_HOSTED_SPEND_ENVIRONMENT` | `dev` or `prod`, matching the authority object |
| `PII_GUARD_HOSTED_PROJECT_STORE` | `azure_blob`; encrypted durable project configuration |
| `PII_GUARD_HOSTED_PROJECT_ACCOUNT_URL` | Reviewed foundation's identity-only Blob account |
| `PII_GUARD_HOSTED_PROJECT_CONTAINER` | `project-configuration`; fixed `<environment>.projects.v1.enc` snapshot |
| `PII_GUARD_HOSTED_PROJECT_ENVIRONMENT` | `dev` or `prod`; separate account, identity and stable tenant key |
| `PII_GUARD_HOSTED_PROJECT_MANAGED_IDENTITY_CLIENT_ID` | The environment runtime identity's client ID |
| `PII_GUARD_HOSTED_IMAGES` | Default `true`: signed-in image masking; `/readyz` then requires Tesseract and the on-device segmenter |
| `PII_GUARD_SEGMENTER` | `local` (image default); `hybrid`/`sam-api`/`off` refuse startup while hosted images are on |
| `PII_GUARD_POLICY_OVERRIDES` | `SIGNATURE=keep`: the on-device segmenter cannot find signatures; without it images are refused and not offered |
| `PII_GUARD_HOSTED_MAX_IMAGE_BYTES`, `PII_GUARD_HOSTED_IMAGE_MAX_PIXELS` | Defaults 4 MiB decoded and 8 MP, checked before OCR |
| `PII_GUARD_HOSTED_IMAGE_TIMEOUT` | Default 60 s per image; one image job per replica, a busy replica answers `429` |
| `PII_GUARD_HOSTED_USER_IMAGES_PER_DAY`, `PII_GUARD_HOSTED_GLOBAL_IMAGES_PER_DAY` | Defaults 20 and 500, reserved before work, never refunded |
| `PII_GUARD_HOSTED_SPEND_MANAGED_IDENTITY_CLIENT_ID` | Dedicated runtime UAMI client ID |
| `PII_GUARD_HOSTED_ALLOCATION_EXPIRES_AT` | Unix UTC expiry for a positive allocation |
| `PII_GUARD_TRAFFIC_LOG`, `PII_GUARD_METRICS` | `off`, `false` |

## Dedicated Azure deployment

Use an explicit subscription and a **new dedicated** resource group beginning with
`rg-pii-guard-prod` (or `rg-pii-guard-dev`). The deployment script refuses shared groups and requires matching
`project=pii-guard` and `environment` tags for updates. The selected public origin is **https://guard.watt-mind.com**, with Google callback
`https://guard.watt-mind.com/.auth/login/google/callback`. The planned dedicated resource group
is `rg-pii-guard-prod`, region `swedencentral`, project prefix `piiguard`, environment `prod`. Names derive from both, for example
`piiguard-prod-env` and `piiguard-prod-runtime`. Tags are `project=pii-guard`,
`environment=prod`; the resource group itself must also be in Sweden Central. These are intended
settings, not evidence that a live deployment exists. Choose an EU region after confirming Container
Apps capacity and model memory needs. Infrastructure provisioning requires permission
to create resources and RBAC assignments. Register Microsoft.App, Microsoft.ContainerRegistry,
Microsoft.ManagedIdentity, Microsoft.KeyVault, Microsoft.Storage and Microsoft.Insights in
the selected subscription first if not already registered.

1. Set `AZURE_SUBSCRIPTION_ID`, `AZURE_RESOURCE_GROUP`, `AZURE_LOCATION` and optionally
   `AZURE_PROJECT_PREFIX` (default `piiguard`) and `AZURE_ENVIRONMENT` (`prod`, or `dev`). Check the active `az account` matches. Run
   `deploy/azure/deploy.sh validate`, then `deploy/azure/deploy.sh bootstrap`. Bootstrap creates
   dedicated foundation resources: registry, vault, runtime identity, environment, allocation
   share and monthly budget. Set `AZURE_MONTHLY_BUDGET_AMOUNT=25` for the owner-approved **EUR
   25/month** in the selected subscription's billing currency, and
   `AZURE_ALERT_ACTION_GROUP_ID` to the selected existing enabled action group. The script does
   not add recipients or create duplicate action groups. Budget alerts at 50/80/100% do not
   stop billing. Bootstrap grants its current provisioning principal Secrets Officer at this
   vault only; `AZURE_SECRET_PROVISIONER_OBJECT_ID` may supply an explicit principal instead. Repeating it is incremental; it does not delete omitted app resources.
2. Read only non-secret outputs from `hosted-foundation`: `registryServer`, `vaultUri`,
   `environmentDomain`, `appName`. Default public origin is
   `https://<appName>.<environmentDomain>`; keep the canonical public origin
   `https://guard.watt-mind.com` for the selected deployment. Build/tag/push the hosted image to this registry's
   `pii-guard` repository and resolve its digest; the deployment script requires that digest.
   Authenticate the builder with its own scoped registry-push role; runtime has AcrPull only.
3. Register a Google OAuth **web** client for that exact HTTPS origin and callback
   `https://<host>/.auth/login/google/callback`. Use only `openid`, `profile`, `email` scopes.
   Google-first login does not grant access to other Google services. Put its secret, the
   sponsored Meta Standard key and a generated tenant key into this vault via an authorized
   in-memory SDK or secret-management workflow. Never use plaintext shell arguments, files,
   command history or outputs for secret values. Bootstrap grants the selected provisioning principal narrowly scoped Secrets Officer access
   on this vault; the runtime retains Secrets User access. Revoke temporary provisioning
   access when operational policy requires it.
4. Set `HOSTED_IMAGE`, `HOSTED_PUBLIC_ORIGIN`, `GOOGLE_CLIENT_ID`, `META_KEY_SECRET_URI`,
   `TENANT_KEY_SECRET_URI`, `GOOGLE_SECRET_URI`. URI variables must refer to **versioned**
   secrets in the dedicated vault. No secret values enter the script. Run
   `deploy/azure/deploy.sh stage`; it validates and deploys internal ingress, Google Easy Auth,
   zero to one replicas, with one worker per replica, and waits boundedly for the latest revision to be admitted as ready. Verify application
   readiness through ingress too; scale-to-zero is expected after idle periods.
5. Test synthetic requests through the actual ingress. Record the tests in an image-bound,
   externally reviewed evidence JSON (example below), then use `enable`. Do not announce the
   service until Google sign-in and the signed-in/guest mask → Meta → restore streaming flow
   have also passed. Budget notification action groups are preserved on stage/enable; set
   `AZURE_ALERT_ACTION_GROUP_ID` only for an explicitly reviewed override.
   No notification recipient addresses are committed.

Before `enable`, point the public `guard` CNAME at `<appName>.<environmentDomain>` with DNS-only
resolution (no proxy during certificate validation), and create TXT `asuid.guard` from the app's
`properties.customDomainVerificationId` after staging. These are public domain-verification
records, not credentials. Run `deploy/azure/deploy.sh bind-domain` as the operator to add the hostname and request/bind
a platform-managed certificate using CNAME validation. App release preserves that binding and
runs the canonical HTTPS smoke during `enable`. Certificate issuance may take time; a failed
enablement attempts to restore internal ingress. Verify DNS propagation,
certificate subject/expiry and the HTTPS callback before retrying. Keep the canonical origin and
Google callback aligned if the domain changes. The default Azure hostname also passes Easy Auth; never
create a second public service that exposes the container directly. Do not enable raw TCP
ports. Internal network callers must not bypass platform identity-header stripping either;
verify this in the deployed environment before setting the trust flag.

Easy Auth is deliberately `AllowAnonymous` because landing and synthetic guest routes are
public. This is **not** API authorization. Protected routes must reject anonymous callers,
spoofed identity headers, cross-owner sessions/API keys and cross-origin cookie writes. Verify
that the platform discards caller-supplied `X-MS-CLIENT-PRINCIPAL` headers on **all** ingress
hostnames, including anonymous requests. If this cannot be established, keep ingress internal.

## Dev/prod deployment

`develop` targets **dev** and `main` targets **prod**, with the same reviewed image and separate
credentials, identities, state and budgets. The [private dev runbook](private-dev.md) specifies
the dedicated internal ACA environment, always-on Tailscale HTTPS proxy, exact-host DNS,
managed-identity credential bootstrap, OAuth/header boundary, cost and activation checks.
This is source readiness, not a claim that a VM, private callback or dev app has been deployed.
There is no public dev fallback. Real runtime inputs may be processed in the authorized service;
repository fixtures and committed evidence remain synthetic.

`main.bicep` is operator-only foundation; app `stage`/`enable` use `release.bicep`, which never
writes RBAC, budgets, networks or storage and never calls account-key functions. The local
`deploy.sh ci-preflight dev|prod` handshake is required before CI login. CI must not receive
operator foundation/funding privileges. Existing domain bindings are preserved; a failed
binding metadata read refuses release instead of silently clearing the certificate/hostname.
Prod certificate binding is an explicit operator `bind-domain` step, not an app CI privilege.

App releases require the operator-provisioned identity-only Blob ledger. They reuse approved
finite cumulative allowance pins and never mint credit. On restart/scale-zero, LAB-1398 resumes
total/daily accounting under CAS without restoring owner data. The old SMB marker-only store
is legacy compatibility infrastructure; its restart-forfeiture behavior is not the new Blob
store's behavior. Durable accounting does not implement LAB-1376 mapping/session persistence.

## Foundation migration and deletion

The owner approved replacing the old hosted-demo foundation with `rg-pii-guard-prod` in
Sweden Central, including the resource group itself. Deploy the new foundation with no app,
then copy the four latest enabled secrets to the new vault **in memory**. Verify their values
in memory and record new enabled versioned references; never print or persist secret values.
The parent operator performs this migration. Check the old allocation share is empty, or
preserve any claim markers before retiring it.

Delete **only** `rg-pii-guard-hosted-demo` after the new foundation/budget succeed and the
operator explicitly confirms secret migration, metadata verification and replacement of all
old secret references. No deployment script deletes it automatically. The approved retirement
command is `az group delete --name rg-pii-guard-hosted-demo --yes`; do not run it before those
conditions. Do not purge the old vault: its purge-protected soft deletion lasts seven days and
reserves its old name. Report only new resource names in the PR discussion.

Prod Key Vault and the legacy allocation share still use RBAC/credential-protected public network endpoints;
this template does not establish private endpoints or an EU residency guarantee downstream.
Limit operator permissions and keep that boundary visible in deployment review.

## Operator launch checklist

Use the final combined backend/UI/deployment revision for launch. A green check on each
separate PR, a locally built image or a successful foundation deployment is not evidence that
an Azure app revision has been tested. Do not mark image-bound evidence true before its actual
checks. The commands below inspect metadata only; do not add `--debug`, dump container env or
retrieve secret values.

```bash
export AZURE_RESOURCE_GROUP=rg-pii-guard-prod
export AZURE_LOCATION=swedencentral
export AZURE_PROJECT_PREFIX=piiguard
export AZURE_ENVIRONMENT=prod
export HOSTED_PUBLIC_ORIGIN=https://guard.watt-mind.com
az deployment group show --resource-group "$AZURE_RESOURCE_GROUP" --name hosted-foundation \
  --query 'properties.outputs.{registry:registryServer.value,vault:vaultUri.value,domain:environmentDomain.value}' --output json
az acr repository show --name "$AZURE_REGISTRY_NAME" --image "pii-guard@$REVIEWED_DIGEST" \
  --query '{digest:digest,lastUpdateTime:lastUpdateTime}' --output json
az containerapp show --resource-group "$AZURE_RESOURCE_GROUP" --name "${AZURE_PROJECT_PREFIX}-${AZURE_ENVIRONMENT}-app" \
  --query '{image:properties.template.containers[0].image,latest:properties.latestRevisionName,ready:properties.latestReadyRevisionName,external:properties.configuration.ingress.external,fqdn:properties.configuration.ingress.fqdn}' --output json
```

Set `AZURE_REGISTRY_NAME` from the registry output (without `.azurecr.io`) and
`REVIEWED_DIGEST=sha256:<reviewed digest>`. Require the deployed image digest to match the
release evidence and `latest=ready`. No app/image yet means these checks are pending.

- **Identity boundary:** inspect the auth configuration with the focused query below. Verify
  Google enabled, HTTPS required and `AllowAnonymous` intentional. In a separately authorized,
  restricted staging test, send a valid-shaped synthetic `X-MS-CLIENT-PRINCIPAL` with
  `auth_typ=google` and a fictional `sub` to `/v1/account` without a Google cookie: it must stay
  anonymous or be refused. Repeat on the default Azure hostname and custom hostname, and for
  repeated security headers. A localhost test bypasses the platform and cannot establish this
  boundary. Internal ingress alone may not exercise the external Easy Auth path. Before the
  first external test, agree its network restriction and rollback with the release reviewer;
  do not forge successful evidence to get past `enable`.
- **Google audience:** confirm exact callback and actual requested scopes in the browser.
  Google's [audience documentation](https://support.google.com/cloud/answer/15549945) exempts
  sign-in limited to `openid`, profile and email from Testing's usual test-user/7-day limits.
  Do not assume Testing either blocks or proves public access. Test the actual Google flow
  with an authorized account outside the configured tester list; record requested scopes and
  outcome without identity claims or tokens. Additional scopes change the audience requirements.
  Publishing status or OAuth configuration changes require separate authorization.
- **DNS/TLS:** before certificate binding, verify `dig +short CNAME guard.watt-mind.com` points
  to the public app hostname and `dig +short TXT asuid.guard.watt-mind.com` matches the staged
  app verification ID. A missing record leaves certificate issuance pending. After binding,
  verify canonical HTTPS, certificate validity and Google callback; retain the Azure hostname
  in the identity-boundary tests.
- **Key references:** list secret *versions* using the command below; select enabled versioned
  IDs from this vault. Require Google OAuth secret, Meta Standard credential and tenant key
  references to resolve under the runtime managed identity. Existing enabled secret metadata
  does not prove resolution or provider authorization. Never print their values.
- **Durable authority:** require LAB-1398 plus the `hosted-azure` SDK extra in both hosted image
  dependency installations and an offline SDK import smoke. The first image without that
  integration cannot be advertised as resumable sponsored service. With sponsorship zero,
  verify private Blob DNS/MI access and missing-object refusal. After provider authorization,
  use approved synthetic finite authority to prove exact-pin validation, concurrent CAS
  charging, expiry, exhaustion and restart resumption without resetting total/daily charges.
- **Spend and rollback:** require written provider authorization, Standard routing, reviewed
  pricing/reservations and exact approved ID/ceiling/expiry pins before setting positive
  sponsorship. Keep it zero for technical-only releases. Save the previous immutable image
  and secret-version references, exercise `disable`, and require fresh review before public
  rollback. Preserve the ledger; rollback never restores spent credit. Record an owner for
  provider-spend reconciliation and Azure budget alerts.

```bash
az rest --method get --url "https://management.azure.com/subscriptions/$AZURE_SUBSCRIPTION_ID/resourceGroups/$AZURE_RESOURCE_GROUP/providers/Microsoft.App/containerApps/${AZURE_PROJECT_PREFIX}-${AZURE_ENVIRONMENT}-app/authConfigs/current?api-version=2025-01-01" \
  --query 'properties.{enabled:platform.enabled,https:httpSettings.requireHttps,action:globalValidation.unauthenticatedClientAction,google:identityProviders.google.enabled,scopes:identityProviders.google.login.scopes}' --output json
for secret_name in google-oauth-client-secret meta-api-key tenant-key; do
  az keyvault secret list-versions --vault-name "$AZURE_VAULT_NAME" --name "$secret_name" \
    --query '[].{id:id,enabled:attributes.enabled}' --output json
done
az containerapp show --resource-group "$AZURE_RESOURCE_GROUP" --name "${AZURE_PROJECT_PREFIX}-${AZURE_ENVIRONMENT}-app" \
  --query properties.customDomainVerificationId --output tsv
```

Set `AZURE_VAULT_NAME` from the foundation vault URI. Ledger data must be provisioned only
by the approved operator workflow, using managed identity and the reviewed LAB-1398 schema.
Do not test authority by deleting a live object, rewriting old counters or creating a replacement
allocation during app deployment. The [private dev runbook](private-dev.md#finite-authority-cost-and-rollback)
describes the network and permission checks for dev.

## Release evidence and sponsored allocation

The script does not generate successful evidence. **LAB-1372 must be Done before `enable`
or any positive sponsored allocation**, including staging. The reviewer must verify its
actual status; an evidence boolean alone is not proof. Merge order is backend **#159**, UI
**#156**, then deployment **#157**; rebase this source after #159 lands. The reviewer supplies an uncommitted JSON
file bound to the final immutable image, with true values only for checks actually performed:

```json
{
  "image": "REGISTRY.azurecr.io/pii-guard@sha256:REVIEWED_DIGEST",
  "lab_1372_done": true,
  "meta_proxy_authorized": true,
  "isolation": true,
  "csrf": true,
  "identity_header_spoofing": true,
  "quotas_restart": true,
  "ssrf": true,
  "synthetic_roundtrip": true,
  "streaming": true,
  "privacy_review": true
}
```

Set `HOSTED_RELEASE_EVIDENCE` to that path and run `deploy/azure/deploy.sh enable` explicitly. DNS and the custom-domain verification TXT must
exist before this step.
The script checks pre-existing Easy Auth before opening external ingress and runs a public
landing/readiness/anonymous-API-refusal smoke. On failure it restores internal ingress. This
smoke does not replace browser sign-in, provider streaming or privacy review.

Sponsored budget remains zero until written provider authorization and the other launch gates
are recorded, and the operator supplies `HOSTED_SPONSORED_MICRODOLLARS`,
`HOSTED_ALLOCATION_ID` and `HOSTED_ALLOCATION_EXPIRES_AT`. The `meta_proxy_authorized` key is required for positive allocations and may be set only
after the maintainer records written Meta authorization. Releases reuse the operator's exact
existing authority pins. The operator precreates the private object; neither bootstrap nor
app release funds it. Changing the ID or cumulative ceiling must preserve charged total and
current-day charges. Reconcile actual upstream usage and outstanding reservations before
approving additional authority; unknown commits are charged conservatively. Never delete or
restore the object to replenish credit. Legacy marker-only deployments retain their original
restart-forfeiture rules and are not the Blob-backed release path.

The app scales to zero when idle and runs at most one 2-vCPU/4-GiB replica. Each cold start
loads the local NER model before readiness and can delay the first request. Scale-to-zero
discards owner state. The Blob store resumes the same finite total/daily authority; it never
reopens credit automatically.
ACR Basic, Key Vault, Azure Files, networking and alerting cost extra. The USD 10 limit is an
application sponsored allocation ceiling, not an Azure hard cap or a verified price estimate.
Bootstrap creates the owner-approved EUR 25/month resource-group budget with 50/80/100%
notifications routed to the existing selected action group. `stage` and `enable` refuse to run
without that budget and preserve its start date/recipients. Azure budgets alert; they do not
stop billing. The EUR infrastructure budget is separate from USD sponsored allocations.
Review daily and disable external ingress/stop the dedicated app when the demo ends. Preserve
the authority object and any legacy claim markers, and follow Key Vault recovery obligations when cleaning up resources.

## Observability, refusal and rollback

`/healthz` reports liveness/model state; `/readyz` must refuse until the required hosted NER
stack is ready. Platform startup/readiness probes allow up to ten minutes for loading. Container Apps ignores Docker `HEALTHCHECK`; the explicit Bicep startup/readiness/liveness
probes are required and send `Host: localhost`. `PII_GUARD_ALLOWED_HOSTS` adds the canonical
public host and app default Azure host; loopback hosts remain allowed for probes. The image
also checks `ner=ready` in its Docker healthcheck for local Docker verification. No image/OCR capability is advertised.
The template creates content-free alerts for restarts, CPU saturation and memory
pressure; scale-to-zero is expected and does not trigger a replica-loss alarm; attach a monitored action group before relying on delivery. In Azure Monitor inspect
`Requests` grouped by status category for 4xx/429 refusal and 5xx availability, not body or
header logs. Alert delivery, 429 refusal thresholds, allocation exhaustion and provider spend
reconciliation require operational validation; this template does not invent a provider billing
feed or an automatic infrastructure spending cutoff.

A restart invalidates ephemeral owner state. The legacy marker store forfeits claimed credit;
the reviewed Azure Blob store resumes the same durable finite authority without refilling it.
Tell users to create fresh sessions/profiles/API keys; do not claim automatic recovery. Keep
`minReplicas=0`, `maxReplicas=1` and the single-worker entrypoint until LAB-1376 is implemented.
Container Apps revision transitions can briefly overlap workers; Blob conditional writes
serialize spending across them, while no mutable owner state is shared. Prefer disabling public
ingress during updates to avoid sessions straddling revisions.

For an incident, run `deploy/azure/deploy.sh disable` first. This restores internal ingress.
Deploy the previous reviewed immutable image with `stage`, keep sponsorship at zero, verify
readiness and synthetic authorization/streaming again, then review new release evidence before
`enable`. Rollback loses the same ephemeral state as any restart; it must not reset a paid
allocation. Never roll back by deleting the volume, clearing markers or restoring an old
counter snapshot. Rotate compromised credentials in Key Vault/provider accounts, select new
secret-version URIs and deploy; no secret material should enter incident logs.

Official platform references: [Container Apps authentication](https://learn.microsoft.com/en-us/azure/container-apps/authentication),
[auth configuration schema](https://learn.microsoft.com/en-us/azure/templates/microsoft.app/2025-01-01/containerapps/authconfigs),
[Container Apps metrics](https://learn.microsoft.com/en-us/azure/container-apps/metrics),
[secret management](https://learn.microsoft.com/en-us/azure/container-apps/manage-secrets).
