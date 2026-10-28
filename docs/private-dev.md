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
Keep sponsorship zero until provider authorization and approved durable authority exist.

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

## Finite authority, cost and rollback

App releases configure LAB-1398's `azure_blob` store and reuse the exact operator-approved
cumulative ceiling, allocation ID and expiry. The isolated private container is
`sponsored-allowance`, with a fixed `dev.json` object. Bootstrap creates no object/funding. An
operator precreates/funds it only after provider permission; releases never create, reset,
refill or extend it. Total/daily charges survive zero replicas and overlapping revisions under
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
