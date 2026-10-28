# OpenCode behind pii-guard

[OpenCode](https://opencode.ai) (`npm i -g opencode-ai`) talks to any OpenAI-compatible
provider through `@ai-sdk/openai-compatible`, over **Chat Completions**. It runs through the
gateway with one environment variable: no config file is written or changed.

Checked on OpenCode **1.19.3** (`OPENCODE_VERSION` in
[`snippets.py`](../../src/pii_guard/integrations/snippets.py)), end to end in
[`tests/integrations/test_opencode_e2e.py`](../../tests/integrations/test_opencode_e2e.py).

## Setup

```bash
export META_API_KEY=<your-key>
pii-guard up --upstream meta
```

Then paste the block from the console's **Connect** page (OpenCode tab), or print it:

```bash
pii-guard connect opencode --print
```

It looks like this (the session and model are filled in for your gateway):

```bash
export OPENCODE_CONFIG_CONTENT='{"provider":{"pii-guard":{"npm":"@ai-sdk/openai-compatible","name":"pii-guard","options":{"baseURL":"http://127.0.0.1:8787/s/c_5f0c3a9e1b7d4f2a8c6e0b9d3a1f7e2c/v1"},"models":{"muse-spark-1.3":{}}}},"model":"pii-guard/muse-spark-1.3"}'
opencode
```

- OpenCode merges `OPENCODE_CONFIG_CONTENT` into its config: a `pii-guard` provider with the
  gateway's base URL and the model, made the default. `opencode run "<task>"` works the same,
  headless.
- `baseURL` carries a vault session in its path, so the same value keeps the same placeholder in
  every turn ([architecture-gateway.md](../architecture-gateway.md#sessions)).
- **No key in the block.** The gateway holds the upstream key. When the gateway needs a token,
  the provider gets `"apiKey": "{env:PII_GUARD_API_TOKEN}"`, which OpenCode reads from the
  environment.
- On first use OpenCode installs `@ai-sdk/openai-compatible` from npm into its cache.
- OpenCode asks before it reads `.env` files and, headless, refuses. The e2e passes `--auto`
  because its task reads the mini-repo's fictional `.env` on purpose.
- OpenCode can't send `X-PII-Guard-Mode`: `pii-guard up` runs fast mode already. With
  `pii-guard serve`, set `PII_GUARD_GATEWAY_MODE=fast`.
- Besides the agent turns, OpenCode sends one short side request without tools to title the
  session; it goes through the gateway too (masked like any other).

## End-to-end test

```bash
uv run python -m pii_guard.integrations.e2e --client opencode               # scripted mock (CI)
uv run python -m pii_guard.integrations.e2e --client opencode --upstream https://api.meta.ai/v1 \
    --model muse-spark-1.3 --key-env META_API_KEY                            # live
```

The harness installs OpenCode with npm into a throwaway prefix (`PII_GUARD_OPENCODE_PREFIX`
reuses one in pytest), runs the Connect page's block with `opencode run --auto` on a copy of
[`examples/coding-agents/mini-repo`](../../examples/coding-agents/) in a throwaway `HOME`, and
counts what reached the upstream. The scripted model uses OpenCode's `read` and `write` tools
(absolute `filePath`).

| Run | Requests | Refused | Gold values upstream | `reply.md` restored |
|---|---|---|---|---|
| Scripted mock | 6 | 0 | 0 of 14 | 14 of 14, no placeholder left |
| Live, Meta Model API `muse-spark-1.3` (2026-10-28) | 7 | 0 | 0 of 14 | 3 values, no placeholder left |

Names inside CSV rows are a known gap (2 of them upstream), as for pi and Muse Code.
