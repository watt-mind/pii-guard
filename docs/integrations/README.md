# Integrations: putting a client behind pii-guard

The gateway is an OpenAI-compatible endpoint: `POST /v1/chat/completions`,
`POST /v1/responses` (the Responses API) and `GET /v1/models` at `http://127.0.0.1:8787/v1`. A
client that lets you set a base URL for either API works through it. The client sends real data, the model gets placeholders, and the
answer (tool-call arguments included) comes back restored.

| Client | Status | Setup |
|---|---|---|
| [pi](pi.md) (coding agent) | Supported, tested end to end in CI (mock upstream) and on the Meta Model API | `pii-guard connect pi` |
| [Muse Code](muse-code.md) (Meta's coding agent) | Supported through `/v1/responses`, tested end to end on a mock upstream and on the Meta Model API | `pii-guard connect muse-code` |
| Any OpenAI-compatible client (OpenAI SDKs, LangChain, LiteLLM, Open WebUI, ...) | Supported | Base URL `http://127.0.0.1:8787/v1`, see below |

The quickest way to get one running is `pii-guard up` (API, gateway and UI on port 8787, mock
upstream unless `--upstream-url` is given; [operations.md](../operations.md#one-command-pii-guard-up)).

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

- `fast` (rules + the NER encoder, in-process) is what `pii-guard connect` configures for
  coding agents. An agent sends dozens of long requests per task, and strict mode's LLM
  detector would add its latency to every one.
- `strict` adds the LLM detector. It catches more names in free text but is slower; set
  `--mode strict` on `connect`, or the header yourself.

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
that the first answer returned (docs/contracts.md). Coding agents don't need to: they resend
the whole history every turn, and each request is masked and restored as a unit.

## 4. Check it end to end

```bash
pii-guard connect pi --check
```

This sends one fictional canary through the client's configured path and prints what was
sent, what the model saw and what came back. With the traffic log on
(`PII_GUARD_TRAFFIC_LOG=masked`, as `make demo` sets), the call also shows on the UI's
**Live traffic** tab at <http://localhost:5173/#traffic>.

## What gets masked in coding work

Measured on the fictional mini-repo ([examples/coding-agents/](../../examples/coding-agents/))
plus five source files and one doc from this repository, in fast mode
([run record](../../examples/coding-agents/runs/2026-10-27-coding-agent-overmask-fast.json)):

- **Masked:** names, e-mail addresses, phone numbers, IBANs and other identifiers the language
  packs know, in prompts, file contents the agent reads, tool results and tool-call arguments.
- **Not masked, on purpose:** code identifiers, file paths and URLs. 0 of 23 masked spans
  were code. The only false positives were the country codes `HU`, `GB` and `DE` in a markdown
  table (read as `ADDRESS`). Constants that *are* personal data, such as a support address in
  code, are masked like any other value; the agent writes them back restored.
- **Not masked yet:** secrets. API keys, tokens and passwords in a `.env` are not personal data
  types, so they reach the model. Keep them out of the agent's reach, or see the follow-up
  ticket. Names inside CSV rows are also only partly found by the NER model.
