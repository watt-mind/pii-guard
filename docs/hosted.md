# Hosted PII Guard: deployment and privacy

The hosted image and Azure templates are opt-in. Their presence does **not** mean a public
service has passed review. Start with internal ingress and zero sponsored budget. Read
[ADR 0011](decisions/0011-hosted-saas.md), [contracts](contracts.md) and the
[privacy model](privacy-model.md) before enabling a deployment.

## What each mode processes

| Mode | Original input and detector | Downstream generation | Access |
|---|---|---|---|
| Anonymous walkthrough | Curated server-owned HU/EN synthetic sample; local rules and CPU NER | Masked sample to sponsored Meta, only when budget permits | Public; sample IDs only |
| Signed-in editable text | Azure hosted service receives original text; local rules and CPU NER | Masked text to configured sponsored Meta or approved BYOK destination | Google identity or owner API key; owner-scoped vault |
| BYOK | The service temporarily receives the provider key and configured endpoint | Masked input, key sent only to that approved public HTTPS destination | Signed-in owner; session-only profile |
| Self-hosted | Original input stays in the operator's chosen guard/detector infrastructure | Masked input to the operator's provider | The operator controls access and retention |

Hosted images/uploads and remote LLM detection are outside the initial scope. A remote detector
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

## Retention, deletion and keys

This initial deployment uses process memory for originals during processing, reversible
mappings, temporary provider credentials, API-key records and visitor/user counters. It does
not promise persistence across redeployments, worker failures or restarts. Do not describe
"session-only" as meaning a browser reload erases server memory. Use the implemented owner
session/profile/key deletion and expiry controls documented in [contracts](contracts.md);
closing a tab alone is not a deletion request. Expiry/removal makes records unavailable to the
application but does not prove physical memory erasure. Raw originals can remain in language
runtime caches after logical vault deletion (LAB-1364); do not promise immediate secure erasure.
No application database, mapping backup or content archive is provisioned here. Azure platform
and provider retention are separate; their current terms must be reviewed for the actual account.

The Key Vault holds versioned sponsored credentials, the runtime tenant key and Google OAuth
client secret. The runtime identity has Secrets User access only within this dedicated vault.
These durable credentials remain until an operator rotates/deletes them. Key Vault soft delete
is seven days and purge protection is enabled; that is a secret-recovery policy, **not** prompt
retention. Tenant-key rotation invalidates old pseudonyms; deploy with a new secret version and
expect all ephemeral sessions to be lost. Delete/revoke BYOK profiles and user API keys through
the owner controls, and revoke the original provider credential at its provider if compromised.
Google's Easy Auth cookie is configured for one hour; it is not a mapping TTL. The auth token
store is disabled. Application cookies/CSRF and profile expiry follow the backend contract.

The backend's current default application expiries are:

| Record | Expiry and removal |
|---|---|
| Owner runtime | One hour idle; periodic cleanup every 30 seconds, active requests pinned |
| Guest owner cookie | Fixed one hour |
| Vault session | Sliding one hour |
| BYOK connection | Fixed one hour from creation; five per owner, 256 globally |
| User API key | Fixed 24 hours; five per owner, 1,000 globally; process loss can revoke earlier |

API keys are stored as verifiers, not recoverable raw keys. Deleting a connection/session/key
prevents subsequent lookup; a request that already selected it may finish. Runtime cleanup
closes the owner's vault and clears provider connections. These are application defaults,
not a guarantee that sensitive memory is physically erased on expiry. Review changes to these
limits together with the backend contract and public notice.

The Azure Files share contains only allocation claim markers (allocation identifiers, never
prompts, mappings or keys). Retain markers while an allocation could be reused and preserve the
share during deployment/rollback. No automatic marker deletion or backup policy is configured.
Storage account keys used by the platform SMB mount stay in ARM's secret handling; they never
appear in source, CLI parameters or template outputs. Limit access to environment configuration
and storage administration accordingly.

