# Hosted deployment pipeline

This prepares reviewed deployment automation for **develop → dev** and **main → prod**.
The repository default branch is `main`, the production branch: it only moves on a release
(a `develop` → `main` pull request), so clones and `git+` installs get the last release. Work
lands on `develop`. The existing
version-tag workflow continues to publish the self-hosted image and Python distributions.
It does not deploy the hosted application.

## Disabled until configured

`HOSTED_DEPLOYMENTS_ENABLED` is an explicit repository variable. Leave it unset or `false`
until the designated reviewer has merged the dependencies and approved deployment setup.
No workflow or helper in this change configures identities, GitHub settings, networking,
secret values or budgets. Merging this change alone does not deploy an application.

The required `ci-ok` check remains the test gate. Only successful **push** runs on the exact
canonical repository branches may call `hosted-deploy.yml`. PRs, merge groups, scheduled
runs and manual test runs do not enter credential-bearing jobs. The reusable workflow also
checks the actual GitHub run/jobs metadata before preparing a target; it does not accept a
caller-supplied claim that CI passed. Stale queued runs refuse after their branch advances.

## One candidate, two runtime environments

| Branch | Pipeline | Runtime exposure |
|---|---|---|
| `develop` | Prepare → publish candidate once → reviewed dev stage and synthetic smoke | Dedicated tailnet-connected runner and reviewed private route only |
| `main` | Prepare matching successful dev evidence → import exact digest → reviewed prod enable | Production origin, only after the existing public release gates |

The dev image is built from `Dockerfile.hosted` and published with provenance and an SBOM.
Deployment always uses `registry.azurecr.io/pii-guard@sha256:…`, never the mutable convenience
tag. The publish job records its digest before any application deployment.

Release evidence remains **manual and image-bound**. Set the environment's reviewed
`HOSTED_RELEASE_EVIDENCE_JSON` for that exact image, then rerun the failed deployment job
without rerunning the successful publish job. Environment review should inspect the
candidate digest shown in the publish job summary. CI never fills in approval flags.

A successful dev stage and smoke produce the immutable Actions artifact
`hosted-tested-<source-tree>`. It records source SHA/tree, template/script hash, digest,
repository, run ID, target and smoke completion. Production accepts it only from a
successful canonical `ci.yml` push run on `develop`, no more than seven days old. It must
match the production source tree and template exactly. The import must preserve the
manifest digest in the separate production ACR. A changed source tree, missing artifact or
mismatched digest blocks promotion; there is no production rebuild fallback. Release by
fast-forward or a content-identical merge; otherwise test the changed content in dev first.
Artifacts are looked up among the latest 100 successful develop runs and retained seven
days. If evidence ages out, run a fresh dev candidate rather than bypassing the policy.

## Minimal one-time setup

An operator configures the following after review, outside this workflow:

1. Create GitHub Environments `hosted-build`, `dev` and `prod`. The first two allow **only
   the exact branch `develop`**; prod allows **only `main`**, with a required reviewer and prevention of self-review.
   Use custom deployment-branch rules, not wildcard/protected-branch shortcuts. The helper
   reads and verifies these policies before Azure login. The repository's GitHub plan must
   support the configured protections.
2. Provision separate Entra workload identities for publisher, dev deploy and prod deploy.
   Use GitHub OIDC with the actual repository subject format, exact environment identity,
   issuer `https://token.actions.githubusercontent.com` and audience
   `api://AzureADTokenExchange`. New repositories may use immutable repository IDs in the
   subject; do not copy a legacy subject blindly. An environment OIDC subject does not
   encode the branch, so the GitHub Environment branch rules are required too.
3. Scope the publisher to candidate ACR push only. Scope each deploy identity to its own
   pre-provisioned runtime resources; prod also needs permission to read/import the approved
   candidate into its own ACR. Runtime managed identities remain separate. Do not grant
   workflow identities access to raw provider secrets, budget funding, allowance creation
   or subscription-wide administration. Bootstrap/RBAC provisioning stays an operator step.
4. Provide a dedicated Linux self-hosted runner labeled `pii-guard-dev` with access to the
   reviewed private dev route and GitHub/Azure control plane. There is no public runner
   fallback for dev deployment/smoke. Place it in an organization runner group restricted
   to the canonical trusted workflow/ref, with ephemeral or rebuilt-per-job isolation.
   Select only `watt-mind/pii-guard/.github/workflows/hosted-deploy.yml@refs/heads/develop`
   for group workflow access: the private job is defined in this reusable workflow.
   Labels and YAML branch checks alone do not prevent another PR workflow from requesting
   a persistent runner. Do not use the security proxy/router as a CI agent. If the GitHub
   plan cannot enforce selected-workflow/ref restrictions, do not enroll a private runner.
   Set repository variable `HOSTED_PRIVATE_RUNNER_READY=true` only after these controls
   are independently verified; preparation refuses before runner allocation otherwise.
5. Finish the private network and durable spend-accounting prerequisites. The side-effect-free `deploy.sh ci-preflight <dev|prod>` proves the reviewed
   app-only release contract before Azure login (see "App-only release contract" below). Both targets remain refused until the companion
   Azure changes land. Internal ACA ingress by itself does not establish a Tailscale route.
6. Configure the variables below, prove live OAuth/hostname/network/release gates, then
   explicitly enable the repository switch. No credentials or switches are set by this PR.

### Environment variables

All values here are GitHub **Environment variables**, except the repository enable switch.
Azure client/tenant/subscription IDs are identifiers, not client secrets. Provider, tenant
and Google client secret values remain in that environment's Key Vault.

