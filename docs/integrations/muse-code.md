# Muse Code behind pii-guard: not configurable yet

**Status (2026-10-27, Muse Code 1.4.13-R6996.1):** Muse Code can be pointed at a custom
endpoint, but it speaks the **OpenAI Responses API**, and the pii-guard gateway serves **Chat
Completions** only. Muse Code can't go through pii-guard yet. Use [pi](pi.md) as the coding
agent in the meantime.

`pii-guard connect muse-code` prints this finding and exits with status 1.

## What was checked

Muse Code was installed with the official installer into a throwaway `HOME`, so the real
`~/.local/bin`, `~/.config/muse` and shell profiles were not touched:

```bash
export HOME=$(mktemp -d) XDG_CONFIG_HOME=$HOME/.config MUSE_NO_MODIFY_PATH=1
curl -fsSL https://dev.meta.ai/install.sh -o install.sh   # read it first
bash install.sh
$HOME/.local/bin/muse --version        # Muse Code 1.4.13 (1.4.13-R6996.1)
```

The requests were captured with a local HTTP server on `127.0.0.1` that logs every request
and redacts `Authorization`. The tests used a dummy key, so no Meta credits were spent on Muse.

| Check | Result |
|---|---|
| `muse --help`, `muse exec --help` | `--base-url <URL>` ("Override the Meta provider base URL"), `--provider echo\|meta\|local` |
| `muse config status` | Shows only the enterprise planes (system file, macOS managed preferences); no provider settings |
| `muse schema --help` | Exports the MSP wire schema (`muse serve`'s client protocol), not provider settings |
| Settings keys in the binary | `endpoint_transport.base_url`, `.auth`, `.proxy`, `.ca_bundle` |
| `muse exec --base-url http://127.0.0.1:<port>/v1` | Works. The first request is `GET /muse-code/models` (at the host root), then `POST /v1/responses`. The binary warns that a `--base-url` flag alone does not get the bearer key: the settings file has to pin it |
| `settings.json` with `endpoint_transport` (below) | Same requests, with the bearer key |
| `MUSE_TRANSPORT_TRACE=1` | Prints each request body: Responses API `input` items |
| `--provider local` | Runs Muse's embedded llama.cpp with downloaded "Glimmer" weights (needs the `local_models` experiment) and ignores `--base-url` |

The settings file that redirects Muse Code (`~/.config/muse/settings.json`):

```json
{
  "schema_version": 1,
  "endpoint_transport": { "base_url": "http://127.0.0.1:8787/v1", "auth": "bearer" }
}
```

### The two requests Muse Code needs

1. `GET <scheme://host>/muse-code/models`: a Muse-specific catalog. It is the OpenAI model list
   plus `metadata["muse-code"]` per model (context limits, reasoning variants, prices,
   `include: ["reasoning.encrypted_content"]`). Without it Muse stops with "failed to fetch
   model catalog".
2. `POST <base_url>/responses`, streamed. The top-level keys are `model`, `instructions`,
   `input` (`message` items with the `developer` and `user` roles, later function calls and
   their outputs), `tools` (one `namespace` tool), `reasoning: {effort, summary}`,
   `include: ["reasoning.encrypted_content"]`, `prompt_cache_key`, `max_output_tokens`,
   `store: false` and `stream: true`. Headers include `x-tbh-session-id`, `x-tbh-thread-id`
   and `x-meta-ai-gateway-session-id`.

The gateway has no `/v1/responses` route, so it would answer 404. It also can't forward
`reasoning.encrypted_content` blobs it can't read, or restore `response.*` stream events.
pii-guard does not intercept traffic: no `HTTPS_PROXY` or MITM setup, by design.

## What it would take

A Responses API front end in the gateway is tracked as a follow-up. It would:

- mask `instructions`, every `input` message's text, `function_call.arguments`,
  `function_call_output.output` and tool descriptions, with the same fail-closed allow-list
  as Chat Completions;
- restore streamed `response.output_text.delta` and `response.function_call_arguments.delta`
  events, holding back a placeholder that is split across events;
- serve `GET /muse-code/models` by passing the upstream catalog through (or adding the
  `muse-code` metadata to a static list);
- decide what to do with `reasoning.encrypted_content` (forward it untouched, as provider-signed
  blobs are today, or drop the `include`).

Questions for Meta: is a Chat Completions transport planned for the `meta` provider, and is
`/muse-code/models` meant to be served by third-party endpoints?
