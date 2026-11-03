# Using the gateway

> [!NOTE]
> **Related guides:** For the REST & OpenAI-compatible route reference, authentication tokens,
> and error code table, see [api.md](api.md) (and [openapi.json](openapi.json)). For runnable
> client examples and coding agent setups (Claude Code, Codex, OpenCode, `pi`, Muse Code), see
> [integrations.md](integrations.md) and [integrations/README.md](integrations/README.md).

PII Guard's gateway is a drop-in for any OpenAI-compatible client: point the client at
PII Guard instead of the provider. Every message is masked when it arrives, the masked request
is forwarded, and the answer (streamed or not) comes back with the real values restored. How it
is built: [architecture.md](architecture.md#gateway-the-proxy). Running and exposing it:
[operations.md](operations.md).

The detection cache stores only results from complete request detection. A model answer's
restored placeholders are not a complete PII scan: previously unseen answer text is detected
when a later request sends it as history, regardless of its role. Existing request history
still benefits from cached detections. Responses never populate the detection cache
speculatively (LAB-1756).

## Modes

| Mode | Detection | Model call per message | Use it for |
|---|---|---|---|
| `fast` (default) | rules + the in-process NER (rules only without a checkpoint) | none: local, nothing leaves the machine | production: the request path |
| `escalate` (opt-in) | fast, then the LLM detector on fast mode's uncertain spans only, as masked windows | none when nothing is uncertain, else one per uncertain text, carrying about ±200 characters of context per uncertain place ([measured](#escalate-mode)) | trying an LLM second look on production-like traffic at a fraction of audit's cost and exposure |
| `audit` | rules + NER + an LLM detector | one, to the detector endpoint (about 2 s, $2.5–3 per 1k messages) | a second opinion: sampled or offline quality checks, label generation, the benchmark upper bound |

Fast mode is the default (`PII_GUARD_GATEWAY_MODE`, code default `fast`); opt into escalate or
audit per request with `X-PII-Guard-Mode: escalate` / `audit`, or for the whole server with
`PII_GUARD_GATEWAY_MODE`. Audit mode is not meant for production traffic: it sends every
message to the detector endpoint. Current numbers for both:
[benchmarks.md](benchmarks.md#smoke). Old mode names and the rename:
[operations.md](operations.md#modes).

## Escalate mode

`X-PII-Guard-Mode: escalate` (LAB-1766, `src/pii_guard/detect/escalate.py`) runs the fast
pipeline unchanged, then asks Muse Spark Open (the audit-mode detector, same key and settings)
about only what fast mode was unsure of:

1. **Select.** NER spans scored under `PII_GUARD_GATEWAY_ESCALATE_LOW_SCORE` (0.75); a
   capitalised word no detector covered, right after a form of address (`Mr`, `Frau`,
   `Kedves`; before Hungarian `úr`) or next to a `PERSON` span; a run of six or more digits no
   rule matched (dates and amounts with a currency left out); a rules-vs-NER type conflict
   where the rules span is not checksum- or format-validated. No candidate, no call: the
   result is fast mode's.
2. **Window.** About `PII_GUARD_GATEWAY_ESCALATE_WINDOW` (200) characters each side of a
   candidate, snapped to whitespace and never cutting a found span, at most
   `_ESCALATE_MAX_WINDOWS` (4) per text and `_ESCALATE_MAX_TEXTS` (8) texts per request. Every
   span fast mode found is replaced by a placeholder (`[[EMAIL_1]]`; a conflicting span by a
   neutral `[[ENTITY_1]]`), so no value already found leaves the machine. The windows of one
   text go out as one call.
3. **Align, verbatim only.** A value the model returns is kept only where it occurs exactly in
   the windows, not across two windows and not halfway into a placeholder. A value that
   includes a placeholder (`Jane [[PERSON_1]]`) maps onto the original text under it, so the
   model can widen a span or settle its type.
4. **Merge, add-only.** The model's spans join fast mode's in the resolver with the LLM as type
   adjudicator, as in audit mode. A losing span keeps its characters masked, and validated
   rules spans keep winning: the model can add or retype, never unmask.

**Failing closed.** A call past `PII_GUARD_GATEWAY_ESCALATE_TIMEOUT` (10 s) or any error masks
the uncertain words that were still unmasked (names as `PERSON`, numbers as `ID_DOCUMENT`) and
the request goes on; `PII_GUARD_GATEWAY_ESCALATE_ON_FAILURE=keep` keeps the rules + NER result
instead. Either way `X-PII-Guard-Escalation-Failures` counts it. Without a key escalate mode is
unavailable (`503 detection_unavailable`, nothing sent), the `local-only` profile refuses it
(`detection_profile_denied`), and the hosted service accepts fast mode only.

**Cache and counts.** Decisions are cached in memory per vault session (and session
incarnation), keyed by a hash of the masked windows: the same uncertain text in the same
session is not sent twice, and, as in every mode, a text already detected in the session comes
from the detection cache. `X-PII-Guard-Escalations` and the traffic record's
`audit_escalations` give the texts sent per request; the console's call detail shows it.

**What leaves the machine:** the uncertain words and the unmasked context around them, to the
LLM endpoint. Values the session knows ([known values](api.md#sessions-and-restore)) are added
after detection, so a known value fast mode did not find can be in a window.

**Measured** on 706 fictional documents
([results](../eval/results/2026-11-01-lab-1766-escalate/README.md)): 30–46 % of documents had an
uncertain place; $0.57–0.89 per 1,000 messages (audit: about $2.5); about 1.4 s added at p50
on an escalated message, 2.9 s at p95. Leak went from 3 to 2 values of 583 on the hand-written
set and did not change on Ai4Privacy (8 of 2,185); over-masking rose by one span on the
hand-written set. That is within noise: escalate stays opt-in and fast mode stays the default.

## Run it

Fast mode needs no model key. The NER checkpoint is optional: without one, fast mode is rules
only ([models.md](models.md#ner-detector)).

```bash
uv sync
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
| `X-PII-Guard-Mode` | both | Request: `fast` (rules + NER, no model call; the default), `escalate` (+ the LLM detector on uncertain spans only, as masked windows) or `audit` (+ the LLM detector on every message). The response carries the mode that ran. |
| `X-PII-Guard-Escalations` / `X-PII-Guard-Escalation-Failures` | response | Escalate mode only: texts sent to the LLM detector as masked windows in this request, and the calls of those that timed out or failed (and were masked closed; sent only when non-zero). Also in the traffic record (`audit_escalations`). |
| `X-PII-Guard-Language` | request | Language of the conversation (default `PII_GUARD_DEFAULT_LANGUAGE`, `hu`). |
| `X-PII-Guard-Echo` | request | Opt-in, `masked`: also return what the model saw and said. Non-streamed: a `pii_guard` object (`masked_messages`, `masked_answer`) in the body. Streamed: a `pii_guard.masked_request` event first and a `pii_guard.masked_answer` event before `[DONE]` (a choice whose masked copy passed the 1M-character retention cap is listed as `{"index": i, "content": null, "truncated": true}`, not left out). Both also carry `kept_spans`: per client message, the values detected but kept by policy as `{"type", "start", "end"}` (code-point offsets into the message as sent; `[]` for a message whose content is not one string or is decoded structured tool output), never the values. Decoded JSON offsets cannot be projected onto the original escaped text. Masked text only; for UIs that show the boundary (the demo's Chat screen). `placeholder_note` says whether the [placeholder note](#placeholder-note) was added. |
| `X-PII-Guard-Cache-Hits` / `-Misses`, `X-PII-Guard-Masked`, `X-PII-Guard-Unresolved` | response | Counts only: texts served from the detection cache, values masked, placeholders the model invented. |
| `X-PII-Guard-Placeholder-Note` | response | `added` when the [placeholder note](#placeholder-note) went upstream with the request. |
| `X-PII-Guard-Opaque-Reasoning-Stripped` | response | How many reasoning items/blocks were removed because their opaque blob (signature, `redacted_thinking` data, `encrypted_content`) was not issued upstream in this vault session; absent when none ([contracts](contracts.md#gateway-request-fields-implemented)). |
| `X-PII-Guard-Outbound-Check` | response | `passed` when the [outbound re-check](#outbound-re-check) found no value the session knows in the masked request; `blocked` on the `422 outbound_check_failed` refusal. Also in the traffic record (`outbound_check`). |
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

## Outbound re-check

After masking, and before anything goes upstream, the gateway reads the masked request once
more with the same request walker and searches every text in it for the values its vault
session holds (LAB-1500, `pii_guard.gateway.outbound`): messages of every role, tool
definitions, tool-call arguments, tool results, reasoning text, metadata, and the transcript
and summary sent after a masked image, in Chat Completions and the Responses API, streamed or
not. The values are those detected in this request and in earlier ones on the session, and
the operator's pre-loaded known values. They are matched with the vault's own occurrence
patterns: case, whitespace, Unicode form, `ß`/`ss` and the language's inflection, so
`TESZT ELEK-nek` is found for `Teszt Elek`. Placeholders never count. A text with a
backslash is also searched with its JSON escapes decoded (`\u00f3`, surrogate pairs, `\"`,
`\n` ..., nested levels too), so a value JSON-escaped in a tool output that is not decodable
JSON (`Result: {...}`, trailing notes, plain text) is found as the upstream would read it
(LAB-1755). Ordinary backslashes (Windows paths, regexes) reveal no value and pass.

A value found there refuses the request: `422 outbound_check_failed`, the message lists entity
types and counts only, `X-PII-Guard-Outbound-Check: blocked`, and nothing is sent. Since the
upstream call is never made, a streamed request gets a JSON error, not a stream. A request
created by the refused call drops its session, as any refused call does. A request that passes
carries `X-PII-Guard-Outbound-Check: passed`.

**Short values.** Every value the session holds is searched for, but only one that can't be a
common short token blocks:

| Value | Blocks from |
|---|---|
| pre-loaded (`known`) | always (they are at least 3 characters by their own rule) |
| a number (no letter) | 6 digits: the gateway's bare-number threshold (LAB-1348) |
| found only by the NER | 4 letters and digits: the NER reads short words (`pi`, `len`, `89`) as names |
| found by the rules or the LLM | 3 letters and digits |

A shorter occurrence is counted (`outbound_check.short` in the traffic record) and lets the
request through: the sweep already masks every occurrence of every value, so a short one left
over is one the sweep meant to leave alone, and refusing on it would refuse requests over the
guard's own noise. The exemptions masking makes on purpose apply too: an NER-only value where
the text's structure rules it out (a product name, a path, a code identifier, LAB-1470/1482),
an id the upstream issued in the session (LAB-1469), and a declared tool name in an identifier
(LAB-1324). A tool name that is also a pre-loaded known value still blocks.

Cost: one fold per text (texts masking left unchanged come from the session's memo) and one
substring search per session value over all texts; a value is matched text by text only when
it can occur. On the latency corpus it adds well under the 2 ms budget
([LAB-1500 results](../eval/results/2026-10-29-lab-1500-outbound-check/README.md)).

## Failing closed

A detection error or timeout (`PII_GUARD_GATEWAY_DETECTION_TIMEOUT`, 30 s), a request field
or content part it can't mask (remote image URLs, audio, files, unknown keys), or a missing
tenant key or upstream return an error and nothing is forwarded. So does a masked request that
still holds a value the session knows ([outbound re-check](#outbound-re-check)). Inline images are masked with
SAM 3.1 and OCR, and refused when those aren't available. The full field table is in
[contracts.md](contracts.md). Further
settings (`PII_GUARD_GATEWAY_MODE`, `_UPSTREAM_TIMEOUT`, `_CACHE_SIZE`, `_CONCURRENCY`,
`_KEEP_TYPES`, `_PLACEHOLDER_NOTE`) are documented in `src/pii_guard/gateway/config.py`. Without
`PII_GUARD_UPSTREAM_API_KEY`, the client's own `Authorization` header is forwarded.
