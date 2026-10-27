# Muse Code behind pii-guard

[Muse Code](https://dev.meta.ai) is Meta's terminal coding agent. With pii-guard in between,
Muse reads your files, runs tools and writes code as usual. The model only ever sees
placeholders, and Muse's tool calls come back with the real values, so the files it writes are
correct.

Muse speaks the **OpenAI Responses API**, not Chat Completions. The gateway serves it natively
(`POST /v1/responses` and the `GET /muse-code/models` catalog). Nothing is translated, and
there is no proxy or MITM.

Tested with Muse Code **1.4.14** (`1.4.14-R7309.1`): end to end against a scripted mock model
(`tests/integrations/test_muse_e2e.py`), and locally against the Meta Model API
(`muse-spark-1.3`, fictional data only). 1.4.13 (`1.4.13-R6996.1`) sends the same requests (see
[1.4.13 to 1.4.14](#1413-to-1414)).

## Setup (copy-paste)

```bash
# 1. The gateway, forwarding to the Meta Model API, in fast mode (see "Mode" below)
cat >> .env <<'EOF'
PII_GUARD_TENANT_KEY=<openssl rand -hex 32>
PII_GUARD_UPSTREAM_BASE_URL=https://api.meta.ai/v1
PII_GUARD_GATEWAY_MODE=fast
PII_GUARD_TRAFFIC_LOG=masked        # optional: shows the calls on the Live traffic tab
EOF
uv run pii-guard serve

# 2. In a second terminal: see what connect would change, then do it
uv run pii-guard connect muse-code --dry-run
uv run pii-guard connect muse-code            # backs up ~/.config/muse/settings.json first
uv run pii-guard connect muse-code --check    # one fictional canary the way Muse sends it

# 3. Use Muse as usual
muse
```

`connect muse-code` sets two keys in Muse's `settings.json` (`$XDG_CONFIG_HOME/muse`, default
`~/.config/muse`; `--muse-dir` overrides it). Every other setting is kept, including other
`endpoint_transport` keys such as `proxy` and `ca_bundle`:

```json
{
  "schema_version": 1,
  "endpoint_transport": { "base_url": "http://127.0.0.1:8787/s/c_5f0c3a9e1b7d4f2a8c6e0b9d3a1f7e2c/v1", "auth": "bearer" }
}
```

- `base_url` carries a vault session in its path (see [Sessions](#sessions)); rerunning
  connect keeps it.
- `auth: "bearer"` matters. Without that pin, Muse withholds its key from any base URL other
  than Meta's (a `--base-url` flag alone isn't enough).
- **The key.** Muse sends `META_API_KEY` (or the key `muse login` saved) as its bearer token.
  With `PII_GUARD_UPSTREAM_API_KEY` unset, as above, the gateway passes that key on to the Meta
  Model API. If you set `PII_GUARD_UPSTREAM_API_KEY`, the gateway sends its own key, and Muse
  still needs some value in `META_API_KEY` because it refuses to start without one.
- Running connect again is a no-op ("already up to date"). Each change keeps a backup:
  `settings.json.pii-guard-backup-<UTC time>`.

### Mode

Muse can't send custom headers, so it can't ask for `X-PII-Guard-Mode`. It gets the gateway's
default mode, which is `strict` unless `PII_GUARD_GATEWAY_MODE=fast` is set. In strict mode,
every turn waits for the LLM detector. A Muse task sends 7 to 10 requests (its main turns plus
reminder observers), each with about 10 kB of instructions and around 80 tool definitions, so
run a gateway for Muse in fast mode (rules + NER). `connect` and `--check` print a reminder.
Language: the gateway's `PII_GUARD_DEFAULT_LANGUAGE` (set `en` for English code).

### `--check`

`--check` reads the catalog (`GET /muse-code/models`), then sends one non-streamed
`POST /v1/responses` with `X-PII-Guard-Echo: masked` and prints the round trip:

```
gateway      : http://127.0.0.1:8787/s/c_5f0c3a9e1b7d4f2a8c6e0b9d3a1f7e2c/v1/responses
model        : muse-spark-1.3
sent         : pii-guard connect check. Reply in one short sentence that repeats this contact exactly: email jane.placeholder@example.net, phone +44 20 7946 0958, IBAN GB82 WEST 1234 5698 7654 32.
model saw    : pii-guard connect check. Reply in one short sentence that repeats this contact exactly: email [[EMAIL_6eab02]], phone [[PHONE_5d1e2e]], IBAN [[BANK_ACCOUNT_9fd9f1]].
model said   : The contact is email [[EMAIL_6eab02]], phone [[PHONE_5d1e2e]], IBAN [[BANK_ACCOUNT_9fd9f1]].
you got back : The contact is email jane.placeholder@example.net, phone +44 20 7946 0958, IBAN GB82 WEST 1234 5698 7654 32.
session      : path (the session in the base URL: placeholders stay the same across conversations)
ok           : 3 value(s) masked, none reached the model, answer restored
gateway mode : fast
```

Without `--model`, the check uses the first visible model in the catalog.

## What goes through the gateway

Muse's `meta` provider makes two kinds of requests to the base URL:

1. `GET <scheme://host>/muse-code/models`, at the **root** of the base URL. This is the model
   catalog: the OpenAI model list plus per-model client settings under
   `metadata["muse-code"]` (context and output limits, reasoning variants, prices,
   `options.include: ["reasoning.encrypted_content"]`). Without it, Muse stops with "failed to
   fetch model catalog". The gateway passes the upstream's catalog through (the Meta Model API
   serves one), keeping `id`, `object`, `created`, `owned_by` and `metadata["muse-code"]`. An
   upstream without one gets a catalog built from `GET /v1/models` with default settings (Muse
   also accepts an empty `metadata["muse-code"]`).
2. Streamed `POST <base_url>/responses`. Each request carries the whole conversation
   (`store: false`). The gateway masks it through a fail-closed allow-list, forwards it to the
   upstream's own `/responses`, and restores the `response.*` event stream
   (docs/contracts.md, "Responses API").

The fields Muse 1.4.13 and 1.4.14 send (`request_keys` in the run records):

| Where | Fields |
|---|---|
| body | `model`, `instructions`, `input`, `tools`, `reasoning` (`effort`, `summary`), `include: ["reasoning.encrypted_content"]`, `prompt_cache_key`, `max_output_tokens`, `store: false`, `stream: true` |
| `input` items | `message` (`developer`, `user`, `assistant`; `id`, `phase` on assistant messages), `function_call` (`id`, `call_id`, `name` like `muse.read_file`, `arguments`), `function_call_output` (`call_id`, `output`), `reasoning` (`id`, `summary`, `encrypted_content`) |
| `tools` | one `namespace` tool (`muse`) holding about 27 `function` tools (`read_file`, `write_file`, `bash`, ...); side requests carry `submit_reminder_decision` |
| headers | `Authorization: Bearer`, `x-tbh-session-id`, `x-tbh-thread-id`, `x-meta-ai-gateway-session-id` (not used by the gateway) |

The event types it receives and the gateway rewrites: `response.created`,
`response.in_progress`, `response.output_item.added`/`.done`,
`response.content_part.added`/`.done`, `response.output_text.delta`/`.done`,
`response.function_call_arguments.delta`/`.done`,
`response.reasoning_summary_part.added`/`.done`,
`response.reasoning_summary_text.delta`/`.done`, `response.completed`, then `data: [DONE]`.

- **Encrypted reasoning** (`reasoning.encrypted_content`) is forwarded untouched both ways. It
  is the provider's own encrypted record of earlier reasoning, produced from masked input.
- **Line-number gutters.** Muse's `read_file` prints each line after its number
  (`12|Jane Placeholder`), and its reminder observers get the conversation again inside a
  message. Glued to the first word, the gutter made the name detector mask only the surname
  (`12|Jane [[PERSON_…]]`). The Responses walker hides gutters from the detectors and puts
  them back in the forwarded text.
- **Tool names aren't names.** The detectors can read a tool's name as a person's (the NER
  tags Muse's own name, "Muse", as a PERSON). A detection whose whole value is a tool or
  namespace name the request declares is left as written: that name goes upstream as written
  anyway, because it is an identifier. Without this, the vault masked the `muse` namespace as
  one more occurrence of that "name" and the request was refused (LAB-1299).
- **Side requests.** Muse runs reminder observers (skill, goal, verify) next to the main
  agent. They are ordinary `/v1/responses` calls and are masked the same way.
- **Retries.** Muse retries a failed request up to 10 times with backoff (1 s to 32 s). A
  request the gateway refuses (`400 unsupported_content`) is therefore retried for minutes
  before Muse gives up. The gateway log line and the traffic tab show the refusal at once.

## End to end

`python -m pii_guard.integrations.e2e --client muse-code` runs a real Muse Code on the fictional
mini-repo ([examples/coding-agents/](../../examples/coding-agents/)): read the client letter, the
customer CSV and `.env`, then write `reply.md`. It installs Muse with the official installer
into a throwaway `HOME` (about 400 MB; `--muse-home DIR` reuses one) and runs only the pinned
version (`MUSE_VERSION_CHECKED`). When the installer serves another version, the run stops and
the tests fail (they don't skip): re-check the protocol ([How this was found](#how-this-was-found))
and bump the pin, or run the served version anyway with `--muse-version <version>`
(`PII_GUARD_MUSE_VERSION` for pytest). The tests skip only when the installer can't be fetched. Muse runs in a throwaway `HOME` too, with `connect muse-code` writing its settings and
the gateway in fast mode.

```bash
# scripted mock model, as in the test
uv run python -m pii_guard.integrations.e2e --client muse-code
# the Meta Model API (fictional data only; the recorder holds the key, Muse gets a dummy one)
uv run python -m pii_guard.integrations.e2e --client muse-code --upstream https://api.meta.ai/v1 \
    --model muse-spark-1.3 --key-env META_API_KEY --record examples/coding-agents/runs/<name>.json
```

Runs on 2026-10-27, fast mode with NER, the connect path URL (one session):

| Run | Muse | Requests | Refused | Gold values upstream | Name partly upstream | Real values in `reply.md` | Placeholders left |
|---|---|---:|---:|---:|---:|---:|---:|
| Scripted mock model | 1.4.14 | 11 | 0 | 0 of 16 | 0 | 16 of 16 | 0 |
| Meta Model API, `muse-spark-1.3` | 1.4.14 | 7 | 0 | 0 of 16 | 0 | 6 | 0 |
| Scripted mock model ([record](../../examples/coding-agents/runs/2026-10-27-coding-agent-muse-code-mock.json)) | 1.4.13 | 10 | 0 | 0 of 13 | 2 | 13 of 13 | 0 |
| Meta Model API ([record](../../examples/coding-agents/runs/2026-10-27-coding-agent-muse-code-meta-muse-spark-1.3.json)) | 1.4.13 | 7 | 0 | 0 of 13 | 1 | 6 | 0 |

The 1.4.13 rows are older (13 gold values, before `SECRET` and LAB-1286's path session).

- "Name partly upstream" counts a gold name that never went upstream whole, but one of whose
  words did. The 1.4.13 cases were a first name glued to a CSV comma (`1,Jane [[PERSON_…]]`,
  LAB-1258, LAB-1284) and, in the mock run, a name split inside the model's own list; with one
  path session the whole name is known from the first turn, so none are left.
- The live model wrote the client's details and some customer e-mails (6 values). It chose
  what to include; everything it wrote came back restored.
- Known gaps, as for pi: the three fake secrets in `.env` reach the model (they aren't
  personal data types).

## How this was found

Muse Code was installed with the official installer into a throwaway `HOME`, so the real
`~/.local/bin`, `~/.config/muse` and shell profiles were not touched:

```bash
export HOME=$(mktemp -d) XDG_CONFIG_HOME=$HOME/.config MUSE_NO_MODIFY_PATH=1
curl -fsSL https://dev.meta.ai/install.sh -o install.sh   # read it first
bash install.sh
$HOME/.local/bin/muse --version        # Muse Code 1.4.14 (1.4.14-R7309.1)
```

The installer only installs the current release. An older one, for a comparison, comes from its
release manifest, the file the launcher reads (check the `sha256` it lists):
`https://lookaside.facebook.com/lookaside/muse/download/?channel=muse&version=<version>&file=manifest.json`.

`MUSE_TRANSPORT_TRACE=1` prints each request body and every SSE event Muse receives (keys
aren't printed). The table above comes from a traced run against the Meta Model API and from
the recorder in the e2e harness. `--provider local` runs Muse's embedded llama.cpp with
downloaded Glimmer weights and ignores the base URL. It is not covered here.

### 1.4.13 to 1.4.14

Both versions ran the scripted e2e task with `MUSE_TRANSPORT_TRACE=1`, and the traces were
compared field by field (names and types, not values):

- **Same on the wire:** the body fields, the `input` item types and their keys (`message`,
  `function_call`, `function_call_output`, `reasoning` with `encrypted_content`), the one
  `muse` namespace with the same 27 function tools, `reasoning` (`effort` low/high,
  `summary: auto`), `include: ["reasoning.encrypted_content"]`, `store: false`, `stream: true`,
  `max_output_tokens: 128000`, the four `prompt_cache_key` kinds (`tbh:main:…`,
  `tbh:skill-reminder:…`, `tbh:goal-reminder:…`, `tbh:verify-reminder:…`), one
  `GET /muse-code/models`, 10 to 12 `POST /responses`, and the `response.*` event types it
  takes. No new field, so the fail-closed allow-list needed no change.
- **Changed:** the prompt text (the instructions are a few hundred characters longer, and the
  reminder prompts say "Muse" on its own). The NER read that as a PERSON. When it was the
  first "Muse" in a new session, the vault then masked the `muse` namespace too and the gateway
  refused the request: in 4 of 4 runs on 1.4.14 and none of 4 on 1.4.13. A request running
  at the same time then got 404, because the refused request dropped the session it had just
  created, and Muse stopped with "model does not exist". Fixed in the gateway (tool names, above).

Muse can also attach images (`--image`). `/v1/responses` refuses image parts for now
(LAB-1285).

## Sessions

Muse can't send `X-PII-Guard-Session`, so `pii-guard connect muse-code` writes a base URL with a
vault session in its path, `http://127.0.0.1:8787/s/<session>/v1` (LAB-1286): every call, the
main agent's and its reminder observers', lands in that session, and the same value has the
same placeholder in every turn and every task. `--check` prints `session      : path`. With
`--no-session-path` (the plain URL) the gateway uses one session per `prompt_cache_key`;
Muse sends one key for the main conversation and one per observer, so a task spans about four
sessions and a value gets a placeholder in each (all of them restored). Details:
[architecture-gateway.md](../architecture-gateway.md#sessions).

| Muse 1.4.14, e2e harness | requests | sessions | distinct placeholders upstream | gold values under >1 placeholder (most for one) | gold upstream |
|---|---|---|---|---|---|
| scripted, `--session per-request` (before) | 10 | 10 | 150 | 16 of 16 (8) | 0 of 16 |
| scripted, `--session auto` (`prompt_cache_key`) | 10 | 4 | 85 | 16 of 16 (4) | 0 of 16 |
| scripted, `--session path` (`connect` default) | 11 | 1 | 25 | 0 of 16 (1) | 0 of 16 |
| Meta Model API `muse-spark-1.3`, per-request (before; 13 gold, before `SECRET`) | 10 | 10 | 155 | 13 of 13 (8) | 0 of 13 |
| Meta Model API `muse-spark-1.3`, path (13 gold, before `SECRET`) | 8 | 1 | 21 | 0 of 13 (1) | 0 of 13 |

```bash
uv run python -m pii_guard.integrations.e2e --client muse-code --session per-request   # before
uv run python -m pii_guard.integrations.e2e --client muse-code                         # path
```
