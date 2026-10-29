# Using the gateway

PII Guard's gateway is a drop-in for any OpenAI-compatible client: point the client at
PII Guard instead of the provider. Every message is masked when it arrives, the masked request
is forwarded, and the answer (streamed or not) comes back with the real values restored. How it
is built: [architecture.md](architecture.md#gateway-the-proxy). Running and exposing it:
[operations.md](operations.md).

## Modes

| Mode | Detection | Model call per message | Use it for |
|---|---|---|---|
| `fast` (default) | rules + the in-process NER (rules only without a checkpoint) | none: local, nothing leaves the machine | production: the request path |
| `audit` | rules + NER + an LLM detector | one, to the detector endpoint (about 2 s, $2.5–3 per 1k messages) | a second opinion: sampled or offline quality checks, label generation, the benchmark upper bound |

Fast mode is the default (`PII_GUARD_GATEWAY_MODE`, code default `fast`); opt into audit per
request with `X-PII-Guard-Mode: audit`, or for the whole server with
`PII_GUARD_GATEWAY_MODE=audit`. Audit mode is not meant for production traffic: it sends every
message to the detector endpoint. Current numbers for both:
[benchmarks.md](benchmarks.md#smoke). Old mode names and the rename:
[operations.md](operations.md#modes).

## Run it

Fast mode needs no model key. The NER checkpoint is optional: without one, fast mode is rules
only ([models.md](models.md#ner-detector)).

```bash
uv sync --extra ner
export PII_GUARD_TENANT_KEY=$(openssl rand -hex 32)
export PII_GUARD_NER_MODEL=/path/to/your/ner-checkpoint      # optional
export PII_GUARD_UPSTREAM_BASE_URL=https://api.meta.ai/v1     # any OpenAI-compatible API
export PII_GUARD_UPSTREAM_API_KEY=$META_API_KEY
uv run pii-guard serve                                         # http://127.0.0.1:8787
```

Audit mode adds the LLM detector. The default endpoint and model are Muse Spark Open on
Baseten Model APIs (`https://inference.baseten.co/v1`, `meta-models/muse-spark-open-1026`), so
only the key and the reasoning effort are needed:

```bash
export PII_GUARD_LLM_DETECTOR_API_KEY=$BASETEN_API_KEY
export PII_GUARD_LLM_DETECTOR_REASONING_EFFORT=low     # required: see docs/models.md
```

Muse Spark 1.3 on the Meta Model API works the same way (fictional text only): set
`PII_GUARD_LLM_DETECTOR_URL=https://api.meta.ai/v1`, `PII_GUARD_LLM_DETECTOR_MODEL=muse-spark-1.3`
and `PII_GUARD_LLM_DETECTOR_REASONING_EFFORT=minimal`. Which endpoint may see real data:
[models.md](models.md#baseten-model-apis-the-audit-mode-detector).

## From Python

```python
from openai import OpenAI

client = OpenAI(base_url="http://127.0.0.1:8787/v1", api_key="unused")
messages = [
    {
        "role": "system",
        "content": "Values like [[PERSON_1a2b3c]] are the user's real data, "
        "masked for privacy. Use them verbatim.",
    },
    {
        "role": "user",
        "content": "I'm Jane Placeholder, jane.placeholder@example.net. "
        "Write one sentence inviting Teszt Elek to lunch.",
    },
]
raw = client.chat.completions.with_raw_response.create(model="muse-spark-1.3", messages=messages)
print(raw.parse().choices[0].message.content)  # real names; the model only saw placeholders
session = raw.headers["X-PII-Guard-Session"]  # send it back on the next turn

stream = client.chat.completions.create(
    model="muse-spark-1.3",
    stream=True,
    messages=[
        *messages,
        {"role": "assistant", "content": raw.parse().choices[0].message.content},
        {"role": "user", "content": "Now mention Minta Mária too."},
    ],
    extra_headers={"X-PII-Guard-Session": session},
)
for chunk in stream:
    if chunk.choices:
        print(chunk.choices[0].delta.content or "", end="")
```

## Headers

| Header | Direction | Meaning |
|---|---|---|
| `X-PII-Guard-Session` | both | The conversation. Same session = same placeholders, and history is not detected again. Unknown or expired → 404. Without it the gateway picks a sticky session (below); the response carries its id, so a client can send it back. |
| `X-PII-Guard-Session-Source` | response | Which step chose the session: `header`, `path`, `prompt_cache_key` or `default`. Also in the traffic record (`session_source`). |
| `X-PII-Guard-Mode` | both | Request: `fast` (rules + NER, no model call; the default) or `audit` (+ the LLM detector). The response carries the mode that ran. |
| `X-PII-Guard-Language` | request | Language of the conversation (default `PII_GUARD_DEFAULT_LANGUAGE`, `hu`). |
| `X-PII-Guard-Echo` | request | Opt-in, `masked`: also return what the model saw and said. Non-streamed: a `pii_guard` object (`masked_messages`, `masked_answer`) in the body. Streamed: a `pii_guard.masked_request` event first and a `pii_guard.masked_answer` event before `[DONE]`. Masked text only; for UIs that show the boundary (the demo's Chat screen). `placeholder_note` says whether the [placeholder note](#placeholder-note) was added. |
| `X-PII-Guard-Cache-Hits` / `-Misses`, `X-PII-Guard-Masked`, `X-PII-Guard-Unresolved` | response | Counts only: texts served from the detection cache, values masked, placeholders the model invented. |
| `X-PII-Guard-Placeholder-Note` | response | `added` when the [placeholder note](#placeholder-note) went upstream with the request. |
| `X-PII-Guard-Request-Id` | response | The call's id in the traffic log; with `PII_GUARD_SERVER_TIMING=true` a `Server-Timing` header gives the per-stage latency ([operations.md](operations.md#timing)). |

## Sessions

Placeholders are stable within one vault session, so every request lands in one, even from a
client that can't send headers (LAB-1286). The first match wins:

1. **`header`**: `X-PII-Guard-Session`. Unknown or expired → `404 session_not_found`: the
   mapping is gone, and a silent new session would give the same value another placeholder.
2. **`path`**: a base URL `http://127.0.0.1:8787/s/<session>/v1` (also
   `/s/<session>/muse-code/...`) reaches the same routes with that session. Same id grammar as
   the header (1-128 of `A-Z a-z 0-9 _ -`, else 400); created on first use, never 404.
   `pii-guard connect` writes such a URL with a random id.
3. **`prompt_cache_key`**: the body's `prompt_cache_key` selects the session
   `HMAC(tenant key, "pck:" + client identity + ":" + key)`. Created on first use. Muse Code's
   reminder observers are grouped with their main conversation (below).
4. **`default`**: one session per client, `HMAC(tenant key, "default:" + client identity)`.

The client identity is the SHA-256 of the request's `Authorization` value (`anonymous`
without one), so two keys never share a derived session; every derived id is keyed with the
tenant key, so ids differ across deployments. Derived ids (`d_` + 32 hex) leave the process
only in the `X-PII-Guard-Session` response header. With `PII_GUARD_API_TOKEN` sent as
`Authorization: Bearer`, the token is removed before the gateway sees it, so those clients
share the `anonymous` default session; send the token as `X-PII-Guard-Token` to keep a
per-key default.

Steps 2-4 use the session TTL like any other and have a size cap,
`PII_GUARD_VAULT_MAX_ENTRIES` (10 000 placeholders). A full session is not cut off or
pruned: the next request starts a new **generation** under a new derived id (logged once),
the full one is left to expire. The client re-sends its history, which is masked again in the
new generation; only a placeholder the model kept from before the rotation, for a value no
longer in the request, stays unrestored (`X-PII-Guard-Unresolved`).

Muse Code's `prompt_cache_key` differs between its main conversation
(`tbh:main:<conversation uuid>`) and each reminder observer
(`tbh:<kind>-reminder:<first 8 hex of the uuid>:...`). Per key, one task would span four
sessions and a value would get a placeholder in each (LAB-1300). So the gateway remembers each
main key's session under its 8-hex prefix and client identity (in memory, the newest 4 096
conversations), and an observer key with that prefix and identity uses that session. The
prefix is a UUIDv7 timestamp (about 65 s), so when one client starts two Muse conversations in
the same window, their observers follow the newer one; the main conversations keep their own
sessions, and nothing is ever shared across client identities. Muse sends its first main turn
and its first observer at the same time, so the observer can reach the gateway first: its
session then waits under the prefix, and the first main key with that prefix and identity
takes it over instead of starting a second one (LAB-1341). The path URL that `connect` writes
needs none of this.

## Placeholder note

When the masked request holds at least one placeholder this session issued, the gateway puts
one constant system note in front of the conversation (Chat Completions: a first `system`
message; Responses: the start of `instructions`). It says placeholders are opaque reference
tokens, not real data, to be copied exactly as written, and that they are restored after the
answer. Without it, `muse-spark-1.3` declined 5 of 15 synthetic agent turns over the label
inside a placeholder (`[[NATIONAL_ID_HU_TAJ_…]]`: "a sensitive health-insurance identifier");
with it, 0 of 15 ([LAB-1471](../eval/results/2026-10-29-lab-1471-placeholder-refusals/README.md)).

The note is the same text for every request: no value, no placeholder, nothing from the
request. It is added after masking and isn't scanned, it holds no placeholder-shaped token,
and the echo (`X-PII-Guard-Echo: masked`) reports it as `placeholder_note: true` next to the
client's masked messages rather than as one of them. Placeholders keep their type label
([ADR 0007](decisions/0007-keyed-pseudonyms.md#addendum-2026-10-29-the-placeholder-note-lab-1471)).
`PII_GUARD_GATEWAY_PLACEHOLDER_NOTE=false` turns it off.

## Failing closed

A detection error or timeout (`PII_GUARD_GATEWAY_DETECTION_TIMEOUT`, 30 s), a request field
or content part it can't mask (remote image URLs, audio, files, unknown keys), or a missing
tenant key or upstream return an error and nothing is forwarded. Inline images are masked with
SAM 3.1 and OCR, and refused when those aren't available. The full field table is in
[contracts.md](contracts.md). Further
settings (`PII_GUARD_GATEWAY_MODE`, `_UPSTREAM_TIMEOUT`, `_CACHE_SIZE`, `_CONCURRENCY`,
`_KEEP_TYPES`, `_PLACEHOLDER_NOTE`) are documented in `src/pii_guard/gateway/config.py`. Without
`PII_GUARD_UPSTREAM_API_KEY`, the client's own `Authorization` header is forwarded.
