# API guide

PII Guard speaks the OpenAI API. Point an OpenAI SDK at the guard instead of the provider: it
masks personal data in the request, sends only placeholders upstream, and restores them in the
answer, streamed or not. Native routes mask, analyze and restore text without a model.

- **Reference:** [guard.watt-mind.com/#api](https://guard.watt-mind.com/#api), rendered from
  [openapi.json](openapi.json). Read-only: it sends no requests.
- **Contract:** field-level behavior, limits and every error are in
  [contracts.md](contracts.md#rest-api-implemented). This guide doesn't repeat them.
- **Clients:** ready-made setups for Codex, pi, OpenCode and Muse Code are in
  [integrations/](integrations/README.md); runnable examples in [integrations.md](integrations.md).

Every example here is fictional (Teszt Elek, `example.com`).

## Quickstart

Pick the base URL and the credential that go with it:

| Where the guard runs | Base URL | Credential |
|---|---|---|
| Self-hosted (`pii-guard serve`) | `http://127.0.0.1:8787/v1` | The server's `PII_GUARD_API_TOKEN`, if set |
| Hosted project endpoint | `https://guard.watt-mind.com/e/<endpoint-id>/v1` (copy it from **Connect**) | The endpoint key (`pg_ep_...`) |
| Self-hosted project endpoint | `http://127.0.0.1:8787/e/<endpoint-id>/v1` | The endpoint key |

The base URL ends in `/v1`: the SDK appends `/chat/completions`. Keep the credential in the
environment, never in code:

```bash
export GUARD_BASE_URL='https://guard.watt-mind.com/e/your-endpoint-id/v1'
export GUARD_MODEL='your-model'
read -r -s GUARD_API_KEY && export GUARD_API_KEY   # no echo, not in shell history
```

### curl

```bash
curl -sS "$GUARD_BASE_URL/chat/completions" \
  -H "Authorization: Bearer $GUARD_API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"model": "'"$GUARD_MODEL"'", "messages": [{"role": "user",
       "content": "Write a short reply to Teszt Elek (teszt.elek@example.com) confirming Tuesday."}]}'
```

The upstream receives `[[PERSON_...]] ([[EMAIL_...]])`; you get the answer with the name and
address back in place. The response headers say what happened: `X-PII-Guard-Masked`
(counts by type, never values), `X-PII-Guard-Session` and `X-PII-Guard-Outbound-Check`.

### Python

```python
import os
from openai import OpenAI

client = OpenAI(
    base_url=os.environ["GUARD_BASE_URL"], api_key=os.environ["GUARD_API_KEY"], max_retries=0
)
reply = client.chat.completions.create(
    model=os.environ["GUARD_MODEL"],
    messages=[
        {
            "role": "user",
            "content": "Write a short reply to Teszt Elek "
            "(teszt.elek@example.com) confirming Tuesday.",
        }
    ],
)
print(reply.choices[0].message.content)
```

### JavaScript

```js
import OpenAI from "openai";

const client = new OpenAI({ baseURL: process.env.GUARD_BASE_URL, apiKey: process.env.GUARD_API_KEY, maxRetries: 0 });
const stream = await client.chat.completions.create({
  model: process.env.GUARD_MODEL,
  messages: [{ role: "user", content: "Write a short reply to Teszt Elek (teszt.elek@example.com) confirming Tuesday." }],
  stream: true,
});
for await (const chunk of stream) process.stdout.write(chunk.choices[0]?.delta?.content ?? "");
```

`max_retries=0` / `maxRetries: 0`: a refusal is not transient, and a retried request can repeat
provider spend. `/v1/responses` and `/v1/models` work the same way; Responses needs an
upstream with a native `/responses` route (else `501 responses_unsupported`).

## Authentication

There are two kinds of credential, and neither is ever a provider key. Send either as
`Authorization: Bearer <credential>`.

| | API token | Endpoint key |
|---|---|---|
| What it is | Self-hosted: the server's `PII_GUARD_API_TOKEN`. Hosted: a guard API key (`pg_...`, 24 hours, at most five) from the console | `pg_ep_...`, issued per project endpoint, shown once |
| Where it works | The root gateway and the native text routes. Also accepted as `X-PII-Guard-Token` | Only its own `/e/<endpoint-id>/v1/chat/completions`, `/responses` and `/models`, and its Muse Code catalog (`/e/<endpoint-id>/muse-code/models`, also at the root `/muse-code/models`, where Muse reads it) |
| What it picks | Self-hosted: the server's upstream. Hosted: the sponsored model, or a saved provider connection (`X-PII-Guard-Connection`) | Everything is pinned by the endpoint: provider, model (unless pass-through), policy version, language, mode |
| Can't | Hosted: manage keys or connections (that needs the signed-in Google session) | Manage projects, inspect the vault, call native routes or another endpoint |

A self-hosted server without `PII_GUARD_API_TOKEN` has no authentication: keep it on loopback.
Endpoint keys are managed with the [endpoint key routes](https://guard.watt-mind.com/#api)
(`/v1/projects/{project_id}/endpoints/{endpoint_id}/keys`) by the project owner; revoking one
refuses its next request. Details: [projects.md](projects.md) and
[contracts.md](contracts.md#account-and-credentials).

## Sessions and restore

A vault session holds the mapping from placeholders back to the original values, in process
memory with a sliding TTL (one hour by default). Within a session the same value always gets
the same placeholder, so a conversation stays coherent across calls.

**Gateway.** You don't have to manage sessions: each call picks one, in this order, and
returns it in `X-PII-Guard-Session` with `X-PII-Guard-Session-Source`:

1. `X-PII-Guard-Session: <id>` you send (unknown or expired: `404 not_found`);
2. the id in a `/s/<id>/v1/...` base URL (self-hosted root gateway; created if missing);
3. the request's `prompt_cache_key`;
4. a default session per credential.

An explicit session (1 or 2) belongs to the credential that first used it, and is never
rotated: when it holds `PII_GUARD_VAULT_MAX_ENTRIES` placeholders the next call gets
`409 session_entry_limit_reached`, and you start a new session. The guard restores the
placeholders in the answer itself, also across streamed chunks; never restore them in the
client. Full rules: [gateway sessions](contracts.md#gateway-sessions-implemented).

**Native routes.** Mask, then restore with the session id `/v1/mask` returns:

```bash
curl -sS http://127.0.0.1:8787/v1/mask -H 'Content-Type: application/json' \
  -d '{"text": "Teszt Elek írt Teszt Eleknek.", "language": "hu"}'
# {"masked_text": "[[PERSON_7f3a]] írt [[PERSON_7f3a]]nek.", "session_id": "s_...", ...}

curl -sS http://127.0.0.1:8787/v1/unmask -H 'Content-Type: application/json' \
  -d '{"text": "Kedves [[PERSON_7f3a]]!", "session_id": "s_..."}'
# {"text": "Kedves Teszt Elek!", "unresolved": []}
```

`unresolved` lists placeholder-shaped tokens the session never issued (made up by a model);
they stay as they are. `/v1/analyze` returns the spans it would mask, without masking.

**Known values.** When the application already knows what is sensitive (a customer record),
create the session with them, then send its id as `X-PII-Guard-Session` or `session_id`; every
occurrence is masked, inflected forms included:

```bash
curl -sS http://127.0.0.1:8787/v1/sessions -H 'Content-Type: application/json' \
  -d '{"known_values": [{"value": "Gyakorló Tihamér", "entity_type": "PERSON"}]}'
# 201 {"session_id": "s_...", "added": 1, "total": 1}
```

## Errors

Every error has the same body, and the message never contains request text, values, keys or
session ids:

```json
{"error": {"code": "session_entry_limit_reached", "message": "..."}}
```

The guard fails closed: on any error nothing was sent upstream and no partially masked text
comes back. Don't work around a refusal by calling the provider directly. A `200` stream can
still end with an `error` event; a complete one ends with `data: [DONE]`.

The table below is generated from the code by `scripts/export_openapi.py` (statuses come from
the exceptions that carry each code) and checked in CI. The hosted service adds its admission
codes (`429 quota_exceeded`, `abuse_throttled`, `sign_in_required`, `hosted_capacity`;
`503 sponsored_unavailable`): see [admission, cost and egress](contracts.md#admission-cost-and-egress).

<!-- BEGIN error-codes: generated by scripts/export_openapi.py, do not edit -->
| Status | `code` | When | Routes |
|---|---|---|---|
| 400 | `unsupported_content` | The body holds a field or content part the gateway can't mask yet (allow-list); nothing is forwarded. | `chat/completions`, `responses` |
| 401 | `unauthorized` | `PII_GUARD_API_TOKEN` is set and the request has no valid token. | every route |
| 403 | `project_access_denied` | Project owner authorization or selection is denied. | endpoint keys |
| 403 | `traffic_log_not_local` | `PII_GUARD_TRAFFIC_LOG=full` and the connection is not loopback on both ends. | every route |
| 404 | `not_found` | Unknown route, or an unknown or expired `session_id`. | `analyze`, `chat/completions`, `mask`, `responses`, `sessions`, `unmask` |
| 404 | `project_not_found` | The project resource is unknown or belongs to another owner. | endpoint keys |
| 409 | `session_entry_limit_reached` | An explicit session already holds `PII_GUARD_VAULT_MAX_ENTRIES` placeholders; it is never rotated, so start a new session. | `chat/completions`, `responses` |
| 413 | `payload_too_large` | The body, text or image is larger than the configured limit. | `analyze`, `chat/completions`, `mask`, `responses`, `sessions`, `unmask`, endpoint keys |
| 413 | `unmask_output_too_large` | Restoring would output more than `PII_GUARD_UNMASK_MAX_RESTORED_CHARS` characters of original values (one `/v1/unmask` text, or one gateway response). | `chat/completions`, `responses`, `unmask` |
| 422 | `blocked_entity` | An entity type whose policy is `block` was found; nothing is masked or stored. | `chat/completions`, `mask`, `responses` |
| 422 | `invalid_known_value` | A pre-loaded known value is too short, too long, or has an unknown or visual type. | `sessions` |
| 422 | `invalid_project_config` | A policy or endpoint configuration is invalid. | endpoint keys |
| 422 | `invalid_request` | The request fails validation. The message lists field locations only, never values. | `analyze`, `mask`, `sessions`, `unmask`, endpoint keys |
| 422 | `outbound_check_failed` | After masking, the request still held a value its session knows; nothing was sent. | `chat/completions`, `responses` |
| 422 | `placeholder_in_input` | The text to mask contains a placeholder this session already issued. | `chat/completions`, `mask`, `responses` |
| 422 | `too_many_known_values` | The session would hold more than `PII_GUARD_KNOWN_VALUES_MAX` known values. | `sessions` |
| 422 | `upstream_destination_not_allowed` | Hosted upstream destinations must use public HTTPS on port 443. | endpoint keys |
| 500 | `internal_error` | Anything unexpected. No exception text is returned. | every route |
| 500 | `masking_failed` | Masking or re-identification could not complete. | `mask`, `unmask` |
| 500 | `vault_not_configured` | `PII_GUARD_TENANT_KEY` is unset, not hex or shorter than 16 bytes. | `analyze`, `chat/completions`, `mask`, `responses`, `sessions`, `unmask` |
| 501 | `responses_unsupported` | The upstream has no Responses API (it answered 404 or 405). | `responses` |
| 502 | `upstream_credential_rejected` | The provider refused the API key while listing its models (HTTP 401/403). | endpoint keys |
| 502 | `upstream_did_not_stream` | `stream: true`, but the upstream answered without an event stream; retry without `stream`. | `chat/completions` |
| 502 | `upstream_unavailable` | The upstream could not be reached or answered with something unusable. | `chat/completions`, `models`, `responses` |
| 503 | `detection_failed` | A detector (or SAM, or OCR) failed or timed out. | `analyze`, `chat/completions`, `mask`, `responses` |
| 503 | `detection_profile_denied` | The selected or cached processing component is not permitted by the detection profile. | `analyze`, `chat/completions`, `mask`, `responses` |
| 503 | `detection_unavailable` | A configured detector can't run safely (the LLM detector without a key). | `analyze`, `chat/completions`, `mask`, `responses` |
| 503 | `detector_loading` | The NER model is still loading after `PII_GUARD_NER_WARMUP_TIMEOUT`; retry after `Retry-After` seconds. | `analyze`, `chat/completions`, `mask`, `responses` |
| 503 | `project_storage_unavailable` | The project configuration store is unavailable. | endpoint keys |
| 503 | `upstream_not_configured` | The server has no upstream (`PII_GUARD_UPSTREAM_BASE_URL`). | `chat/completions`, `models`, `responses` |
| 503 | `vault_capacity_exhausted` | A new session is needed while every vault slot is held by an active request; retry. | `chat/completions`, `responses` |
<!-- END error-codes -->

## Keeping the reference current

`docs/openapi.json` is generated from the FastAPI app and filtered to the routes above:
internal, admin and hosted-only routes (status, traffic, vault inspector, projects and
policies, account, demo) are left out. After changing a public route, model or error code:

```bash
uv run python scripts/export_openapi.py   # or: make openapi
```

`tests/test_openapi_export.py` fails while the committed files differ from the code. The
hosted service keeps the runtime `/docs`, `/redoc` and `/openapi.json` off; the console's
`#api` page renders the committed file, bundled with the UI.
