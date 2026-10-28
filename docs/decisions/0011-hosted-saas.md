# 0011. An opt-in hosted demo with explicit processing boundaries

- **Status:** accepted design; public launch remains gated
- **Date:** 2026-10-28

## Context

The local demo assumes one trusted operator. Publishing it unchanged would expose mappings,
provider credentials and paid upstream capacity. A hosted service also receives original text;
self-hosted privacy claims cannot describe that deployment.

## Decision

Provide a public landing page and a curated Hungarian/English synthetic walkthrough. Anonymous
live requests select a server-owned synthetic sample; they cannot supply editable original
text, an upstream URL or a model. Google is the first sign-in provider. Signed-in users may
submit editable **text** and use temporary BYOK profiles whose destinations pass the server's
public-HTTPS endpoint policy. Hosted uploads, images, remote LLM detection and arbitrary
anonymous prompts remain disabled. The existing self-hosted mode stays available separately.

Sponsored generation is proposed through Meta Standard, subject to the
[written-authorization requirement](https://dev.meta.ai/legal/terms-of-service) for proxy/API
gateway offerings in section 10.1(i). A technical launch review cannot waive that gate.
After authorization, use the server's model allowlist and secret. Verify the account's actual
tier and current terms before activation;
configuration cannot prove the account's commercial terms. Contributor/data-sharing modes are
unsuitable for real inputs, including masked inputs. Local CPU NER plus rules process originals;
a remote detector would receive originals and requires a separate explicit trust decision.

Deploy into dedicated Azure resources: ACR, Container Apps, managed identity and Key Vault.
The image includes the production hosted UI and the existing pinned, hash-verified NER model.
Missing models prevent readiness. HTTPS and Easy Auth cover every ingress route, including the
Azure default hostname. Easy Auth permits anonymous landing/guest traffic; server middleware
still authorizes every protected API and scopes mappings to the authenticated owner. Only the
platform's stripped and injected identity headers are trusted. No second exposed origin or
container TCP ingress may bypass that boundary. Cookie writes require same-origin CSRF checks.

The initial runtime has **zero to one replicas and one worker per replica**. Mappings, temporary provider
profiles, API-key records and visitor/user counters are ephemeral. Their loss on restart is
intentional and must be disclosed. It is not the durable/shared state architecture in LAB-1376.
A small Azure Files share stores **allocation claim markers only**, preventing a restart from
reusing sponsored credit. A process claims a one-time, expiring allocation atomically; after
restart that allocation is forfeited until an operator reconciles spend and issues a fresh ID.
Do not delete markers as a way to restore credit. Default sponsored budget is zero; each
explicit deployment allocation is capped at USD 10. Reservations must cover worst-case model
costs. Azure infrastructure costs are separate and remain an operator responsibility.

No prompt, restored answer, identity claim or credential belongs in telemetry. Platform counts,
readiness, replica/restart counts and CPU/memory usage are sufficient for the first deployment.
The global traffic log and public metrics are disabled. Each owner retains its last 50 masked
traffic events in memory, readable only by that owner; owner purge or restart frees them. The project maintainer owns
privacy/acceptable-use review and provider-terms verification before editable text is enabled.

## Rollout and evidence

1. Land the ADR, hosted authorization, owner isolation, CSRF, quotas and endpoint policy.
   LAB-1372 must be Done before public enablement or any positive sponsored allocation.
   Merge #159, then #156, then #157; rebase deployment after the backend lands.
2. Use environment-derived production names (`rg-pii-guard-prod`, `piiguard-prod-*`) and
   matching `project`/`environment` tags. Recreate the resource group and foundation in Sweden
   Central with the owner-approved EUR 25/month notification budget and min replicas zero.
   The budget is not a hard cap. Cold starts reload NER and forfeit prior claimed credit.
   Build the hosted image and stage it with internal ingress. Configure Google OAuth callback
   for the eventual public HTTPS origin. Test model readiness and mount behavior.
3. Review synthetic tests for isolation, forged identity headers, quota exhaustion/restart,
   SSRF/redirect refusal, streaming mask/restore and failures. Confirm public notices and the
   Meta account tier. Explicitly enable external ingress only with image-bound review evidence.
4. Run the public smoke; test Google sign-in and the chosen provider through Azure ingress.
   Enable a small sponsored allocation only after conservative spend reservations and durable
   claim behavior are verified. An allocation may be exhausted or forfeited; guests then see a
   refusal, never an unmetered fallback.
5. Add LAB-1376 durable owner data and shared counters before introducing multiple processes,
   replicas, restart continuity or persistent account guarantees. Review retention again then.

[Hosted operations and privacy](../hosted.md) defines the runnable steps and current limits.

## Dev/prod follow-on

`develop` is intended for tailnet-only dev and the actual production branch for prod, using the
same image with isolated credentials/state/budgets. Dev cloud/app deployment is currently
blocked pending a reviewed private VNet/Container Apps environment plus always-on tailnet
proxy/router, DNS/TLS and OAuth callback. A sleeping app sidecar cannot wake itself. The
finite sponsored default remains subject to provider permission and reconciled allocation
policy; see the [dev/prod plan](../hosted.md#devprod-deployment-plan--private-dev-networking-pending).
No branch deployment workflow or public dev app is enabled here.

## Consequences

This provides a reviewable hosted path while preserving a small initial trust boundary.
Scale-to-zero, deployment, restart and rollback can invalidate sessions and require a new reviewed sponsored
allocation. There is no claim of anonymity, perfect detection, guaranteed physical memory
erasure or production SLA. Detection misses and contextual clues may still identify people.
