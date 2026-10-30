# pi behind PII Guard

[pi](https://pi.dev) (`@earendil-works/pi-coding-agent`) is a terminal coding agent that
accepts any OpenAI-compatible endpoint as a custom provider. With PII Guard in between, pi
reads your files, runs tools and writes code as usual. The model only ever sees placeholders,
and pi's tool calls come back with the real values, so the files it writes are correct.

Tested with pi **1.4.0**: end to end in CI against a scripted mock model, and locally against
the Meta Model API (`muse-spark-1.3`, fictional data only).

## Setup (copy-paste)

```bash
# 1. The gateway, forwarding to any OpenAI-compatible upstream (docs/integrations/README.md)
cat >> .env <<'EOF'
PII_GUARD_TENANT_KEY=<openssl rand -hex 32>
PII_GUARD_UPSTREAM_BASE_URL=https://api.meta.ai/v1
PII_GUARD_UPSTREAM_API_KEY=<your META_API_KEY>
PII_GUARD_TRAFFIC_LOG=masked        # optional: shows the calls on the Live traffic tab
EOF
uv run pii-guard serve

# 2. In a second terminal: see what connect would change, then do it
uv run pii-guard connect pi --dry-run
uv run pii-guard connect pi            # backs up ~/.pi/agent/models.json first
uv run pii-guard connect pi --check    # one fictional canary through pi's configured path

# 3. Use pi as usual, with the pii-guard provider
pi --provider pii-guard --model muse-spark-1.3
```

`connect pi` merges one provider into pi's `models.json` (`$PI_CODING_AGENT_DIR`, default
`~/.pi/agent`). Every other provider, and the file's own formatting, stays as it was:

```json
"pii-guard": {
  "name": "pii-guard",
  "baseUrl": "http://127.0.0.1:8787/s/c_5f0c3a9e1b7d4f2a8c6e0b9d3a1f7e2c/v1",
  "api": "openai-completions",
  "apiKey": "pii-guard",
  "headers": { "X-PII-Guard-Mode": "fast", "X-PII-Guard-Language": "en" },
  "compat": { "supportsDeveloperRole": false, "supportsStore": false },
  "models": [{ "id": "muse-spark-1.3", "name": "muse-spark-1.3 (pii-guard)" }]
}
```

- `baseUrl` carries a vault session in its path (`/s/<session>/v1`, LAB-1286): pi sends no
  `X-PII-Guard-Session`, and with the session in the URL a value keeps its placeholder across
  turns and runs. Rerunning connect keeps the session; `--no-session-path` writes the plain
  URL (the gateway then uses one default session per client key).
- The models come from the gateway's `GET /v1/models` (the upstream's list), or `--model ID`
  (repeatable).
- `apiKey` is a placeholder: pi needs one to list the models, and the gateway sends its own
  `PII_GUARD_UPSTREAM_API_KEY` upstream. If the gateway requires `PII_GUARD_API_TOKEN`, connect
  writes `"$PII_GUARD_API_TOKEN"`, which pi reads from the environment at request time. The
  token itself is never written to the file.
- `fast` mode (rules + NER) is the default for agents; `--mode audit` adds the LLM detector
  (a second opinion for quality checks: slower, and the text goes to the detector endpoint).
- A hosted project endpoint URL (`--gateway https://<host>/e/<endpoint>/v1`) gets no
  `headers`: the endpoint's policy sets the mode and language, and the endpoint refuses a
  request that names others (LAB-1651), so `--mode` and `--language` don't apply there.
- The `compat` flags make pi send `system` instead of `developer` and leave out `store`, which
  non-OpenAI upstreams may reject. The gateway accepts both fields either way.
- Running it again is a no-op ("already up to date"). Each change keeps a backup:
  `models.json.pii-guard-backup-<UTC time>`.

`--check` prints the round trip:

```
gateway      : http://127.0.0.1:8787/s/c_5f0c3a9e1b7d4f2a8c6e0b9d3a1f7e2c/v1/chat/completions
sent         : ... email jane.placeholder@example.net, phone +44 20 7946 0958, IBAN GB82 WEST ...
model saw    : ... email [[EMAIL_3f9c1a]], phone [[PHONE_b20e77]], IBAN [[BANK_ACCOUNT_5d1e04]].
model said   : Contact: [[EMAIL_3f9c1a]], [[PHONE_b20e77]], [[BANK_ACCOUNT_5d1e04]]
you got back : Contact: jane.placeholder@example.net, +44 20 7946 0958, GB82 WEST 1234 ...
session      : path (the session in the base URL: placeholders stay the same across conversations)
ok           : 3 value(s) masked, none reached the model, answer restored
dashboard    : http://localhost:5173/#traffic (with PII_GUARD_TRAFFIC_LOG=masked or full)
```

