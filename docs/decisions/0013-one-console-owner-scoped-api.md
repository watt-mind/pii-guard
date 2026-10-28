# 0013. One console, one API: owner-scoped runtime and server-declared capabilities

- **Status:** accepted
- **Date:** 2026-10-28
- **Builds on:** [ADR 0011](0011-hosted-saas.md), [ADR 0012](0012-hosted-projects-and-endpoint-configuration.md)
- **Amended by:** [ADR 0014](0014-hosted-local-images.md): hosted `images` is `true` (see the table)

## Context

The hosted dashboard should be the same console as the local one. Most of the backend already
is: `/v1/traffic`, `/v1/traffic/stream` and `/v1/vault/sessions` run the same route code in
both modes, and in hosted mode the middleware swaps in the signed-in owner's own observability
and vault directory (`request.state.hosted_runtime`). Projects are one store keyed by owner
(`local-owner` locally, the Google principal when hosted).

Two console APIs stayed local-only. `GET /v1/status` (Overview, Policy, engine mode) reported
operator internals a hosted owner must not see: the upstream origin, the image pipeline, the
server-wide traffic-log level and whether a server token is set. Its `gateway.url` was the
request's base URL, which behind the hosted router is an internal host, not the public origin.
`GET /v1/connect/snippets` (Connect) built `/s/<session>/v1` blocks against the operator's
upstream, while hosted clients call `/e/<endpoint>/v1` with an endpoint key. The UI also had
no way to ask which sections a server offers without knowing the build or the mode.

Writing a hosted copy of each route would fork the console: two handlers drift, and each fix
lands twice or once.

## Decision

**One route implementation per API.** A difference between local and hosted mode is either a
*projection* (which fields an owner may see) or a *scope* (whose runtime and whose projects),
never a second handler. A projection is an explicit allow-list of fields next to the route, so
a new field is hidden from hosted owners until someone decides otherwise. Hosted-only
behaviour that is not a projection (identity, admission, quotas, runtimes) stays in
`pii_guard.hosted`.

**Server-declared capabilities.** `GET /v1/status` returns `capabilities` in both modes: a
flat object of booleans (`text`, `chat`, `images`, `logs`, `vault`, `server_policy`,
`projects`, `connect`, `evaluation`, `accounts`) computed from settings and mode. It is the
UI's only source for which sections to show; the UI does not branch on the mode or the build.
`logs` and `vault` come from the caller's own view (the server-wide setting locally, the
owner's runtime when hosted), so the same expression serves both modes.

| Capability | Local | Hosted |
|---|---|---|
| `text`, `chat`, `projects`, `connect`, `evaluation` | `true` | `true` |
| `images` | `true` | `true` ([ADR 0014](0014-hosted-local-images.md)): while `PII_GUARD_HOSTED_IMAGES` is on and no masked visual type needs SAM |
| `logs`, `vault` | the server's settings | the owner's runtime (`true`) |
| `server_policy` | `true` | `false` |
| `accounts` | `false` | `true` |

**Hosted projection of `/v1/status`.** Hosted owners see the version, the gateway's default
mode and URL, the fast mode only (audit detection is not offered hosted), NER availability and
state, the default policies, the default language, their own traffic-log and vault views and
the capabilities. Upstream, image internals, `auth` and the server-wide log level are dropped.
`gateway.url` comes from `HOSTED_PUBLIC_ORIGIN`, never from the request's `Host`.

**Owner-scoped Connect.** `GET /v1/connect/snippets?endpoint=<id>` builds the same tool blocks
from `pii_guard.integrations.snippets` for one of the caller's endpoints:
`<gateway origin>/e/<endpoint>/v1`, the endpoint's model, and the key as
`$PII_GUARD_ENDPOINT_KEY`. The endpoint must belong to the caller (the Google principal hosted,
`local-owner` locally, behind the same trusted-local rule as project management); an unknown
or foreign id gets the same 404. No upstream origin is shown. Hosted mode requires `endpoint`;
local calls without it are unchanged.

**Who may call.** Hosted, both routes need a signed-in Google principal. Guests get 401, and
guard API keys and endpoint keys are refused: keys are for the gateway and REST, not for
reading the console.

## Consequences

A console feature that needs a new hosted surface adds a projection or a scope to the existing
route and a line to the hosted allow-list, not a new handler. The UI reads `capabilities` and
stays one build. A new `/v1/status` field is local-only until it is added to the hosted
projection, which keeps operator details from leaking by default but means a hosted section can
miss a field until someone adds it. Capabilities describe what the server offers, not the
caller's quota: reads still pass hosted admission like any other request, and their accounting
is decided separately.

See [contracts](../contracts.md#get-v1status) and [hosted operations](../hosted.md).
