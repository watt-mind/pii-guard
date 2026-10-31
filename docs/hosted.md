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
no SAM, no remote detector, no image spend. Faces and ID photos are found by YuNet and
signatures by the pinned YOLOS-tiny detector, both on the CPU; the owner's project policy decides
what is masked (LAB-1444). Nothing local finds stamps, so a policy that masks `STAMP` is refused.
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

## First run for signed-in owners

Straight after Google sign-in the console calls `POST /v1/account/first-run` (contract in
[contracts](contracts.md)). The server provisions, once per owner, the default project (with its
default policy), one **Default endpoint** and that endpoint's first key, and the console lands
on Connect, "Connect your client": the guard key shown once, copy-paste blocks for Codex, pi,
the OpenAI SDK, cURL and OpenCode with the key and endpoint URL filled in, and a **Send a test
request** button that shows the masked round trip. Muse Code cannot use an endpoint URL yet, so
its tab explains that instead of showing a block.

- **Sponsorship available** (`limits.sponsored_enabled`): the endpoint uses the server-owned
  sponsored Meta route with the first `PII_GUARD_HOSTED_MODELS` model and is ready immediately.
- **Sponsorship unavailable** (the default until the launch gate below is met): the same
  endpoint is marked **Needs a key** and refuses requests with `sponsored_unavailable` before
  any upstream call. The first screen asks for one field, the owner's Meta API key; saving it
  converts the endpoint in place to an own-key Meta endpoint whose credential is encrypted in
  project configuration (ADR 0012). The browser never stores the key. An own-key endpoint never
  falls back to sponsored inference, and the sponsored key is never sent to an owner endpoint.
  If sponsorship is enabled later, endpoints still on the sponsored route become ready without
  any action.

The guard key exists only in that page's memory: after a reload the console offers one-click
**Create a new guard key** rather than showing the old one. Policies and endpoints remain
editable in Projects; nothing about first run is required for owners who configure their own.
Provisioning adds rows only and needs no schema change, so existing encrypted snapshots load
unchanged.

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

