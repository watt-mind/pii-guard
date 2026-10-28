# Private dev deployment

This is the **dev environment of hosted PII Guard**, using the same reviewed application image
as prod. `develop` targets dev; the actual production branch is `main`. It is not a separate
product. Source is prepared here; no router enrollment, private OAuth flow or Azure packet path
is proven by compilation. Keep deployment readiness switches off until the live checks below
pass. Production foundation resources are outside this deployment's scope.

The request path is the user's tailnet → a dedicated always-on proxy VM → HTTPS to the private
Container Apps ingress → Easy Auth → PII Guard. The environment has an internal VNet endpoint
and `publicNetworkAccess=Disabled`. The app's `external=true` means reachable from that VNet,
not the internet. Its NSG admits HTTPS only from the proxy's fixed private address, platform
load-balancer probes and necessary intra-environment traffic.

The VM advertises **no subnet or exit-node routes** and performs no forwarding/SNAT. It is not
a CI runner. Its Standard public IPv4 supplies outbound access, with unsolicited Azure ingress
blocked by NSG. Nginx HTTPS and DNS listen only on its Tailscale address; no public SSH, public
HTTP application or Funnel is configured. Tailscale may use encrypted DERP fallback when direct
peer transport is unavailable. Private DNS inside the VNet resolves the ACA default hostname.
Tailnet restricted DNS must target **only `guard-dev.watt-mind.com`**, pointing to the router's
resolver; do not capture the parent domain or the prod hostname.

## Operator foundation and app releases

`main.bicep` is operator-only: network, registry, identities, vault, storage/RBAC and alert
budget. It never creates a Container App. `release.bicep` writes only the app, its auth config
and content-free metric alerts. CI must not apply the foundation or have storage account-key,
role-assignment or budget-funding rights. The local handshake is:

```bash
deploy/azure/deploy.sh ci-preflight dev
```

Its version-1 JSON reports the reviewed release-path capabilities; it does not certify live
network readiness. App release still verifies the existing budget, its monitored action groups,
actual internal/PNA-disabled environment, dedicated router and image-bound review evidence.
The CI identity needs read access to those specific metadata resources, including the selected
existing action group, plus app/auth/alert deployment rights. It gets no direct allowance data
role. A trusted app deployer can change app code that uses its runtime identity; this is not a
claim of protection against malicious trusted release code.

Use separate `rg-pii-guard-dev`, dev identities, vault objects, account/owner state, ledger and
Google OAuth client. Do not reuse prod credentials, its non-VNet environment or unrelated
existing tailnet nodes. The operator first reviews the network/cost plan, then prepares the
foundation with no VM or app:

```bash
export AZURE_ENVIRONMENT=dev
export AZURE_RESOURCE_GROUP=rg-pii-guard-dev
export AZURE_LOCATION=swedencentral
export AZURE_PROJECT_PREFIX=piiguard
export AZURE_DEV_NETWORK_APPROVED=true
# Set explicit subscription, approved dev monthly budget and existing action-group ID too.
deploy/azure/deploy.sh bootstrap
```

This command is an authorization boundary, not a request to run it before review. Read safe
foundation outputs to locate the dev vault. Populate separate dev `meta-api-key`, `tenant-key`,
`google-oauth-client-secret` and OAuth client ID, plus the two router objects below, through an
in-memory secret workflow. Never use secret values in CLI arguments, files, template parameters
or PR comments. The bootstrap operator receives vault-scoped Secrets Officer; app/runtime and
router identities have separate permissions. The dev app is granted only its three secret
objects; the router gets only its enrollment and TLS secret objects.

## Enrollment, TLS and DNS

Prepare a one-use, preauthorized **non-ephemeral** Tailscale enrollment key tagged only
`tag:piiguard-dev`, owned by `autogroup:admin`. Do not mint it in cloud-init or CI. Store it in
the dev vault and pass only its versioned URI. Parent/operator access to the existing tailnet,
DNS and Google administrative sessions is sufficient; no live credential value belongs in the
source PR.

