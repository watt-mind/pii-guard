# Codex behind PII Guard

[Codex](https://github.com/openai/codex) (OpenAI's coding agent, `npm i -g @openai/codex`)
speaks the OpenAI **Responses API**. It runs through the gateway's `POST /v1/responses` with a
launch command alone: no config file is written or changed.

Checked on Codex **0.163.0** (`CODEX_VERSION` in
[`snippets.py`](../../src/pii_guard/integrations/snippets.py)), end to end in
[`tests/integrations/test_codex_e2e.py`](../../tests/integrations/test_codex_e2e.py).

## Setup

```bash
export META_API_KEY=<your-key>
pii-guard up --upstream meta
```

Then paste the block from the console's **Connect** page (Codex tab), or print it:

```bash
pii-guard connect codex --print
```

It looks like this (the session and model are filled in for your gateway):

```bash
codex -m muse-spark-1.3 \
  -c model_provider=pii-guard \
  -c 'model_providers.pii-guard={name="pii-guard", base_url="http://127.0.0.1:8787/s/c_5f0c3a9e1b7d4f2a8c6e0b9d3a1f7e2c/v1", wire_api="responses"}' \
  -c web_search=disabled
```

- `-c` overrides apply to this run only (Codex reads them on top of `~/.codex/config.toml`):
  a `pii-guard` model provider with the gateway's base URL, `wire_api = "responses"`, and that
  provider selected. `codex exec "<task>"` takes the same flags, headless.
- `base_url` carries a vault session in its path: Codex sends no `X-PII-Guard-Session`, and
  with the session in the URL the same value gets the same placeholder in every turn
  ([architecture-gateway.md](../architecture-gateway.md#sessions)).
- **No key in the block.** The gateway holds the upstream key (`--upstream meta` reads
  `$META_API_KEY`), so Codex sends none. When the gateway needs a token
  (`PII_GUARD_API_TOKEN`), the provider gets `env_key="PII_GUARD_API_TOKEN"` and Codex sends
  that variable's value.
- **`web_search=disabled`.** Codex's hosted web search tool runs at the provider, on text the
  gateway never sees, so the gateway refuses requests that offer it (fail closed). Every other
  Codex tool (`exec_command`, `write_stdin`, `view_image`, ...) is a function tool the gateway
  masks.
- Codex can't send `X-PII-Guard-Mode`: `pii-guard up` runs fast mode (rules + NER) already. With
  `pii-guard serve`, set `PII_GUARD_GATEWAY_MODE=fast`.
- Codex warns `Model metadata for <model> not found` for a model OpenAI doesn't list. The
  warning is harmless.
- `pii-guard connect codex --check` sends one fictional canary the way Codex does (a
  non-streamed `POST <base_url>/responses` through a path session) and prints what the model
  saw and what came back.
- Codex mints its own message ids (`msg_<uuid>`) and sends the model's call ids back; the
  gateway forwards both as sent (LAB-1469: the NER used to read some of them as phone numbers
  and refuse the request).

## What the gateway sees from Codex

Each request carries the whole conversation (`store: false`): `instructions`-style developer
and user messages, `function_call` / `function_call_output` items for its shell tool, opaque
`reasoning` items (`encrypted_content`, forwarded untouched), `prompt_cache_key`, and
`client_metadata`, Codex's per-turn ids (session, turn, installation). `client_metadata` is
walked like `metadata`: keys checked, values masked (docs/contracts.md).

## End-to-end test

```bash
uv run python -m pii_guard.integrations.e2e --client codex                 # scripted mock (CI)
uv run python -m pii_guard.integrations.e2e --client codex --upstream https://api.meta.ai/v1 \
    --model muse-spark-1.3 --key-env META_API_KEY                           # live
```

The harness installs Codex with npm into a throwaway prefix (`PII_GUARD_CODEX_PREFIX` reuses one
in pytest), runs the Connect page's block plus `exec --sandbox workspace-write` on a copy of
[`examples/coding-agents/mini-repo`](../../examples/coding-agents/) with its own `CODEX_HOME`,
and counts what reached the upstream. The scripted model reads the three files with one `cat`,
writes `reply.md` with a heredoc of the placeholders it saw, and finishes.

| Run | Requests | Refused | Gold values upstream | `reply.md` restored |
|---|---|---|---|---|
| Scripted mock | 3 | 0 | 0 of 14 | 14 of 14, no placeholder left |
| Live, Meta Model API `muse-spark-1.3` (2026-10-28) | 4 | 0 | 0 of 14 | written, 0 placeholders left |

The live model's reply didn't repeat the values, so there was nothing to restore in the file;
what matters is that none of the 14 reached it. Names inside CSV rows were a known gap in these
runs (2 of them upstream), as for pi and Muse Code; the NER now sees each CSV cell (LAB-1258).