The global traffic log and uvicorn request access log are off. Aggregate Prometheus metrics are
on at `GET /metrics`, but only for the scrape token in Key Vault secret `metrics-token`
(`Authorization: Bearer`); they carry no tenant, principal or endpoint labels. Rotate the token
by adding a secret version, updating `METRICS_TOKEN_SECRET_URI` and releasing (LAB-1732). Each hosted
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
| `PII_GUARD_HOSTED_SOURCE_TAG` | Default `pii-guard-hosted-demo`, `[A-Za-z0-9._-]{1,64}`; sent as `X-PII-Guard-Source` on sponsored Meta calls only ([attribution](#sponsored-upstream-attribution)) |
| `PII_GUARD_NER_MODEL`, `PII_GUARD_DETECTORS` | `/app/models/ner`, `rules,ner`; cannot silently drop NER |
| `PII_GUARD_HOSTED_SPONSORED_MICRODOLLARS` | Default `0`; approved cumulative ceiling, max USD 50 on prod and USD 10 on dev |
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
| `PII_GUARD_POLICY_OVERRIDES` | Unset: owners' project policies decide visual actions; an override set here wins when stricter |
| `PII_GUARD_HOSTED_MAX_IMAGE_BYTES`, `PII_GUARD_HOSTED_IMAGE_MAX_PIXELS` | Defaults 4 MiB decoded and 8 MP, checked before OCR |
| `PII_GUARD_HOSTED_IMAGE_TIMEOUT` | Default 60 s per image; one image job per replica, a busy replica answers `429` |
| `PII_GUARD_HOSTED_USER_IMAGES_PER_DAY`, `PII_GUARD_HOSTED_GLOBAL_IMAGES_PER_DAY` | Defaults 20 and 500, reserved before work, never refunded |
| `PII_GUARD_HOSTED_CHAT_IMAGES` | Default `false`. With hosted images on, a signed-in Google owner's direct chat or Responses call on their own connection may carry inline images; the sponsored route, guard API keys and endpoint paths stay text-only |
| `PII_GUARD_HOSTED_CHAT_MAX_IMAGES` | Default 1 (at most 4) inline images per chat request; the chat body limit grows by that many base64 images, and a body without one keeps the text limit |
| `PII_GUARD_HOSTED_IMAGE_INPUT_TOKENS` | Default 16,384 provider input tokens reserved per chat image, plus 32 KiB for its masked transcript; the image bytes are never charged as text tokens |
| `PII_GUARD_HOSTED_SPEND_MANAGED_IDENTITY_CLIENT_ID` | Dedicated runtime UAMI client ID |
| `PII_GUARD_HOSTED_ALLOCATION_EXPIRES_AT` | Unix UTC expiry for a positive allocation |
| `PII_GUARD_TRAFFIC_LOG`, `PII_GUARD_METRICS` | `off`, `true` (scrape token `PII_GUARD_METRICS_TOKEN` from Key Vault secret `metrics-token`, LAB-1732) |
| `VITE_PII_GUARD_ROBOTS` (UI build arg) | Default `disallow`, and the hosted image keeps it. The app (`pii-guard up` and the hosted image) answers `/robots.txt` at runtime from the request host, so the build's file only matters when `ui/dist` is served by something else. That is the runtime switch: the one image promoted from dev to prod is indexable only on `guard.watt-mind.com` (`Allow: /`, with `/v1/`, `/docs`, `/openapi.json`, `/healthz` and `/readyz` disallowed). Every other host, including `guard-dev`, the `azurecontainerapps.io` hostnames and localhost, gets `Disallow: /` |
| `VITE_PII_GUARD_DEMO_VIDEO_URL`, `VITE_PII_GUARD_DEMO_VIDEO_POSTER` (UI build args) | Unset by default: the landing's demo video slot stays hidden. Set the URL (and optionally a poster image) to show a poster with a play button above the demo |

### Browser security headers

The hosted app sets these on every response itself, once each (`src/pii_guard/security_headers.py`,
LAB-1460); a header a route already set is not repeated. The dev router forwards and collapses
headers (LAB-1467), so they do not belong there. `Strict-Transport-Security` comes from the Azure
Container Apps ingress, so the app does not send a second one.

| Header | Value |
|---|---|
| `Content-Security-Policy` | `default-src 'self'`; scripts and styles from the origin plus the SHA-256 of each inline `<script>`/`<style>` in the served `index.html` (computed at startup, so the build-dependent theme script stays allowed); `img-src 'self' data: blob:`; `font-src 'self' data:`; `connect-src 'self'`; `object-src 'none'`; `base-uri 'none'`; `form-action 'self'`; `frame-ancestors 'none'`. `/docs` and `/redoc` (Swagger UI and ReDoc load from a CDN) keep only `frame-ancestors`, `object-src` and `base-uri` |
| `X-Content-Type-Options` | `nosniff` |
| `X-Frame-Options` | `DENY` |
| `Referrer-Policy` | `same-origin`: not `no-referrer`, under which a browser may send `Origin: null` on a write and the same-origin check refuses it |
| `Permissions-Policy` | camera, microphone, geolocation, payment, USB, serial, HID, Bluetooth, MIDI, display capture and topics off |
| `Cross-Origin-Opener-Policy` | `same-origin` |

Anything the UI loads from another origin needs the policy widened first: for example a
`VITE_PII_GUARD_DEMO_VIDEO_POSTER` on another host is blocked by `img-src`; ship it in `ui/public/`
instead. `pii-guard up` (local) sends none of these unless `create_bundle_app(..., security_headers=True)`.

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
   `TENANT_KEY_SECRET_URI`, `GOOGLE_SECRET_URI`, `METRICS_TOKEN_SECRET_URI`. URI variables must refer to **versioned**
   secrets in the dedicated vault. No secret values enter the script. Run
   `deploy/azure/deploy.sh stage`; it validates and deploys internal ingress, Google Easy Auth,
   one replica in prod or zero to one in dev (LAB-1711), with one worker per replica, and waits boundedly for the latest revision to be admitted as ready. Verify application
   readiness through ingress too; in dev scale-to-zero is expected after idle periods.
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
a platform-managed certificate using CNAME validation. `bind-domain` is re-runnable: it
skips `hostname add` when the hostname is already in
`properties.configuration.ingress.customDomains`, then binds, so a re-run after a
successful bind is a no-op success. Managed-cert issuance needs public reachability from
DigiCert DCV IPs: if the first `bind-domain` ran while ingress was still internal, the
certificate stays Pending until ingress goes external; re-run `bind-domain` once it is
public to complete the binding. App release preserves that binding and
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
- **Spend and rollback:** require written provider authorization **or** the owner's recorded
  risk acceptance (LAB-1389, [below](#owner-risk-acceptance-is-not-authorization)), Standard
  routing, reviewed pricing/reservations and exact approved ID/ceiling/expiry pins before
  setting positive sponsorship. Before any general-availability launch, remove sponsored Meta
  as the default route unless written authorization has arrived. Keep it zero for technical-only releases. Save the previous immutable image
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

Sponsored budget remains zero until written provider authorization (or the owner risk
acceptance below) and the other launch gates are recorded, and the operator supplies
`HOSTED_SPONSORED_MICRODOLLARS`, `HOSTED_ALLOCATION_ID` and `HOSTED_ALLOCATION_EXPIRES_AT`.
A positive allocation needs **one** of two evidence keys. `meta_proxy_authorized: true` may be
set only after the maintainer records written Meta authorization.

### Owner risk acceptance is not authorization

No written Meta gateway/proxy authorization exists today. On 2026-10-28 the account owner
decided, on LAB-1389, to run the sponsored route for the hackathon demo anyway and to accept
responsibility for the possible non-compliance with the Meta Model API Terms (§10.1(i)). That
is a **risk acceptance, not an authorization**, and the evidence says so with a separately
named key; never record `meta_proxy_authorized: true` on the strength of it:

```json
"meta_proxy_owner_risk_accepted": {
  "by": "owner", "ref": "LAB-1389", "date": "2026-10-28", "scope": "hackathon-demo"
}
```

`deploy.sh` accepts exactly these four keys with these values (`date` a real, non-future
`YYYY-MM-DD`), refuses any other shape even next to `meta_proxy_authorized`, and prints that the
allocation is admitted under risk acceptance. It replaces no other gate: LAB-1372, image
binding, the dev network keys, the per-environment ceiling and the operator's allocation pins all still
apply. Its conditions: hosted demo only (dev now, prod for judges), a finite allocation with a fixed expiry after the hackathon, and attribution headers on
every sponsored call. **Before any general-availability launch, sponsored Meta stops being the
default route unless written authorization arrives**; delete the waiver from new evidence then.

The allocation cap is per environment and enforced in both `deploy.sh` and `release.bicep`:

| Environment | Cap | Approved pins | Owner decision |
|---|---|---|---|
| dev | USD 10 (`10000000` µ$) | `dev-hackathon-20261029` | LAB-1389, 2026-10-28 |
| prod | USD 50 (`50000000` µ$) | `prod-hackathon-20261029`, expires `1796083200` (2026-12-01T00:00Z) | 2026-10-29, in chat: "do with $50 please." (LAB-1508, recorded on LAB-1389) |

The prod extension widens only the amount and expiry. The evidence key above is unchanged and is
still a risk acceptance, not authorization.

### Sponsored upstream attribution

Every sponsored upstream call (the server-owned Meta route: no own connection selected, or a
project endpoint whose provider is `sponsored`) sends `User-Agent:
pii-guard/<version> (+https://github.com/watt-mind/pii-guard)` and `X-PII-Guard-Source:
<PII_GUARD_HOSTED_SOURCE_TAG>`, so Meta can attribute the traffic to this deployment. Both are
fixed per deployment and carry no user, principal, project, session or network identifier;
the tag is validated at startup (`[A-Za-z0-9._-]{1,64}`). Bring-your-own-key and custom
endpoints, including an own Meta key, get neither header, and a client-sent
`X-PII-Guard-Source` is never forwarded.

Releases reuse the operator's exact
existing authority pins. The operator precreates the private object; neither bootstrap nor
app release funds it. Changing the ID or cumulative ceiling must preserve charged total and
current-day charges. Reconcile actual upstream usage and outstanding reservations before
approving additional authority; unknown commits are charged conservatively. Never delete or
restore the object to replenish credit. Legacy marker-only deployments retain their original
restart-forfeiture rules and are not the Blob-backed release path.

Prod keeps one 2-vCPU/4-GiB replica warm (LAB-1711) so signed-in visitors never wait on a
cold start; dev scales to zero when idle. Both run at most one replica. A cold start
serves the landing page, the UI, `/healthz` and `/v1/status` as soon as the process is up and
loads the bundled NER model in the background (LAB-1548). Until it is loaded, detecting
requests wait up to `PII_GUARD_NER_WARMUP_TIMEOUT` and then get `503 detector_loading` with
`Retry-After`; a model that fails to load gets `503 detection_unavailable`. Nothing is ever
detected without the model or forwarded unmasked. A replica restart, or
scale-to-zero in dev, discards owner state. The Blob store resumes the same finite total/daily authority; it never
reopens credit automatically.
ACR Basic, Key Vault, Azure Files, networking and alerting cost extra. The USD 50 (prod) and USD 10 (dev) limits are
application sponsored allocation ceilings, not Azure hard caps or verified price estimates.
Bootstrap creates the owner-approved EUR 25/month resource-group budget with 50/80/100%
notifications routed to the existing selected action group. `stage` and `enable` refuse to run
without that budget and preserve its start date/recipients. Azure budgets alert; they do not
stop billing. The EUR infrastructure budget is separate from USD sponsored allocations.
Review daily and disable external ingress/stop the dedicated app when the demo ends. Preserve
the authority object and any legacy claim markers, and follow Key Vault recovery obligations when cleaning up resources.

## Observability, refusal and rollback

`/healthz` reports liveness/model state (`ner`: `loading`, `ready` or `failed`); `/readyz`
refuses until the required hosted NER stack is ready, and the deploy smoke waits for it.
`/readyz/serving` is serving readiness: it also admits a replica whose model is still
loading (never one whose load failed, which answers `503 detection_unavailable`, or whose
image pipeline is missing). It is a plain path because Container Apps documents no query
string in probe paths. The Bicep Readiness
probe uses it, because Container Apps holds a scale-from-zero request until the replica is
Ready, so probing full `/readyz` would hold the landing page for the whole model load. The
Startup probe allows up to ten minutes for the process to answer `/healthz`. Container Apps ignores Docker `HEALTHCHECK`; the explicit Bicep startup/readiness/liveness
probes are required and send `Host: localhost`. `PII_GUARD_ALLOWED_HOSTS` adds the canonical
public host and app default Azure host; loopback hosts remain allowed for probes. The image
also checks `ner=ready` in its Docker healthcheck for local Docker verification. No image/OCR capability is advertised.
The template creates content-free alerts for restarts, CPU saturation and memory
pressure; dev scale-to-zero is expected and does not trigger a replica-loss alarm; attach a monitored action group before relying on delivery. In Azure Monitor inspect
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
