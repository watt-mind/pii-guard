# Real harnesses through the gateway: results (2026-10-28)

> Re-run on 2026-10-29 with the placeholder note and the agent-text guards in: refusals 7 of 15
> → 0 of 10 agent turns. See [harness-matrix-2026-10-29.md](harness-matrix-2026-10-29.md)
> (LAB-1475). This page is kept as the record of the first run.

LAB-1469. Each coding agent installed on a developer Mac ran non-interactively through a local
`pii-guard up`, on a synthetic task with fictional personal data, against the Meta Model API.
The scripted end-to-end tests ([`tests/integrations/`](../../tests/integrations/)) pin one
version per client and a mock model; this run used the versions people actually have, the
real model and the published NER.

## Setup

| | |
|---|---|
| Date | 2026-10-28 to 2026-10-29 (UTC) |
| Gateway | `pii-guard up --upstream-url <recorder> --traffic-log masked`, branch `fix/LAB-1469-harness-e2e` |
| Detection | fast mode: rules + NER `watt-mind/pii-guard-ner-xlmr-base@95f612a9ad65` |
| Language | `hu` for clients that send no headers (Muse Code, Codex, OpenCode), `en` for pi (`connect` writes the header) |
| Upstream | Meta Model API, `muse-spark-1.3` (Muse's `--check` picks the catalog's first model, `muse-wonder-1.0`) |
| Between gateway and upstream | a local recorder that keeps every body the gateway forwards and adds the key; the gateway itself held no key |
| Upstream calls | 108 in total (budget 150): 97 agent requests, 11 `--check` canaries; all fictional data, and none of the 9 values in any of them |
| Isolation | every client ran with a scratch `HOME` (and `XDG_*`, `CODEX_HOME`, `PI_CODING_AGENT_DIR`, `--muse-dir`); cwd a scratch git repo; pi and OpenCode under a `sandbox-exec` profile that denies writes to the user's home, Codex and Muse in their own workspace sandboxes. No real config was read or written |