Content-bearing traffic logging is off, public metrics are off and uvicorn request access logs
are off. The template disables Log Analytics app-console export. Azure platform metrics and
control-plane activity still exist under Azure retention policies; they contain resource usage
and operation metadata, not application bodies by design. Never enable request-body tracing,
identity-header dumps, `az --debug`, shell tracing or exception dumps to investigate real inputs.

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
startup characteristics and is not subject to the self-hosted image's 375 MB OCR image budget.

| Setting | Hosted deployment |
|---|---|
| `PII_GUARD_HOSTED` | `true`; backend support is mandatory |
| `PII_GUARD_HOSTED_SINGLE_PROCESS` | `true`; exactly one worker and one replica |
| `PII_GUARD_HOSTED_PUBLIC_ORIGIN` | Canonical HTTPS origin, no trailing slash |
| `PII_GUARD_HOSTED_TRUST_EASY_AUTH` | `true` only behind the platform's trusted ingress |
| `PII_GUARD_TENANT_KEY` | Versioned Key Vault reference; random 32-byte hex key |
| `PII_GUARD_UPSTREAM_API_KEY` | Versioned Key Vault reference; sponsored Meta Standard key |
| `PII_GUARD_UPSTREAM_BASE_URL` | `https://api.meta.ai/v1`; server-owned sponsored route |
| `PII_GUARD_HOSTED_MODELS` | `muse-spark-1.3` allowlist |
| `PII_GUARD_NER_MODEL`, `PII_GUARD_DETECTORS` | `/app/models/ner`, `rules,ner`; cannot silently drop NER |
| `PII_GUARD_HOSTED_SPONSORED_MICRODOLLARS` | Default `0`; explicit one-time allocation, max USD 10 |
| `PII_GUARD_HOSTED_SPONSORED_ALLOCATION_ID` | Fresh reviewed ID; reused ID forfeited on restart |
| `PII_GUARD_HOSTED_ALLOCATION_DIRECTORY` | `/app/allocation-ledger`, durable marker-only share |
| `PII_GUARD_HOSTED_ALLOCATION_EXPIRES_AT` | Unix UTC expiry for a positive allocation |
| `PII_GUARD_TRAFFIC_LOG`, `PII_GUARD_METRICS` | `off`, `false` |

## Dedicated Azure deployment

Use an explicit subscription and a **new dedicated** resource group beginning with
`rg-pii-guard-hosted-`. The deployment script refuses shared groups and requires the
`project=pii-guard` ownership tag for updates. The selected public origin is **https://guard.watt-mind.com**, with Google callback
`https://guard.watt-mind.com/.auth/login/google/callback`. The planned dedicated resource group
is `rg-pii-guard-hosted-demo`, region `westeurope`, prefix `piiguarddemo`. These are intended
settings, not evidence that a live deployment exists. Choose an EU region after confirming Container
Apps capacity and model memory needs. Infrastructure provisioning requires permission
to create resources and RBAC assignments. Register Microsoft.App, Microsoft.ContainerRegistry,
Microsoft.ManagedIdentity, Microsoft.KeyVault, Microsoft.Storage and Microsoft.Insights in
the selected subscription first if not already registered.

1. Set `AZURE_SUBSCRIPTION_ID`, `AZURE_RESOURCE_GROUP`, `AZURE_LOCATION` and optionally
   `AZURE_PREFIX` (default `piiguarddemo`). Check the active `az account` matches. Run
   `deploy/azure/deploy.sh validate`, then `deploy/azure/deploy.sh bootstrap`. Bootstrap creates
   only dedicated foundation resources: registry, vault, runtime identity, environment and
   allocation share. Repeating it is incremental; it does not delete omitted app resources.
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
   command history or outputs for secret values. Give the provisioning operator narrowly
   scoped secret-write access separately; the template does not grant it automatically.
4. Set `HOSTED_IMAGE`, `HOSTED_PUBLIC_ORIGIN`, `GOOGLE_CLIENT_ID`, `META_KEY_SECRET_URI`,
   `TENANT_KEY_SECRET_URI`, `GOOGLE_SECRET_URI`. URI variables must refer to **versioned**
   secrets in the dedicated vault. No secret values enter the script. Run
   `deploy/azure/deploy.sh stage`; it validates and deploys internal ingress, Google Easy Auth,
   one replica and one worker, and waits boundedly for the platform's Running status. Wait for
   readiness inside the environment too; Running alone does not prove full application health.
