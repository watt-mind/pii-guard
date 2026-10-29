# File names, paths and tool names stay readable in agent text (2026-10-29)

LAB-1470, found in LAB-1469's run of real coding agents through the gateway
([harness matrix](../integrations/harness-matrix-2026-10-28.md)). **Before:** the NER encoder
read agent text as personal data. `contacts.json` came out as an `EMAIL` with no `@` in it,
`JSON`, `Claude`, `Codex` and `Muse Spark` as `PERSON`, and a `<project>-<uuid>` workspace path
segment as an `ID_DOCUMENT` or a `BANK_ACCOUNT`. The session sweep then masked every later
occurrence, the user's own prompt included. OpenCode's model saw "write the fixture file
`[[EMAIL_…]]` … run cat contacts`[[EMAIL_…]]`son" and refused the task twice, and Muse requests
carried 74 to 81 `PERSON` masks each. Values still round-tripped, but the model was reading a
different task.

- **The fix: structural guards, not a word list.**
  [`detect/ner_context.py`](../../src/pii_guard/detect/ner_context.py) checks the NER's spans
  before they leave the detector, so a rejected hit never becomes a session value. Each check
  looks at the shape of the text around the hit:
  - an `EMAIL` needs an `@` in its token (bracketed `[at]` is already `@` after
    normalization; a spelled-out `at … dot` also counts). An npm scope (`@scope/pkg`) is not an
    address;
  - a hit on a file extension (`json` in `contacts.json`) or on a code-fence language tag
    (```` ```json ````) goes;
  - in a file name or a path, an unvalidated number-like hit (ID, account, phone, tax number,
    email, birth date) goes. The checksum and format rules don't go through these guards, so
    a valid IBAN in `/exports/<IBAN>.csv` is still masked. A name-like hit in a path goes only
    when its segment also holds a digit (`claude-501`, `opencode-3f2b…`). `/Users/anna.kovacs/`
    stays masked;
  - a hit that is only part of a code identifier goes. That is a called chain
    (`JSON.stringify(`), a `snake_case` or `camelCase` part, or a lower-case or all-caps word in
    inline code. A hit that is the whole identifier (`anna_kovacs`) is kept.
- **A small software list, with no person names in it.**
  [`languages/software.tsv`](../../src/pii_guard/languages/software.tsv) has about 60 formats,
  languages, developer tools and coding agents (`JSON`, `YAML`, `Codex`, `OpenCode`,
  `Muse Spark`, `Claude Code`). A test checks that no single-word entry is a name in any
  language pack's lexicon. `Claude` alone is a given name, so it isn't on the list. It stays
  unmasked only in a software context: when the next word completes a listed name
  (`Claude Code`, `Claude API`), or when it sits in a list next to one (`Claude, Codex`,
  `Claude or Codex`). Lexicon names (`Anna or Codex`), honorifics and adjacent names follow the
  brand rules of LAB-1336 and are still masked.
- **The sweep follows the same guards.** The vault now records whether only the NER found a
  value. For such a value, the sweep skips occurrences the guards rule out. `Ask Claude to
  review` stays masked in prose, but the masking no longer spreads into `Claude Code` or
  `/tmp/claude-501/`. Once a value is confirmed by any other detector (rules, the LLM, a known
  value), it is swept everywhere again. `PII_GUARD_NER_AGENT_TEXT=false` turns both parts off.

Fast mode (rules + NER v2.0, `watt-mind/pii-guard-ner-xlmr-base@95f612a9ad65`), local CPU.
Each row compares a run on develop `f93a2e1` with a run on this branch. The agent-text rows
compare runs on the same commit with the guards off and on.

| set | leak (values) | over-masking (spans) | recall | precision |
| -- | -- | -- | -- | -- |
| agent-text, new (hu/en/de, 39 docs) | 0 → 0 of 60 | **28.3 → 0.0 % (26 → 0)** | 100 → 100 % | 71.7 → 100 % |
| agent-traffic-dev (dev) | 0.13 → 0.13 % (2 → 2) | 1.84 → 1.84 % (31 → 31) | 98.2 → 98.2 % | 96.0 → 96.0 % |
| smoke hu/en/de | 0.0 → 0.0 % | 1.09 → 1.09 % (2 → 2) | 93.3 → 93.3 % | 95.3 → 95.3 % |
| synth-sample hu/en | 0.0 → 0.0 % | 0.0 → 0.0 % | 96.4 → 96.4 % | 96.4 → 96.4 % |
| negative: brand names hu/en/de | — | 2 → 2 spans | — | — |
| negative: uncued numbers hu/en/de | — | 13 → 13 spans | — | — |
| agent docs + mini-repo replay (`integrations.overmask`, hu) | gold values 27 → 27 | 38 → 30 agent-doc spans, identifiers 4 → 0 | — | — |

Run records:
[agent-text before](../../eval/results/runs/2026-10-28-lab-1470-agent-text-before.json) /
[after](../../eval/results/runs/2026-10-28-lab-1470-agent-text-after.json),
[agent-traffic-dev before](../../eval/results/runs/2026-10-28-lab-1470-agent-traffic-dev-before.json) /
[after](../../eval/results/runs/2026-10-28-lab-1470-agent-traffic-dev-after.json),
[smoke before](../../eval/results/runs/2026-10-28-lab-1470-smoke-before.json) /
[after](../../eval/results/runs/2026-10-28-lab-1470-smoke-after.json),
[synth-sample before](../../eval/results/runs/2026-10-28-lab-1470-synth-sample-before.json) /
[after](../../eval/results/runs/2026-10-28-lab-1470-synth-sample-after.json),
[brand names before](../../eval/results/runs/2026-10-28-lab-1470-brand-names-before.json) /
[after](../../eval/results/runs/2026-10-28-lab-1470-brand-names-after.json),
[uncued numbers before](../../eval/results/runs/2026-10-28-lab-1470-uncued-numbers-before.json) /
[after](../../eval/results/runs/2026-10-28-lab-1470-uncued-numbers-after.json), and the replay
[before](../../examples/coding-agents/runs/2026-10-28-lab-1470-agent-docs-overmask-before.json) /
[after](../../examples/coding-agents/runs/2026-10-28-lab-1470-agent-docs-overmask-after.json).

- **The agent-text set is in-sample.** I wrote its 39 documents
  ([builder](../../eval/fixtures/build_agent_text.py)) from the harness requests while building
  the guards. The 0 % shows that the guards work on those shapes, not how far they generalize.
  Half the set is positives (a `cat` of a JSON file, a CSV in a code fence, a name in a file
  name, an IBAN in an export path): all 60 values stay masked, and a test checks that every
  gold value survives the guards or is found by the rules.
- **No other set moved.** Their texts hold no file names, paths or tool names, so leak and
  recall are unchanged everywhere. On the replay of the repository's own agent-facing docs,
  these 8 spans went: `contacts.json` and a URL's host name as `EMAIL`, two pieces of an npm
  scope, `Claude` in a quoted list and in `Claude Code`, and `Tesseract` and `YuNet`. The 27 values in the fictional mini-repo are all
  still masked.
- **Left as is.** Ports and sizes such as `8787` and `4096` tagged as `ADDRESS`, and `Luhn`
  as a `PERSON`, are not agent-text structure. They are filed as follow-ups.
- **Cost:** $0, offline, no model change. The records are marked dirty only because of the
  generated benchmark pages and the run records in the same working tree.
