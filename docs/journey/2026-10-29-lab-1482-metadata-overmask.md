# Request metadata and commands stay readable in agent text (2026-10-29)

LAB-1482, found in LAB-1475's re-run of real coding agents through the gateway
([harness matrix](../integrations/harness-matrix-2026-10-29.md), "What still goes wrong").
**Before:** after LAB-1470 the task text was clean, but the NER encoder still read request
metadata and commands as personal data. Codex 0.163's `prompt_cache_key` and `client_metadata`
ids came out as `"[[PHONE_…]]-abc6-…"`: the first segments of a bare UUID read as a phone
number. A 13-digit `turn_started_at_unix_ms` came out as a `BANK_ACCOUNT`, and `false` inside a
JSON string as a `PERSON`. In OpenCode 1.18, `python3` in a `bash` command and the `89` in the
model's own `len 89` came out as `PERSON`, and so did the npm scope in pi 1.3's install path
(`node_modules/@<scope>-works/pi-coding-agent/`). No value leaked and no agent changed what it
did. But a masked `prompt_cache_key` is a different cache key in every session, so the
upstream's prompt cache missed.

- **More structural guards, not a word list.**
  [`detect/ner_context.py`](../../src/pii_guard/detect/ner_context.py) gets a sixth group of
  checks. Like LAB-1470's, each looks at the shape of the text around an NER hit:
  - a hit inside a bare UUID (`8-4-4-4-12` hex, anywhere in the text) goes. Hex digits and
    dashes hold no name, and a phone number inside a UUID is not one. A hit that runs out of
    the UUID into the next word is kept;
  - a hit that is exactly `true`, `false` or `null` in value position (after `:`, `=`, `,` or
    `[`) goes;
  - a number-like hit that is a whole epoch timestamp (10 or 13 digits) and the value of a time
    field (`*_ms`, `*_at`, `*_ts`, `*unix*`, `*time*`, `*timestamp*`, `*epoch*`) goes. The same
    13 digits under `"account"` or in prose stay masked;
  - a name-like hit that is a whole lower-case executable name at command position goes. That
    means after `&&`, `||`, `|`, `;`, `$(`, a `$` prompt, `sudo`/`env`/`exec`/`xargs`, or first
    in a `"command"` value. A name in an argument (`--to "Kovács Réka"`, `echo Teszt Elek`) is
    not at command position and stays masked, and so is a capitalised word after `&&`;
  - a `PERSON` or `ORGANIZATION` hit with no letter in it goes;
  - in a path, a name-like hit in the package segment right after `node_modules/` (or in its
    `@scope` and the package after it) goes. `/Users/anna.kovacs/…/node_modules/…` keeps the
    home directory masked.
- **Whole-id values in masked fields.**
  [`gateway/opaque_ids.py`](../../src/pii_guard/gateway/opaque_ids.py) gets a third rule:
  `prompt_cache_key`, `user`, `safety_identifier` and `metadata`/`client_metadata` values that
  are exactly a prefixed UUID, or a hex run with a hex letter in it, drop model hits, as
  identifier slots already did. The rules, the LLM and known values still apply. These fields
  stay masked like free text, because a client can put anything there. A digit-only value
  (a phone number, a card) is not exempt. So `prompt_cache_key` is not treated as an opaque id
  by its key, only by its shape.
- **The sweep follows the same guards**, through `sweep_vetoed`. A `false` or a UUID segment
  that the NER flagged once is no longer swept into every later occurrence.

Fast mode (rules + NER v2.0, `watt-mind/pii-guard-ner-xlmr-base@95f612a9ad65`), local CPU.
Each row compares a run before the change (develop `0be220a` plus the new fixture cases, commit
`540d4d6`) with a run on this branch (`10c53ad`). Both commits are from before the branch was rebased on PR #221, which only touches gateway restore code.