5. Test synthetic requests through the actual ingress. Record the tests in an image-bound,
   externally reviewed evidence JSON (example below), then use `enable`. Do not announce the
   service until Google sign-in and the signed-in/guest mask → Meta → restore streaming flow
   have also passed. Set an optional existing `HOSTED_ALERT_ACTION_GROUP_ID` for alert delivery.
   No notification recipient addresses are committed.

Before `enable`, point the public `guard` CNAME at `<appName>.<environmentDomain>` with DNS-only
resolution (no proxy during certificate validation), and create TXT `asuid.guard` from the app's
`properties.customDomainVerificationId` after staging. These are public domain-verification
records, not credentials. The enable script adds the hostname, requests/binds a platform-managed
certificate using CNAME validation, and only then runs the canonical HTTPS smoke. Certificate
issuance may take time; a failure attempts to restore internal ingress. Verify DNS propagation,
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

## Release evidence and sponsored allocation

The script does not generate successful evidence. The reviewer supplies an uncommitted JSON
file bound to the final immutable image, with true values only for checks actually performed:

```json
{
  "image": "REGISTRY.azurecr.io/pii-guard@sha256:REVIEWED_DIGEST",
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

Sponsored budget remains zero unless the operator supplies `HOSTED_SPONSORED_MICRODOLLARS`,
`HOSTED_ALLOCATION_ID` and `HOSTED_ALLOCATION_EXPIRES_AT`. A positive allocation creates a new
revision/process; do not reuse an ID previously started. Verify atomic marker creation on the
mounted share, including exclusive creation and file/directory fsync support, expiry, reservation bounds, exhausted-budget refusal and restart forfeiture
using synthetic traffic before funding public use. Never delete a claim marker to replenish
credit. Reconcile actual upstream usage and all outstanding reservations before issuing fresh
credit; assume the full old allocation spent if uncertain. Changing an allocation ID repeatedly
is additional spending, not a monthly ceiling. The operator controls cumulative allocations.

A single warm 2-vCPU/4-GiB replica avoids model cold starts but incurs ongoing Azure charges.
ACR Basic, Key Vault, Azure Files, networking and alerting cost extra. The USD 10 limit is an
application sponsored allocation ceiling, not an Azure hard cap or a verified price estimate.
Before launch configure an Azure Cost Management budget for this resource group with owner
alerts at 50/80/100% of a reviewed monthly amount. Azure budgets alert; they do not stop billing.
Review daily and disable external ingress/stop the dedicated app when the demo ends. Preserve
claim markers and follow Key Vault recovery obligations when cleaning up resources.

## Observability, refusal and rollback

`/healthz` reports liveness/model state; `/readyz` must refuse until the required hosted NER
stack is ready. Platform startup/readiness probes allow up to ten minutes for loading. The
image also checks `ner=ready` in its Docker healthcheck. No image/OCR capability is advertised.
The template creates content-free alerts for replica loss, restarts, CPU saturation and memory
pressure; attach a monitored action group before relying on delivery. In Azure Monitor inspect
`Requests` grouped by status category for 4xx/429 refusal and 5xx availability, not body or
header logs. Alert delivery, 429 refusal thresholds, allocation exhaustion and provider spend
reconciliation require operational validation; this template does not invent a provider billing
feed or an automatic infrastructure spending cutoff.

A restart invalidates ephemeral state and forfeits a previously claimed sponsored allocation.
Tell users to create fresh sessions/profiles/API keys; do not claim automatic recovery. Keep
`minReplicas=maxReplicas=1` and the single-worker entrypoint until LAB-1376 is implemented.
Container Apps revision transitions can briefly overlap workers; the allocation claim makes a
new worker refuse reused credit, and no mutable owner state is shared. Prefer disabling public
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
