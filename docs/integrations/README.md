# Integrations: putting a client behind PII Guard

The gateway is an OpenAI-compatible endpoint: `POST /v1/chat/completions`,
`POST /v1/responses` (the Responses API) and `GET /v1/models` at `http://127.0.0.1:8787/v1`,
plus the Anthropic Messages API (`POST /v1/messages`) for Claude Code. A
client that lets you set a base URL for either API works through it. The client sends real data, the model gets placeholders, and the
answer (tool-call arguments included) comes back restored.

For a plain OpenAI-compatible client (cURL, Python SDK), see [integrations.md](../integrations.md).

| Tool | API it uses | Setup | Tested version | End-to-end test |
|---|---|---|---|---|
| [Muse Code](muse-code.md) (Meta's coding agent) | Responses (`/v1/responses`) | `pii-guard run muse-code` or `pii-guard connect muse-code` | 1.4.14-R7309.1 | [`test_muse_e2e.py`](../../tests/integrations/test_muse_e2e.py) |
| [pi](pi.md) (coding agent) | Chat Completions | `pii-guard run pi` or `pii-guard connect pi` | 1.4.0 | [`test_pi_e2e.py`](../../tests/integrations/test_pi_e2e.py) |
| [Codex](codex.md) (OpenAI's coding agent) | Responses (`/v1/responses`) | `pii-guard run codex` or a launch command with `-c` flags | 0.163.0 | [`test_codex_e2e.py`](../../tests/integrations/test_codex_e2e.py) |
| [OpenCode](opencode.md) | Chat Completions | `pii-guard run opencode` or `OPENCODE_CONFIG_CONTENT` | 1.19.3 | [`test_opencode_e2e.py`](../../tests/integrations/test_opencode_e2e.py) |
| cURL, Python (OpenAI SDK), LangChain, LiteLLM, Open WebUI, ... | Chat Completions or Responses | base URL `http://127.0.0.1:8787/v1`, see below | | |
| [Claude Code](claude-code.md) | Anthropic Messages (`/v1/messages`) | `pii-guard run claude-code` or `ANTHROPIC_BASE_URL` on the launch command | 2.1.312 | checked by hand ([claude-code.md](claude-code.md#what-was-checked)) |

The versions installed on a developer Mac (Codex 0.163.0, pi 1.3.0, OpenCode 1.18.26, Muse Code
1.4.14, Claude Code 2.1.289) were also run by hand against the Meta Model API, with the
published NER: [results matrix, 2026-10-28](harness-matrix-2026-10-28.md), re-run with the
placeholder note on [2026-10-29](harness-matrix-2026-10-29.md).

Each end-to-end test installs the pinned version into a throwaway directory, runs one task on
the fictional mini-repo through the gateway against a scripted upstream (CI), and asserts that
no gold value reached the upstream and that the files the agent wrote hold the real values
again. With `META_API_KEY` in the environment the Codex and OpenCode tests also run live
against the Meta Model API.

## One-command runner (`pii-guard run` & `pii-guard login`)

To start an in-process local gateway on `127.0.0.1` and launch a coding agent immediately in a
single terminal:

```bash
export META_API_KEY=<your-key>              # or OPENAI_API_KEY, OPENROUTER_API_KEY, FIREWORKS_API_KEY
pii-guard run opencode                      # also: codex, claude-code, pi, muse-code
```

`run` picks where scrubbed telemetry goes, in this order: `--dashboard` / dashboard flags and the
real environment (never a project's `./.env`), then the profile saved by `pii-guard login`. With
neither, an interactive first run asks once (hosted, local only, or self-hosted) and saves the
answer; a non-interactive run sends nothing.

| Mode | How |
| --- | --- |
| Hosted dashboard | `pii-guard login`, then `pii-guard run opencode` |
| Self-hosted dashboard | `pii-guard login --dashboard https://pii-guard.internal.example.com` |
| Local web UI | `pii-guard run opencode --dashboard local` (serves `http://127.0.0.1:<port>/#traffic`) |
| Off | `pii-guard run opencode --dashboard off` (or `pii-guard login --local` to make it the default) |

An endpoint key can still be passed without logging in:

```bash
export PII_GUARD_DASHBOARD_KEY=<your-endpoint-key>
pii-guard run opencode --dashboard https://pii-guard.internal.example.com --endpoint ep_abc123
```

Every dashboard URL, from a flag, the environment, a saved profile or a login response, must be
`https://` (`http://` only for a loopback host) with no `user:pass@`; anything else is refused
before a key or a masked body is sent.

### `pii-guard login`: saved telemetry profile

1. The CLI listens on a random port on `127.0.0.1` and opens
   `<dashboard>/#cli-auth?port=<port>&state=<random>` (plus `&project=<id>` with `--project`).
2. You approve the CLI for a project in the browser. The dashboard then sends the browser to
   `http://127.0.0.1:<port>/callback?state=<state>&code=<code>`: a short-lived, single-use
   code, never the key. A callback with a missing or wrong `state` is ignored and the CLI keeps
   waiting (until `--timeout`, 180 s by default); the code is never logged.
3. The CLI redeems the code with `POST <dashboard>/v1/cli/token` and receives the project's
   endpoint and a **telemetry-only** key: the server accepts it only for posting telemetry to
   that project's endpoint (and for revoking itself). If the response names
   a different dashboard origin than the one the CLI opened, nothing is saved.
4. The profile is written to `~/.config/pii-guard/cli.json` (or `$PII_GUARD_CLI_CONFIG`), created
   with mode `0600` and replaced atomically. `pii-guard login --status` shows it without the key.
   `run` only turns it into `PII_GUARD_REMOTE_URL` / `PII_GUARD_REMOTE_KEY` /
   `PII_GUARD_REMOTE_LEVEL` for its in-process gateway; the agent never sees it.

Headless or over SSH, `pii-guard login --no-browser` prints the URL and prompts for the code the
dashboard shows, and `--code -` reads it from stdin. Before saving, the CLI prints the origin
the telemetry will go to. `--code <value>` also works but leaves the code in your shell history.
`--telemetry-level stats` keeps the CLI to counts and timings even if the project allows masked
bodies.

`pii-guard logout` revokes the key on the dashboard (`DELETE <dashboard>/v1/cli/token`) and then
deletes `cli.json`. If the dashboard cannot be reached, the file is still deleted, the command
exits 1, and you should revoke the key in the dashboard yourself.

## Quickstart (the Connect page)

```bash
export META_API_KEY=<your-key>
pii-guard up --upstream meta        # also: openai, fireworks, openrouter (key in $<NAME>_API_KEY)
```

Then open **Connect** in the console (<http://127.0.0.1:8787/#connect>), pick your tool, and
paste its block in a terminal. The block has the gateway URL, a vault session for that tool
(`/s/<session>/v1`, so the same value keeps the same placeholder in every turn) and a model
from `GET /v1/models` filled in. Step 3 turns green with the first request from that tool:
"first request from Codex: 3 values masked, 0 reached the model", with a link to the call in
Logs. The same block in a terminal:

```bash
pii-guard connect codex --print     # muse-code, pi, codex, opencode, curl, python
```

Both read `GET /v1/connect/snippets` ([`snippets.py`](../../src/pii_guard/integrations/snippets.py)
is the one place the text lives). No block carries a key: keys appear as `$VARIABLE` or
`<your-key>`.

| `--upstream` | Base URL | Key variable | Suggested model |
|---|---|---|---|
| `meta` | `https://api.meta.ai/v1` | `META_API_KEY` | `muse-spark-1.3` |
| `openai` | `https://api.openai.com/v1` | `OPENAI_API_KEY` | the first listed |
| `fireworks` | `https://api.fireworks.ai/inference/v1` | `FIREWORKS_API_KEY` | the first listed |
| `openrouter` | `https://openrouter.ai/api/v1` | `OPENROUTER_API_KEY` | the first listed |

`--upstream-url` and `--api-key-env` still work for any other OpenAI-compatible endpoint; the
key variable may also be in `./.env`.

## 1. Point the gateway at an upstream

The gateway forwards to **any OpenAI-compatible endpoint**. You set three things, in `.env`
or the environment:

| Variable | What |
|---|---|
| `PII_GUARD_UPSTREAM_BASE_URL` | The upstream's OpenAI base URL (with or without `/chat/completions`) |
| `PII_GUARD_UPSTREAM_API_KEY` | Its key. The gateway sends it upstream, so clients never need it. Without it, the client's own `Authorization` header is passed on |
| `PII_GUARD_UPSTREAM_MODELS` | Optional: a static model list for `GET /v1/models` (comma-separated), for upstreams without a `/models` route |

The model is whatever the client asks for: the gateway passes `model` through unchanged.
`PII_GUARD_TENANT_KEY` (`openssl rand -hex 32`) is required, because it keys the vault.

Presets (fictional data only on hosted models, docs/models.md):

```bash
# Meta Model API
PII_GUARD_UPSTREAM_BASE_URL=https://api.meta.ai/v1
PII_GUARD_UPSTREAM_API_KEY=<your META_API_KEY>
# models: muse-spark-1.3, muse-spark-1.2, muse-wonder-1.0 (GET /v1/models lists them)

# Baseten (Model APIs)
PII_GUARD_UPSTREAM_BASE_URL=https://inference.baseten.co/v1
PII_GUARD_UPSTREAM_API_KEY=<your BASETEN_API_KEY>

# A local vLLM or Ollama: nothing leaves the machine
PII_GUARD_UPSTREAM_BASE_URL=http://127.0.0.1:11434/v1      # Ollama
PII_GUARD_UPSTREAM_MODELS=qwen2.5-coder:7b
```

Then start it and check the model list:

```bash
uv run pii-guard serve                    # http://127.0.0.1:8787
curl -s http://127.0.0.1:8787/v1/models   # proxied from the upstream (id, object, created, owned_by)
```

## 2. Choose the mode

Clients pick the detection mode per request with `X-PII-Guard-Mode`:

- `fast` (rules + the NER encoder, in-process, nothing leaves the machine) is the gateway's
  default and what `pii-guard connect` configures for coding agents. An agent sends dozens of
  long requests per task; fast mode adds milliseconds to each.
- `audit` adds a remote LLM detector as a second opinion, for spot-checking quality rather
  than everyday traffic: every message goes to the detector endpoint and adds about 2 s. Set
  `--mode audit` on `connect`, or the header yourself.

`X-PII-Guard-Language` (default `hu`, the gateway's `PII_GUARD_DEFAULT_LANGUAGE`) picks the
language pack. `connect` sets `en`, since agents mostly work on English code.

## 3. A generic OpenAI-compatible client

```python
from openai import OpenAI

client = OpenAI(base_url="http://127.0.0.1:8787/v1", api_key="unused-the-gateway-has-it")
reply = client.chat.completions.create(
    model="muse-spark-1.3",
    messages=[{"role": "user", "content": "Write to jane.placeholder@example.net ..."}],
    extra_headers={"X-PII-Guard-Mode": "fast", "X-PII-Guard-Language": "en"},
)
```

To keep one conversation's placeholders stable across turns, send the `X-PII-Guard-Session`
that the first answer returned (docs/contracts.md). A client that can't send headers gets a
sticky session anyway (LAB-1286): `pii-guard connect` writes a base URL with the session in
its path (`http://127.0.0.1:8787/s/<session>/v1`), and without one the gateway uses the
request's `prompt_cache_key`, else one default session per client key
([architecture-gateway.md](../architecture-gateway.md#sessions)). `X-PII-Guard-Session-Source`
on every answer says which one it used.

## 4. Check it end to end

```bash
pii-guard connect pi --check          # also muse-code, codex, opencode
```

This sends one fictional canary through the client's configured path (for Codex and
OpenCode, which have no config file, the way their Connect block sends requests) and prints what was
sent, what the model saw and what came back. With the traffic log on
(`PII_GUARD_TRAFFIC_LOG=masked`, as `make demo` sets), the call also shows on the UI's
**Live traffic** tab at <http://localhost:5173/#traffic>.

## What gets masked in coding work

Measured on the fictional mini-repo ([examples/coding-agents/](../../examples/coding-agents/))
plus five source files and one doc from this repository, in fast mode
([run record](../../examples/coding-agents/runs/2026-10-27-coding-agent-overmask-fast.json)):

- **Masked:** names, email addresses, phone numbers, IBANs and other identifiers the language
  packs know, in prompts, file contents the agent reads, tool results and tool-call arguments.
- **Not masked, on purpose:** code identifiers, file paths and URLs. 0 of 23 masked spans
  were code. The only false positives were the country codes `HU`, `GB` and `DE` in a markdown
  table (read as `ADDRESS`). Constants that *are* personal data, such as a support address in
  code, are masked like any other value; the agent writes them back restored.
- **Not masked yet:** secrets. API keys, tokens and passwords in a `.env` are not personal data
  types, so they reach the model. Keep them out of the agent's reach, or see the follow-up
  ticket. Names inside CSV rows are also only partly found by the NER model.
