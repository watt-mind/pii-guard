# Claude Code behind PII Guard

[Claude Code](https://docs.anthropic.com/en/docs/claude-code) speaks the Anthropic **Messages
API** (`POST /v1/messages`). It runs through the gateway's own `/v1/messages` adapter
(LAB-1605) with one environment variable on the launch command: no config file is written or
changed. Request text, system blocks, tool definitions, `tool_use` inputs, `tool_result`
contents, thinking text and inline images are masked; the streamed answer, tool inputs
included, comes back restored. The field-by-field contract is in
[contracts.md](../contracts.md#messages-api-implemented).

Checked on Claude Code **2.1.312** (`CLAUDE_CODE_VERSION` in
[`snippets.py`](../../src/pii_guard/integrations/snippets.py)) against a scratch
Anthropic-compatible upstream, see "What was checked" below.

## Setup

The upstream must serve the Messages API too: the gateway forwards natively to
`{PII_GUARD_UPSTREAM_BASE_URL}/messages` and never translates to Chat Completions.

```bash
export PII_GUARD_UPSTREAM_BASE_URL=https://api.anthropic.com/v1
export PII_GUARD_UPSTREAM_API_KEY=<your-anthropic-key>   # sent upstream as x-api-key
pii-guard serve
```

An OpenAI-only upstream answers `.../messages` with 404; the gateway turns that into
`400 unsupported_api` (with `x-should-retry: false`), which Claude Code shows as is.

Then paste the block from the console's **Connect** page (Claude Code tab), or print it:

```bash
pii-guard connect claude-code --print
```

It looks like this (the session and model are filled in for your gateway):

```bash
ANTHROPIC_BASE_URL=http://127.0.0.1:8787/s/c_5f0c3a9e1b7d4f2a8c6e0b9d3a1f7e2c ANTHROPIC_API_KEY=unused \
  claude --model claude-sonnet-4-5
```

- `ANTHROPIC_BASE_URL` is the session root **without** `/v1`: the Anthropic SDK appends
  `/v1/messages` itself. The session in the path keeps the same value on the same placeholder
  in every turn ([architecture-gateway.md](../architecture-gateway.md#sessions)).
- **No key in the block.** The gateway holds the upstream key and sends it as `x-api-key`;
  Claude Code's own key is dropped. Without `PII_GUARD_UPSTREAM_API_KEY` the client's
  `x-api-key` (or `Authorization`) is passed through instead. When the gateway checks a token
  (`PII_GUARD_API_TOKEN`), the block sets `ANTHROPIC_AUTH_TOKEN="$PII_GUARD_API_TOKEN"`.
- `anthropic-version` and `anthropic-beta` are passed on; other client headers are not.
- **Sessions.** Only `Authorization` derives a client identity. A Claude Code that sends only
  `x-api-key` is the `anonymous` local principal, so use the session URL from the block (or
  `X-PII-Guard-Session`) to keep conversations apart. Per-key session isolation for Anthropic
  clients is a follow-up (LAB-1643). A guard token sent as `x-api-key` authenticates and is
  stripped before anything goes upstream.
- Not offered for project endpoint URLs (`/e/<endpoint>/v1`) yet: their upstreams are
  OpenAI-compatible presets.

## What is refused

Fail closed, as on the other APIs: server tools (`web_search_*`, `code_execution_*`, ...),
`mcp_servers`, `container`, `document`/`search_result` blocks, URL or file images and
citations are `400 unsupported_content`, and nothing is forwarded. Claude Code's default
request (client tools only) uses none of them.

## What was checked

Claude Code 2.1.312, `claude -p` in a scratch directory with its own `CLAUDE_CONFIG_DIR`,
`ANTHROPIC_BASE_URL` at a local gateway, the gateway's upstream a scratch recording server
that answers in the Messages format (streamed in 6-7 character deltas, so placeholders split
across deltas):

- a prompt with a fictional e-mail, phone and IBAN reached the upstream as
  `[[EMAIL_…]]`, `[[PHONE_…]]`, `[[BANK_ACCOUNT_…]]`, and the streamed answer came back with
  the values;
- a two-turn tool task (`--allowedTools Write`): the upstream answered with a `tool_use` whose
  `input_json_delta` carried placeholders; the file Claude Code wrote holds the real values,
  and the next request's assistant history and `tool_result` went out masked again, with the
  same placeholders.

**Known limit (fast mode).** That run used rules-only detection. With the NER on, Claude
Code's own scaffolding still trips fail-closed checks: the NER reads words of its system
prompt and tool schemas (`Claude`, `boolean`, `9007199254740991`, `thin`, ...) as personal
data, and an identifier or a re-check hit refuses the request. The first three are fixed
(model-id words, JSON-Schema type names and integer limits are exempt in identifiers); the
rest are tracked as follow-ups to LAB-1605.