| Environment | Required configuration |
|---|---|
| `hosted-build` | `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID`, `HOSTED_REGISTRY` |
| `dev`, `prod` | Their own Azure IDs, `AZURE_RESOURCE_GROUP` (`rg-pii-guard-dev` or `rg-pii-guard-prod`), `HOSTED_REGISTRY`, `HOSTED_PUBLIC_ORIGIN`, `GOOGLE_CLIENT_ID`, versioned `META_KEY_SECRET_URI`, `TENANT_KEY_SECRET_URI`, `GOOGLE_SECRET_URI`, and exact `HOSTED_RELEASE_EVIDENCE_JSON` |
| `dev`, `prod` | `HOSTED_ENVIRONMENT_READY=true`, `HOSTED_NETWORK_READY=true`, `HOSTED_BUDGET_READY=true` only after operator review of the corresponding prerequisites |

Dev additionally requires `AZURE_DEV_NETWORK_APPROVED=true` and the exact split-DNS origin
`https://guard-dev.watt-mind.com`. Its image-bound release evidence must explicitly approve
`private_dev_reviewed`, `tailnet_acl`, `proxy_tls` and `proxy_headers` as well as
`lab_1372_done`. These are manual approvals, not CI-generated values. The dedicated CI
runner identity/tag needs an explicit narrow tailnet grant for dev HTTPS (TCP 443) and the
approved split-DNS resolver (DNS 53); an operator's admin-user grant does not authorize the
runner implicitly. No router enrollment credential is passed through CI.

`AZURE_PROJECT_PREFIX` optionally selects the existing deployment's prefix. Dev and prod
must have distinct runtime identities, Key Vaults, provider credentials, tenant keys,
OAuth clients/callbacks, allocation stores and registry/resource names. Reusing the same
image and template does not share those states or secrets.

The compatibility runtime inputs `HOSTED_SPONSORED_MICRODOLLARS`, `HOSTED_ALLOCATION_ID`
and `HOSTED_ALLOCATION_EXPIRES_AT` are passed through unchanged from approved environment
configuration. CI does not choose an amount, generate an ID, extend expiry or initialize a
ledger. Positive sponsorship still requires the exact image's provider authorization and
existing script gates. Do not enable this pipeline against restart-sensitive accounting:
finite funding must survive scale-to-zero and redeployment without an automatic refill.
The runtime budget contract is owned by the companion accounting change; readiness stays
false until the operator verifies that contract with these inputs.

### App-only release contract

The workflow invokes `deploy.sh ci-preflight <dev|prod>` before Azure login. This mode must
use local source/configuration checks only and return exactly the reviewed capability
version: `version:1`, `app_only:true`, `no_storage_keys:true`,
`no_role_assignments:true`, `durable_budget:true`, and `private_dev:true` for dev. It must
not return ready capabilities before those properties are implemented. Setting readiness variables early cannot bypass
the missing contract: `ci-preflight` fails closed with `reviewed_app_release_contract_unavailable` unless the reviewed template satisfies it.

CI must use the app-only release template provided by the Azure lane. Reapplying a
foundation template that lists storage account keys or writes role assignments is not
allowed with the deployment identity. This split is a prerequisite, not a request to grant
broader CI permissions. The release identity needs only selected resource metadata reads
and app/auth/alert writes, including `Microsoft.Insights/actionGroups/read` at each selected
existing action group (which can live outside the project resource group). It needs no
action-group writes or receiver details. Runtime preflight must verify the actual private environment,
proxy/ACL/TLS readiness and durable ledger binding before staging dev.

## Verification and recovery

The offline policy suite tests exact branch/event admission, missing prerequisites,
provenance/schema validation, source/template mismatches, expiry and digest equality.
Workflow validation uses actionlint and zizmor. Hosted image/template tests remain in the
existing CI job. That Linux job discovers `deploy/azure/test_*.py`, compiles the app-only
release template when present and lints the router shell installer. It installs nginx and
OpenSSL so the companion router's actual loopback TLS/header tests execute after those
source files are integrated. This does not claim those new cases ran on the older
foundation-only stack. Automated runtime smoke uses synthetic fixtures only; real user inputs
must never enter test fixtures or CI logs.

The pipeline calls `stage` for dev and `enable` for prod. It never invokes `bootstrap`.
The existing script's failed public-enable path attempts to disable external ingress.
That is **not** a promise to restore an earlier revision or undo every infrastructure
change. Inspect the failed deployment; apply a previously approved immutable digest only
through the same reviewed gates. Do not create fresh funding to make a retry pass.

CI green does not establish live Google OAuth, hostname/TLS, private reachability, provider
terms or real-provider behavior. Those remain explicit operator release evidence. This PR
neither enables a public service nor bypasses the no-deployment instruction during review.

```sh
uv run python -m unittest discover -s scripts/ci -p 'test_hosted_deploy.py'
uv run ruff check scripts/ci/hosted_deploy.py scripts/ci/test_hosted_deploy.py
uv run ruff format --check scripts/ci/hosted_deploy.py scripts/ci/test_hosted_deploy.py
actionlint
uvx zizmor@1.31.1 --min-severity=low .github/workflows
```

References: [GitHub Azure OIDC](https://docs.github.com/en/actions/how-tos/secure-your-work/security-harden-deployments/oidc-in-azure),
[GitHub Environment protections](https://docs.github.com/en/actions/how-tos/deploy/configure-and-manage-deployments/manage-environments),
[ACR digest import](https://learn.microsoft.com/en-us/azure/container-registry/container-registry-import-images),
[runner group workflow restrictions](https://docs.github.com/en/enterprise-cloud%40latest/actions/how-tos/manage-runners/self-hosted-runners/manage-access).