The task: `customers.md` holds two fictional customers (a Hungarian name, e-mail, IBAN,
adóazonosító jel and TAJ szám; a German name, e-mail, IBAN and Steuer-ID: 9 values, all masked
in fast mode). Turn 1: "create `contacts.json` from it, `cat` it, reply with the German
customer's e-mail". Turn 2, in the same conversation: "with your edit tool, insert
`"verified": true` after the first e-mail". The project's `AGENTS.md` says placeholders are
restored locally ([pi.md](pi.md#the-end-to-end-test)).

## Matrix

After the fixes below. "Masked" means none of the 9 values appeared in any body the
upstream received.

| Check | Codex | pi | OpenCode | Muse Code | Claude Code |
|---|---|---|---|---|---|
| Version | 0.163.0 ¹ | 1.3.0 | 1.18.26 | 1.4.14 (`1.4.14-R7309.1`) | 2.1.289 |
| API | Responses | Chat Completions | Chat Completions | Responses | Anthropic Messages |
| Request masked upstream | pass (0 of 9, 9 requests) | pass (0 of 9, 18 requests) | pass (0 of 9, 19 requests) | pass (0 of 9, 51 requests) | not testable ² |
| Restored values in the answer | pass | pass | pass via `--check`; in the task the model declined to repeat the values ³ | pass | not testable |
| Streaming | pass | pass | pass | pass | not testable |
| Multi-turn | pass (`exec resume --last`) | pass (`-c`) | pass (`-c`) | pass (same `--session-id`) | not testable |
| Tool calls and file edits | pass (`exec_command`, `apply_patch`; file has all values, no placeholder) | pass (`write`, `edit` with a restored `oldText`) | pass (`read`, `write`, `edit` with a restored absolute `filePath`) | pass (`read_file`, `write_file`, `edit_file`) | not testable |
| `pii-guard connect <client> --check` | pass (new in this ticket) | pass | pass (new in this ticket) | pass | n/a: `--print` says the Messages API isn't served |

¹ The `codex` on the machine (0.116.0) does not start: its native binary is missing from the
npm install (`spawn .../codex-darwin-arm64/.../codex ENOENT`). The run used the pinned
0.163.0, installed with npm into a scratch prefix as the e2e test does.

² Claude Code speaks `POST /v1/messages`, which the gateway doesn't serve. Pointed at it with
`ANTHROPIC_BASE_URL` and a dummy `ANTHROPIC_API_KEY` (scratch `CLAUDE_CONFIG_DIR`, no login
used), it fails with "There's an issue with the selected model", a misleading message
([LAB-1313](https://linear.app/watt-mind/issue/LAB-1313)). Nothing reached the upstream.

³ Model refusals are counted below; they are the model's choice, not a gateway error (every
request was answered 200).

## What broke, and the fixes

Before the fixes, three of the four OpenAI-API clients could not finish a task:

| Client | Failure (before) | Cause | Fix |
|---|---|---|---|
| pi | refused on the 4th request, `messages.6.tool_calls.0.id: personal data detected in an identifier` | the NER reads an upstream call id (`call_<32 hex>`) as a PHONE: 37 of 300 random ids | upstream-issued ids are remembered per vault session and forwarded as sent |
| Muse Code | refused from the 3rd request (`input.14.call_id`); Muse retried 10 times over 4 minutes, then gave up | the same, in Responses `call_id` | the same |
| Codex | refused on the **first** request (`input.0.id`) | Codex mints its own message ids (`msg_<uuid v7>`): 59 of 200 read as a PHONE | NER hits are dropped in identifiers that are a prefixed UUID or hex run |
| OpenCode | every agent request refused (`tools.0.function.parameters.properties.1.minimum`) | zod writes `Number.MAX_SAFE_INTEGER` (`±9007199254740991`) as schema bounds; the NER reads it as a BANK_ACCOUNT | the same rule for JSON-number identifiers |
| all | `connect pi --gateway URL --check` (as `pii-guard up` prints it) checked the default session, not the path session pi uses | `--gateway` replaced the configured base URL | the same gateway keeps the configured session |
| Codex, OpenCode | `connect codex --check` refused: "--check is for pi and muse-code" | no config file to read | `--check` sends the canary the way their block does |

All fixes are in [`gateway/opaque_ids.py`](../../src/pii_guard/gateway/opaque_ids.py) and
[`integrations/cli.py`](../../src/pii_guard/integrations/cli.py), with regression tests in
[`tests/gateway/test_opaque_ids.py`](../../tests/gateway/test_opaque_ids.py) and
[`tests/integrations/test_connect_cli.py`](../../tests/integrations/test_connect_cli.py). Both
id rules are narrow: an id the upstream wrote can't tell it anything new, and a UUID, hex run
or number has no room for a name or an address; rules, the LLM detector and known values still
check them, and any other identifier still fails closed.

## What still goes wrong (filed)

- **Over-masking in agent text** ([LAB-1470](https://linear.app/watt-mind/issue/LAB-1470)).
  The NER tags `contacts.json` as an EMAIL (no `@`), `JSON`, `Claude`, `Codex` and
  `Muse Spark` as PERSON, and workspace path segments as ID_DOCUMENT or BANK_ACCOUNT; the
  session sweep then masks every later occurrence, the user's prompt included. Values still
  round-trip (the files had the right names), but the model reads a different task: OpenCode
  refused it twice until the file was renamed, and one Muse run (effort `low`) wrote invented
  names into the file.
- **Refusals** ([LAB-1471](https://linear.app/watt-mind/issue/LAB-1471)). `muse-spark-1.3`
  sees the type in `[[NATIONAL_ID_HU_TAJ_...]]` and declines to copy or repeat: 7 of 15 agent
  turns ended in a full or partial refusal (pi 4 of 6, OpenCode 3 of 4, Muse 0 of 3, Codex 0
  of 2).
- **Claude Code** needs a Messages API adapter
  ([LAB-1313](https://linear.app/watt-mind/issue/LAB-1313)).

## Notes for each client

- **Codex:** no config file; `-c` flags on the command line, `exec --sandbox workspace-write`.
  It warns that it has no metadata for `muse-spark-1.3` (harmless). Codex's edits go through
  `exec_command` (`apply_patch` as a shell call).
- **pi:** `pi -p` waits on stdin when stdin is an open pipe; run it with `< /dev/null` in
  scripts.
- **OpenCode:** sends no pii-guard headers, so it gets the gateway's default language (`hu`
  here). Its first request is a side call without tools that titles the session.
- **Muse Code:** `--trust-workspace` loads `AGENTS.md`; without it Muse skips the file.
  `--approval-judge off` keeps the approval judge from making extra model calls. Muse's
  shell sandbox can't start inside another `sandbox-exec` profile, so it ran in its own.