Obtain the front certificate for **`guard-dev.watt-mind.com`** through owned DNS-01 validation,
without opening a public HTTP endpoint. Store a combined PEM certificate chain and unencrypted
private key as a separate dev Key Vault secret. This is the front certificate; the ACA default
hostname has a different provider certificate which the proxy validates normally upstream.
Google's dev redirect must be exactly
`https://guard-dev.watt-mind.com/.auth/login/google/callback`, using its own client and only
`openid`, `profile`, `email` scopes. See the [Google audience caveat](hosted.md#operator-launch-checklist).

After independent source review and concrete tag/ACL/credential configuration:

```bash
export AZURE_ROUTER_DEPLOY_APPROVED=true
# Set AZURE_ROUTER_ENROLLMENT_SECRET_URI and AZURE_ROUTER_TLS_SECRET_URI to versioned dev references.
# Set AZURE_ROUTER_SSH_PUBLIC_KEY to a public key Azure requires; SSH stays disabled.
# Optional AZURE_ROUTER_VM_SIZE defaults to Standard_B1s, subject to quota/capacity approval.
deploy/azure/deploy.sh bootstrap-router
```

No credential value enters ARM/custom data. The router UAMI reads only the two referenced
secret objects through managed identity. The enrollment key travels to Tailscale through stdin,
not argv, environment or a file. Its normal machine identity persists root-only on Azure's
encrypted OS disk so a reboot does not require reusing a consumed enrollment key. The TLS PEM
stays in a sealed anonymous Linux memory file held by the supervisor; Nginx reads it through
`/proc`, and the private key never enters disk configuration. No request/access/error-content
logs are enabled. The router sees original input while proxying and is inside the hosted trust
boundary. It must not spill request/response bodies to disk.

VM ARM provisioning success alone does not prove enrollment or proxy health. Verify the
systemd service, obtain only the device's tailnet IP, and configure a narrow admin-only grant
for router TCP443 and TCP/UDP53. Adding a narrow grant does not override existing broad
allow rules: review the full effective tailnet policy and prove an unauthorized peer is denied.
If a dedicated CI node is tagged separately, it needs its own narrowly scoped service grant;
tag ownership by an admin does not make a tagged device an admin user. Never grant a CI node
subnet/exit-node routing. Configure restricted DNS for the exact hostname, then verify TLS from
an authorized tailnet client and denial from outside the tailnet.

Renewal requires an approved new TLS-secret version, updating only the non-secret URI in the
root-owned router configuration and restarting the supervisor through the operator channel.
Do not dump configuration, environment, secret responses or OAuth callback queries. Losing the
machine state requires a fresh approved one-use enrollment key; do not silently create one.

## App activation and identity proof

`stage` is the dev release mode. Public `enable` and public domain binding are rejected for
dev. Use the same immutable image digest and normal versioned app key references, set
`HOSTED_PUBLIC_ORIGIN=https://guard-dev.watt-mind.com`, and provide reviewed evidence containing
`lab_1372_done`, `private_dev_reviewed`, `tailnet_acl`, `proxy_tls`, `proxy_headers` for that image.
Keep sponsorship zero until provider authorization (or the owner's recorded LAB-1389 risk
acceptance, `meta_proxy_owner_risk_accepted`) and approved durable authority exist. That
waiver is a risk acceptance, not Meta authorization: it is scoped to the hackathon demo, capped
at USD 10 with a fixed expiry, and sponsored Meta stops being the default before general
availability unless written authorization arrives
([hosted.md](hosted.md#owner-risk-acceptance-is-not-authorization)).

### Operator technical stage before live acceptance

The first private app is needed to collect end-to-end identity, OAuth and isolation evidence.
An operator can use `deploy/azure/deploy.sh technical-stage` for that synthetic verification
only. It requires `AZURE_TECHNICAL_STAGE_APPROVED=true`, an active Azure CLI account of type
`user`, the exact dev group and origin, and no `CI` or `GITHUB_ACTIONS` environment. Set
`HOSTED_SPONSORED_MICRODOLLARS=0` and leave both allocation ID/expiry variables unset.
All existing budget/action-group, own-registry image digest, versioned dev-vault, internal
PNA-disabled environment and dedicated-router checks still apply. The app stays reachable only
through the private environment; the usual readiness and content-free smoke run after staging.

Set `HOSTED_TECHNICAL_STAGE_EVIDENCE` to an uncommitted JSON file with exactly these fields:

```json
{
  "image": "<reviewed immutable image digest>",
  "purpose": "private-synthetic-verification",
  "network_reviewed": true,
  "tailnet_acl": true,
  "proxy_tls": true,
  "synthetic_only": true
}
```

These attest the pre-app network controls already reviewed and tested: authorized and refused
peer access and front TLS can be tested before the ACA app exists. They do not claim live
header stripping, Google callback, cross-owner isolation or LAB-1372 acceptance. This path
creates no funding or allowance object. Keep automatic releases disabled, collect the full live
acceptance evidence on this private synthetic stage, and then use normal `stage`; technical
evidence cannot satisfy normal release admission. Public `enable` and CI have no technical-stage
exception.

The proxy drops caller `X-MS-*`, `Forwarded`, `X-Forwarded-*`, `X-Real-IP`, Host and custom
external-host/proto fields, then sets a fixed ACA Host and canonical HTTPS external host.
Easy Auth explicitly consumes `X-Pii-Guard-External-Host` and `X-Pii-Guard-External-Proto` under
its Custom forward-proxy setting. Preserve actual caller Origin and Sec-Fetch-Site for CSRF;
never invent same-origin evidence. Google redirects must target the private dev hostname.

Before enabling automatic dev releases, prove valid-shaped forged identity headers stay
anonymous/refused through the **whole** proxy/ACA/sidecar chain, Google sign-in/callback works,
wrong-origin cookie mutation is refused and cross-owner/API-key access is denied. Test duplicate
security headers too. The direct-ACA `aca_xff_rightmost` client-IP assumption is unproven for
this additional proxy; dev forces `PII_GUARD_HOSTED_CLIENT_IP_SOURCE=off`, disabling the
network limiter rather than attributing all users to the router. This setting does not require
Google sign-in: reachable guests can use curated demos under guest/global quotas and approved
finite authority. Zero sponsorship or an unavailable ledger refuses sponsored work. Tailnet ACLs
bound dev reachability. Do not describe the router's address as an individual user.

Scale the app to zero and issue a private request through the still-running proxy. Confirm
HTTP autoscaling wakes it and required local NER reaches readiness before processing. A sleeping
app sidecar cannot provide this wake path. Repeat streaming and synthetic error checks and show
that OAuth code/state, auth, cookie and body canaries appear in neither proxy output nor generated
files. Local Linux Nginx tests exercise these properties but cannot prove the deployed Azure path.

## Merge to dev: the image CI built, deployed after `ci-ok`

The dev image is built once, by CI (LAB-1446). On every push to `develop`, `hosted-infra` builds
and smoke-tests Dockerfile.hosted, then `hosted-image-push` rebuilds it from the same layer cache
(all hits) and pushes `<dev registry>.azurecr.io/pii-guard:develop-<short sha>`. It runs in the
`dev-image` GitHub Environment (deployable from `develop` only) with an OIDC identity that has
`AcrPush` on the dev registry and nothing else: no secret, no deploy right. The job summary
shows the pushed `HOSTED_IMAGE` (`...pii-guard@sha256:...`). `hosted-image-push` is a delivery
job outside `ci-ok`, so a registry hiccup leaves CI green without an image; use the fallback.

Develop pushes run the fast test suite (`make test`, the pull-request profile), so `ci-ok`
lands about as fast as on the pull request; the full suite runs nightly, on `main` and on manual
dispatch. After a merge:

```bash
run=$(gh run list --branch develop --workflow ci --event push --limit 1 \
  --json databaseId -q '.[0].databaseId')
gh run watch "$run" --exit-status            # wait for ci-ok on that exact commit
gh run view "$run" --log --job "$(gh run view "$run" --json jobs \
  -q '.jobs[] | select(.name == "hosted-image-push") | .databaseId')" | grep 'IMAGE '
```

Deploy only after `ci-ok` on that commit is green: pass the `IMAGE` digest as `HOSTED_IMAGE` to
`deploy/azure/deploy.sh technical-stage` (or `stage`) with the evidence described above, bound
to that digest. If `ci-ok` is red, do not deploy that digest; fix forward.

### Manual fallback: `acr_build.sh`

When `hosted-image-push` did not run or failed, build the same commit in the registry. Start it
as soon as the pull request merges, in parallel with develop CI, and still deploy only after
`ci-ok` is green:

```bash
git fetch origin develop
ACR_NAME=<dev registry> deploy/azure/acr_build.sh origin/develop
```

`acr_build.sh` exports the commit with `git archive` (committed files only), runs `az acr run`
with BuildKit, tags `pii-guard:develop-<sha>` and prints `TAG`, `DIGEST` and
`IMAGE <registry>.azurecr.io/pii-guard@sha256:...` on stdout (build logs on stderr). It needs
only the operator's existing `az login` and holds no secret. Each Dockerfile.hosted stage is
also pushed as `pii-guard:buildcache-*`, an inline BuildKit layer cache the next build reads, so
a change under `src/` reuses the dependency, NER model and apt layers. The cache tags are
overwritten on every build; delete them to force a cold build.

## Durable encrypted project configuration

The operator foundation adds a separate private `project-configuration` container in the same
identity-only Blob account as `sponsored-allowance`; it reuses dev's private endpoint and DNS.
It grants the existing runtime identity read/write only in this container with an exact
`dev.projects.v1.enc` ABAC path and listing denied. Prod uses its separate account, identity,
container and `prod.projects.v1.enc` path. No delete, storage key, SAS or account-wide data
permissions are added. Review inherited grants because they can bypass the scoped condition.

The app-only release reads `projectAccountUrl` from the reviewed foundation and sets
`PII_GUARD_HOSTED_PROJECT_STORE=azure_blob`, the fixed container/environment and the runtime
identity's client ID. Preserve the separate environment's existing stable **32-byte tenant
key**: it encrypts the snapshot and provider credentials. Rotating or losing it makes existing
configuration unreadable. This storage persists project/policy/endpoint configuration and key
revocations; mappings, sessions and traffic stay ephemeral. It does not fund sponsorship.

After the combined application image includes the Blob project store, an authorized operator
initializes the empty encrypted blob **once** under that environment's runtime identity and
settings. The foundation creates only the private container. App startup, release and CI never
initialize or migrate project data. Wake the private app from an authorized tailnet client and
wait for `/readyz`, then run this explicit management command against the active app container:

```bash
az containerapp exec --name piiguard-dev-app --resource-group rg-pii-guard-dev \
  --command '/app/.venv/bin/python -m pii_guard.projects.blob --initialize-empty'
```

This uses the existing runtime managed identity and Key Vault-backed tenant key inside the
container; do not copy secrets, dump its environment or provide a token/key in command arguments.
Use `piiguard-prod-app` and `rg-pii-guard-prod` only for the separately authorized prod bootstrap.
The initializer performs create-if-absent and refuses an existing blob, including after an
ambiguous write outcome. Never delete/reset it on retry or restore an older snapshot to roll
back code: doing so can restore revoked endpoint keys. Missing/corrupt/wrong-key/unavailable
storage fails project operations closed without creating local SQLite state. Legacy local
SQLite migration needs a separate reviewed operator procedure.

Verify from the authenticated private app that a synthetic project/policy/endpoint survives a
revision replacement and that a key revoked from one revision stays refused by the next.
Confirm unauthorized identities and alternate/list/delete paths are denied, and missing state
returns sanitized `project_storage_unavailable`. See the combined source's
[Blob project-store contract](projects.md#hosted-encrypted-blob-snapshots) for bounds, CAS,
unknown-write handling and retained limitations. Deployment compilation is not live evidence.

## Finite authority, cost and rollback

App releases configure LAB-1398's `azure_blob` store and reuse the exact operator-approved
cumulative ceiling, allocation ID and expiry. The isolated private container is
`sponsored-allowance`, with a fixed `dev.json` object. Bootstrap creates no object/funding. An
operator precreates/funds it only after provider permission or the owner's recorded LAB-1389
risk acceptance (which is not permission); releases never create, reset, refill or extend it. Total/daily charges survive zero replicas and overlapping revisions under
CAS. Owner sessions, mappings, profiles and API-key records remain ephemeral; LAB-1376 is not
implemented by durable spend accounting.

The runtime gets read/write only at its one container, with an ABAC exact-path condition and
list denial. Shared-key authorization is disabled. For dev, the account public network is
disabled and the Blob private endpoint/DNS are in the same dev VNet. Write authority still
allows same-path creation/authority changes by trusted runtime code; broader inherited grants
can bypass a conditional role. Review effective permissions rather than claiming tamper-proof
accounting. CI and runtime never receive storage keys, SAS or operator funding rights.

Retail EUR estimates checked on 2026-10-28 put a Standard_B1s at about EUR6.94/month (730h),
32-GB Standard HDD at EUR1.35 and Standard IPv4 at EUR3.21: about **EUR11.50/month fixed** before
ACA/VNet managed resources, private endpoints, registry, DNS, storage, keys, traffic and any
separate CI runner. SKU quota/capacity and the full EUR25 dev-budget fit remain unverified.
Budget notifications are not a hard cap; obtain approval for the actual estimate before VM
creation. Do not add a NAT gateway merely to provide this VM's outbound path.

For an incident, disable dev app ingress using `deploy.sh disable`; preserve the ledger and
approved charge history. Stop or isolate the dedicated proxy if needed through the operator
channel, without affecting prod or unrelated tailnet nodes. Roll back to the prior reviewed
immutable image through the same private stage path. Reuse approved allowance pins; never
clear or restore old counters. Re-test TLS, identity stripping, private wake and finite authority
before re-enabling CI readiness.

Primary platform references: [ACA networking](https://learn.microsoft.com/en-us/azure/container-apps/networking),
[ACA NSG rules](https://learn.microsoft.com/en-us/azure/container-apps/firewall-integration),
[explicit VM outbound](https://learn.microsoft.com/en-us/azure/virtual-network/ip-services/default-outbound-access),
[Tailscale DNS](https://tailscale.com/docs/reference/dns-in-tailscale),
[Azure retail price API](https://learn.microsoft.com/en-us/rest/api/cost-management/retail-prices/azure-retail-prices).
