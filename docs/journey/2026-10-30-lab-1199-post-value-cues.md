# Cues after the value: Hungarian `számon`, `számra`, `számú` + noun (2026-10-30)

LAB-1199, a follow-up to LAB-1170's context-cued numbers. **Before:** a number was masked
without a checksum only right *after* a cue word. Hungarian often puts the cue after the
value: `a +36.37.393.9102 számon`, `a 0136-13 051 0758 számra`, `a KA652524 számú
útlevelére`. Those stayed unmasked in rules mode whenever the checksum or numbering plan
failed.

- **`cues.tsv` takes an optional third column `after`**
  ([`languages/cues.py`](../../src/pii_guard/languages/cues.py)): the value must stand right
  before the cue, spaces only between, with the same shapes and score (0.6). A phone before
  such a cue also needs a `+` or `0` prefix, so `a 2026/4471 számon iktatott` stays a file
  number. A bare `számú` names nothing (`a 4500123456 számú szerződés`); it is a cue only with
  its noun (`számú útlevél*`, `számú bankszámla*`, `számú telefon*` ...).
- Three new Hungarian negatives in `eval/fixtures/negative/hu-uncued-numbers.jsonl` (case,
  file and contract numbers before `számú`, `számon`, `számra`); the whole negative set stays
  unmasked.
- Short account numbers after `Kontonummer` / `account number`: not accepted. The negatives
  hold 10-digit customer and order numbers one cue word away, and SEPA text uses IBANs.

Rules mode and fast mode (rules + NER v2.0), `pii-guard eval`, before is `develop` `4cd1181`,
after is this branch (run records `eval/results/runs/2026-10-30-lab-1199-post-value-cues-*`).

| set | rules leak (values) | rules over-masked | fast leak | fast over-masked |
| -- | -- | -- | -- | -- |
| Ai4Privacy de/en/hu (600 docs) | 1376/2185 → **1362/2185** | 1 → 1 | 8/2185 → 8/2185 | 28 → 28 |
| Ai4Privacy hu (200 docs) | 492/752 → **478/752** | 0 → 0 | unchanged | unchanged |
| smoke de/en/hu | 71/173 → 71/173 | 0 → 0 | 0 → 0 | 2 → 2 |
| synth-sample en/hu | 109/253 → 109/253 | 0 → 0 | 0 → 0 | 0 → 0 |
| company-names hu | 1/40 → 1/40 | 0 → 0 | 0 → 0 | 0 → 0 |

Rules-mode Ai4Privacy leak falls from 63.0 to 62.3 % (hu 65.4 → 63.6 %) with no new
over-masking. Fast mode is unchanged: NER v2.0 already masks these values.