## What pi sends, and what the gateway does with it

pi 1.4.0 sends `model`, `messages` (`system`, `user`, `assistant` with `tool_calls`, `tool`
with `tool_call_id`), `tools` (read, bash, edit, write), `stream: true`,
`stream_options.include_usage` and `max_completion_tokens`. The fail-closed allow-list already
covers all of these, so no request is refused. PII Guard masks:

- your prompt, pi's system prompt and every tool result (file contents, command output);
- the arguments of earlier tool calls in the history, string by string inside the JSON;
- tool descriptions and schemas (free text only; parameter names are checked, not masked).

The streamed answer is restored chunk by chunk, tool-call arguments included. A placeholder
split across chunks is held back until it is complete.

**What doesn't get masked:** code identifiers, paths and URLs (measured: 0 of 23 masked spans
on the mini-repo plus repository code; see the
[over-masking record](../../examples/coding-agents/runs/2026-10-27-coding-agent-overmask-fast.json)).
Secrets are not masked either: API keys, tokens and passwords are not personal data types.
In the end-to-end runs all 3 fake secrets from `.env` reached the model. Don't let an agent
read real secrets through PII Guard.

## The end-to-end test

`examples/coding-agents/mini-repo` is a fictional support-desk project: a client letter, a
customer CSV, a `.env` and some code. pi gets one task: read them, then write `reply.md` with
the client's IBAN, email and phone and every customer's email.

```bash
uv run pytest tests/integrations/test_pi_e2e.py        # CI: scripted mock model; needs node + npm
uv run --extra ner python -m pii_guard.integrations.e2e \
    --upstream https://api.meta.ai/v1 --model muse-spark-1.3 --key-env META_API_KEY \
    --record examples/coding-agents/runs/<date>-coding-agent-pi-meta-<model>.json
```

The harness installs the pinned pi with npm into a temp prefix and runs it with a throwaway
`HOME`, so your own `~/.pi` is never touched. A local recorder stands in for the upstream: it
keeps every request body, and either answers as a scripted coder or forwards to the real API
with the key. The gateway itself never holds the real key. Results, from the
[run records](../../examples/coding-agents/runs/):

| Run | Requests | Refused | Gold values upstream | Real values in `reply.md` |
|---|---:|---:|---:|---:|
| Scripted mock, fast = rules + NER | 5 | 0 | 0 of 13 | 13 of 13 |
| Meta Model API, `muse-spark-1.3` | 3 | 0 | 0 of 13 | 5 (the ones the task asked for) |

With the scripted model, a run without the NER extra (as in CI) checks the 11 rule-covered
values. Two things showed up with the real model:

- In a first run, without a hint, the model saw placeholders and decided to leave the
  personal data out of `reply.md` ("a privacy-safe draft"). Telling it once that placeholders
  are restored locally fixed that:

  > Personal data in these files reaches you as placeholders such as [[EMAIL_1a2b3c]]: copy
  > them exactly as written, they are turned back into the real values on this machine.

  Put the same line in your project's `AGENTS.md` or system prompt.
- One run, with the same prompt, never finished within 15 minutes, while the runs before and
  after it took 30 to 55 seconds. The harness now stops pi after `--timeout` seconds and records
  the run as failed.

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `connect pi`: "could not reach the gateway" | Start `pii-guard serve` first, or pass `--gateway URL`, or give `--model` |
| `GET /v1/models` answers 404 or 401 | The upstream has no `/models` route, or the key is wrong. Set `PII_GUARD_UPSTREAM_MODELS=id1,id2` |
| pi shows `503 upstream_not_configured` | `PII_GUARD_UPSTREAM_BASE_URL` is unset |
| pi shows `500 vault_not_configured` | `PII_GUARD_TENANT_KEY` is unset (`openssl rand -hex 32`) |
| pi shows `400 unsupported_content` | A request field the gateway can't mask yet (fail closed). The message names the field, never the value. Please report it; newer pi versions may add fields |
| pi shows `401` | The gateway runs with `PII_GUARD_API_TOKEN`: export it in pi's shell, and rerun `connect pi` so the provider uses `$PII_GUARD_API_TOKEN` |
| The model writes placeholders into files | It invented or changed one (`[[EMAIL_xyz]]` that isn't in the conversation). Only placeholders the session issued are restored |
| The model refuses to copy personal data | It sees placeholders and plays safe. The gateway tells it they are opaque tokens restored locally ([placeholder note](../architecture-gateway.md#placeholder-note), on by default since LAB-1471); if it still refuses, say so in `AGENTS.md` too (see above) |
| `--check` says "no pii_guard echo" or "no pii-guard headers" | `baseUrl` points at the model itself, not at PII Guard |