| set | leak (values) | over-masking (spans) | recall | precision |
| -- | -- | -- | -- | -- |
| agent-text, 30 new docs (hu/en/de, 69 docs) | 0 → 0 of 93 | **17.5 → 0.0 % (21 → 0)** | 100 → 100 % | 82.5 → 100 % |
| agent-traffic-dev (dev) | 0.13 → 0.13 % (2 → 2) | 1.84 → 1.84 % (31 → 31) | 98.2 → 98.2 % | 96.0 → 96.0 % |
| smoke hu/en/de | 0.0 → 0.0 % | 1.09 → 1.09 % (2 → 2) | 93.3 → 93.3 % | 95.3 → 95.3 % |
| synth-sample hu/en | 0.0 → 0.0 % | 0.0 → 0.0 % | 96.4 → 96.4 % | 96.4 → 96.4 % |
| negative: brand names hu/en/de | — | 2 → 2 spans | — | — |
| negative: uncued numbers hu/en/de | — | 13 → 13 spans | — | — |
| agent docs + mini-repo replay (`integrations.overmask`, hu) | — | 58 → 58 masked values | — | — |

Run records:
[agent-text before](../../eval/results/runs/2026-10-29-lab-1482-agent-text-before.json) /
[after](../../eval/results/runs/2026-10-29-lab-1482-agent-text-after.json),
[agent-traffic-dev before](../../eval/results/runs/2026-10-29-lab-1482-agent-traffic-dev-before.json) /
[after](../../eval/results/runs/2026-10-29-lab-1482-agent-traffic-dev-after.json),
[smoke before](../../eval/results/runs/2026-10-29-lab-1482-smoke-before.json) /
[after](../../eval/results/runs/2026-10-29-lab-1482-smoke-after.json),
[synth-sample before](../../eval/results/runs/2026-10-29-lab-1482-synth-sample-before.json) /
[after](../../eval/results/runs/2026-10-29-lab-1482-synth-sample-after.json),
[brand names before](../../eval/results/runs/2026-10-29-lab-1482-brand-names-before.json) /
[after](../../eval/results/runs/2026-10-29-lab-1482-brand-names-after.json),
[uncued numbers before](../../eval/results/runs/2026-10-29-lab-1482-uncued-numbers-before.json) /
[after](../../eval/results/runs/2026-10-29-lab-1482-uncued-numbers-after.json), and the replay
[before](../../examples/coding-agents/runs/2026-10-29-lab-1482-agent-docs-overmask-before.json) /
[after](../../examples/coding-agents/runs/2026-10-29-lab-1482-agent-docs-overmask-after.json).

- **The agent-text set is in-sample, and only part of it reproduces offline.** I wrote the 30
  new documents ([builder](../../eval/fixtures/build_agent_text.py)) from the LAB-1475 requests.
  Six are negatives in each language: a cache key, Codex turn metadata, `client_metadata` with
  an escaped JSON string, an OpenCode `bash` call, its debug output, and pi's install path.
  Four are positives: a name and a phone number in the same metadata JSON as a UUID and a
  timestamp, a UUID next to a phone number and an IBAN in prose, a name next to
  `&& python3`, and a name before a `node_modules/@scope` path. All 93 values stay masked. On
  these short documents the encoder reproduces the UUID and timestamp hits (21 spans, all
  gone). It does not reproduce the `false`, `python3`, `len 89` and `@scope` hits, which came
  from long real requests and the session sweep. Those four shapes are covered by unit tests
  with the spans the harness logged ([tests](../../tests/detect/test_ner_context.py),
  `TestMachineTokens`).
- **Recall did not move.** No standard set holds these shapes, so leak, recall and
  over-masking are the same on every one of them, and the replay masks the same 58 values.
- **Left as is.** `pi` (the harness's own name) read as a `PERSON` in "pi's documentation"
  while I built the fixture. It is a software name that is also a short word, so it needs a
  decision rather than a guard. It is filed as a follow-up.
- **Cost:** $0, offline, no model change.
