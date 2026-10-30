# NER v4.2: a selection split that sees the smoke failures, birth-date labels fixed, targeted data (2026-10-30)

LAB-1625, the follow-up to LAB-1547 ([v4.1 results](../2026-10-30-lab-1547-ner-v41/README.md)).
v4.1-A1 fixed the `ADDRESS` false alarms, the hu-poa smoke miss and the Maltese gate, and passed
the eu gate, but failed the smoke gate (leak 0.58 %, over-masking 2.16 % against v2.0's 0.00 /
1.08) and over-masked agent-traffic-dev (3.21 % against 1.66 %), mostly `DATE_OF_BIRTH` (2 to
29). A2 failed the same way. The published model is v2.0
(`watt-mind/pii-guard-ner-xlmr-base@95f612a9`).

## 1. Model selection repaired first: the v4.2 selection split

The LAB-1417 smoke-style split scored 0.00 % leak for v2.0, A1 and A2 alike, so it could not
see what failed on smoke. `training/ner/selection_v42.py` writes a new dev-side split (synthetic,
seeded, `eval/generated/selection-v42/`, 685 hu/en/de documents) with a smaller v1 base and
one slice per v4.1 failure mode, from `training/ner/v42_gen.py` pool `sel`:

| Slice | Languages | Documents | What it holds |
|---|---|--:|---|
| `base` | hu, en, de | 135 | `smoke_style_dev.build`, seed 1625 |
| `de-genitive` | de | 200 | German genitive names: `Annas`, `Frau Beckers`, `Jonas'` (ending outside the span) |
| `hu-surname-given` | hu | 80 | a common-word surname with an inflected given name (`Fekete Eleknek`), many given names outside the lexicon (LAB-1606, LAB-1646) |
| `dates` | hu, en, de | 180 | a birth date (`DATE_OF_BIRTH`) next to 1-3 other dates (`O`): appointments, invoices, deadlines and old start dates; a quarter hold no birth date |
| `numbers` | hu, en, de | 90 | order, customer and reference numbers (`O`), half the time next to an IBAN |

No smoke, gate or test document is read for its text. Only the person names of the smoke and
inflection fixtures are read, so that none is reused. A document naming a person whose full name
occurs in any evaluation text is redrawn, and `decontam.py` dropped 0 of 685 documents. The
training generators (pool `train`) use other sentence frames and the other half of every name
list, and `train.py` gets the split as `report_dev`, so no training document can copy one.

**Calibration on the three known models** (fast mode, rules + NER, CPU, this branch). The split
was sized on these numbers: a first version with 80 genitive documents ranked them the same way
on leak (2 / 3 / 3 values), but by one value only, so the genitive slice grew to 200 documents
and 16 short given names were added before any v4.2 model existed.

| Model | selection-v42 leak % (values) | over-masking % | real smoke gate (LAB-1547) leak / over-masking |
|---|--:|--:|--:|
| v2.0 | **0.00** (0 of 1,868) | **6.63** | 0.00 / 1.08 |
| v4.1-A1 | 0.21 (4) | 9.61 | 0.58 / 2.16 |
| v4.1-A2 | 0.16 (3) | 10.08 | 1.16 / 2.20 |

It ranks v2.0 above A1 and A2 on leak and on over-masking, as the smoke gate does. The A1/A2
order on leak is reversed, but that is one value on each side. Per slice
([`selection/`](selection/)):

- **`de-genitive`:** A1 and A2 leak 3 and 2 genitive names (`Idas`-type short given names), and
  v2.0 leaks none.
- **`dates`:** `DATE_OF_BIRTH` false alarms go from 67 (v2.0) to 116 (A1) and 130 (A2). v2.0's
  are old start dates, the hard case. A1 and A2 add recent dates (`Nächster Termin: 2025-…`),
  the agent-traffic failure.
- **`numbers`:** `PHONE` and `BANK_ACCOUNT` false alarms on reference numbers rise from 3 and 1
  to 14 and 10 (A1). The rest of this slice's over-masking comes from rules (Hungarian TAJ, tax
  and ID formats) and is the same for every model.
- **`base` and `hu-surname-given`:** 0 leaks for all three. They are regression guards.
  LAB-1606's rule already finds the `Fekete Eleknek` shape in fast mode.

The over-masking rate is high in absolute terms because the `dates` and `numbers` slices are
made of hard negatives. Only the differences between models mean anything.

## 2. Protocol (fixed and committed before any v4.2 model was trained or scored)

The LAB-1535 / LAB-1547 gates, **unchanged**. v2.0 is re-scored on this commit (records keyed
`rules+ner:xlmr-base-v2-hn@rescore=lab-1625`): LAB-1597 regenerated agent-traffic after LAB-1547.

1. **Gates, pass/fail, against v2.0 on this commit** (`gates_v4.py`):
   - hu/en/de smoke leak ≤ v2.0, and smoke over-masking ≤ v2.0 + 0.5 pp;
   - hu-inflection leak ≤ v2.0;
   - eu, per language (lv lt hr sl fr es it nl ro mt ga, and `en-court-smoke`): leak ≤ v2.0 and
     over-masking ≤ v2.0 + 2 pp; and the eu total leak **strictly lower** than v2.0's;
   - **beats v2.0 on agent-traffic-dev:** leak ≤ v2.0 *and* over-masking ≤ v2.0, at least one
     strictly lower;
   - CPU p95 ≤ 1.2× v2.0 in one alternating `modal_latency.py` run, only for a candidate that
     passes every accuracy gate.
2. **Selection, among the candidates that pass every gate:** the lowest leak on the
   **selection-v42 split** wins, then the lower over-masking there, then the earlier candidate in
   the list below (`gates_v4.py --selection`). This replaces agent-traffic-dev as the ranking set.
   agent-traffic-dev stays a gate.
3. **MAPA EUR-Lex, all 21 languages, report-only.** It is scored on this Mac in one process and
   never uploaded (the LAB-1527 allowlist refuses any `mapa` path). It is not a gate and chooses
   nothing.
4. **Never read for design:** agent-traffic-dev, the smoke and eu gate sets, and every test
   set. The failure modes come from the LAB-1547 README (counts and types only).
5. **A tie is not a win.** It is reported for the owner to decide. **Nothing is published** and
   the production pin is not changed: a winner goes to the owner.

## 3. Candidates, fixed now. None is added after a result is seen.

All three trained candidates use **v4.1-A1's recipe and mix**, unchanged:
- v2.0 warm start at its pinned revision, `train.py` with decontamination on;
- 1 epoch, lr 1e-5, batch 16, warmup 0.1, weight decay 0.01, seed 13, bf16, one A10G on Modal;
- OpenPII EU and kiji `ADDRESS` spans out of the loss.

184 of A1's 186 files rebuild byte for byte. The other two are the hu-poa set, which changes
because LAB-1597 fixed Hungarian vowel harmony. Each candidate adds the v4.2 targeted files and a
birth-date treatment of the kiji, nym and E3 rows (`training/ner/v42_data.py`, report in
[`data.json`](data.json)). In selection order:

- **B1** (`v42-b1.toml`): the **implausible** uncued third-party `DATE_OF_BIRTH` spans are
  taught as `O`. That is 563 spans with no year or a year from 2010 on, plus 93 without a digit.
  The v4.2 targeted files are added once.
- **B2** (`v42-b2.toml`): **every** uncued third-party `DATE_OF_BIRTH` span is kept out of the
  loss (2,735 spans). The targeted files are added once.
- **B3** (`v42-b3.toml`): B1 with the targeted files twice.
- **B4**: a weight soup, 0.5 v2.0 + 0.5 B1 (`soup.py`, made locally, no GPU). It pulls B1 back
  towards v2.0's calibration.

**Why the birth-date labels.** Measured on the training files before any run (`v42_data.py`
docstring): kiji, nym and E3 hold 9,357 `DATE_OF_BIRTH` spans. 2,642 of them have no birth word
in the 50 characters before them (back to the previous date). Some are plainly other dates: a
contract signing, a payment deadline, a flight. 93 E3 spans hold no digit at all (a birthplace).
A1's dev F1 on that type was 0.61. The s11 replay, pii-anon and the targeted sets are not
changed (s11: 1,406 of 1,426 birth dates cued; mt-dob writes its own cues).

**Targeted data** (`v42_data.py targeted`, seed 1625, template-based, no model call, [`targeted.json`](targeted.json)):

| Slice | Language | Train | Dev |
|---|---|--:|--:|
| `de-genitive` | de | 1,500 | 100 |
| `hu-surname-given` | hu | 1,500 | 100 |
| `dates` | hu, en, de | 800 each | 50 each |
| `numbers` | hu, en, de | 300 each | 30 each |

That is 6,300 training documents. No full name in them occurs in any evaluation text or in the
selection split (a draw that does is redrawn), and `decontam.py` dropped 0 documents.

## Budget and stop rules

- **Modal:** $1.92 of credit plus a $12.50 limit that the owner is billed for. **This ticket's
  hard cap is $11.**
  - One A10G per run, at most 3 training runs, each with a hard timeout of 45 minutes
    (`PII_GUARD_TRAIN_TIMEOUT_S=2700`).
  - Estimate from v4.1: A1 cost $0.51 for 174,430 documents (about 33 minutes of app time). B1
    and B2 have 180,730 documents (+3.6 %), about $0.53 each. B3 has 187,030 documents (+7.2 %),
    about $0.55. With one latency run, the projected total is **about $1.70**. The worst case,
    every run hitting its timeout, is $2.60.
  - Stop if the measured total (`modal billing report`) would go over $11.
- **Fireworks / Meta:** not used. The targeted data is template-based (cap $8, $0 planned).
- Upload only through the LAB-1527 allowlist. MAPA and TAB text never leaves the machine.

## Reproduce

```
uv run --no-sync python training/ner/openpii_eu.py --source <openpii train.jsonl>
uv run --no-sync python training/ner/openpii.py --source <openpii train.jsonl>
uv run --no-sync python training/ner/negatives_eu.py && uv run --no-sync python training/ner/negatives.py
uv run --no-sync python training/ner/court_surnames_en.py
uv run --no-sync python training/ner/v41_data.py targeted
uv run --no-sync python training/ner/selection_v42.py write
uv run --no-sync python training/ner/v42_data.py targeted --json eval/results/2026-10-30-lab-1625-ner-v42/targeted.json
uv run --no-sync python training/ner/v42_data.py build --json eval/results/2026-10-30-lab-1625-ner-v42/data.json
PII_GUARD_TRAIN_TIMEOUT_S=2700 modal run training/distill/modal_train.py --config training/ner/v42-b1.toml \
    --gpu A10G --data <the --data line in the config header>          # and b2, b3
uv run --no-sync python training/ner/soup.py --a <v2.0 snapshot> --b models/ner/pii-guard-ner-xlmr-base-v42-b1 \
    --alpha 0.5 --out models/ner/pii-guard-ner-xlmr-base-v42-b4
PII_GUARD_NER_DEVICE=cpu uv run --no-sync python training/ner/selection_v42.py score --candidate v42-b1 \
    --model models/ner/pii-guard-ner-xlmr-base-v42-b1 --json eval/results/2026-10-30-lab-1625-ner-v42/selection/v42-b1.json
PII_GUARD_NER_DEVICE=cpu uv run --no-sync python training/ner/eval_v3.py score --ticket LAB-1625 \
    --candidate v42-b1 --model models/ner/pii-guard-ner-xlmr-base-v42-b1 --record \
    --sets smoke inflection agent-traffic-dev eu-smoke eu-inflection en-court mapa-eur-lex
uv run --no-sync python training/ner/gates_v4.py --ticket LAB-1625 --date 2026-10-30 \
    --candidates v42-b1 v42-b2 v42-b3 v42-b4 --selection eval/results/2026-10-30-lab-1625-ner-v42/selection \
    --json eval/results/2026-10-30-lab-1625-ner-v42/gates.json
```

## Result: B3 passes every gate and is selected. It goes to the owner; nothing is published

`gates_v4.py --ticket LAB-1625 --selection selection/ --latency latency-cpu.json` on the run
records ([`gates.json`](gates.json)). **B3 is the first candidate since v2.0 to pass every v4
gate**, the latency gate included. It is not published, and the production pin
(`watt-mind/pii-guard-ner-xlmr-base@95f612a9`) is unchanged: publishing needs the owner.

The table shows leak % / over-masking %, rules + NER, fast mode, CPU, on this commit. v2.0 was
re-scored here. Run records are in `eval/results/runs/2026-10-30-lab-1625-<set>-<candidate>.json`
and the summaries in [`stage1/`](stage1/).

| Candidate | smoke leak ≤ 0.00 | smoke over ≤ 1.58 | inflection leak ≤ 2.0 | eu per language | eu total leak < 0.95 | agent-traffic-dev (beat 0.13 / 1.66) | p95 ≤ 1.2× | selection-v42 leak / over | |
|---|--:|--:|--:|---|--:|--:|--:|--:|---|
| v2.0 (published) | 0.00 | 1.08 | 2.0 | – | 0.95 | 0.13 / 1.66 | – | 0.00 / 6.63 | |
| B1 (implausible DOB → `O`) | 0.00 | **1.63 fail** | 0.0 | pass | 0.32 | 0.13 / 1.19 beats | – | 0.00 / 1.83 | no |
| B2 (uncued DOB ignored) | 0.00 | **2.16 fail** | 0.0 | pass | 0.32 | 0.13 / 1.25 beats | – | 0.00 / 1.83 | no |
| **B3** (B1, targeted ×2) | **0.00** | **1.09** | **0.0** | **pass** | **0.32** | **0.13 / 0.66 beats** | **0.94** | **0.00 / 1.58** | **selected** |
| B4 (soup 0.5 v2.0 + 0.5 B1) | 0.00 | 1.09 | 0.0 | pass | 0.32 | **0.19** / 1.20 fails | – | 0.00 / 3.46 | no |

Latency was measured on an idle Modal CPU container, alternating per message
([`latency-cpu.json`](latency-cpu.json)): v2.0 p95 77.5 ms, B3 73.0 ms. It was run only for B3,
the only candidate that passed the accuracy gates.

Against v2.0, B3:

- **Smoke:** the same leak (0.00) and over-masking (1.09 vs 1.08). v4.1's German name leak is
  gone.
- **Inflection:** leak 2.0 → 0.0.
- **agent-traffic-dev:** over-masking 1.66 → 0.66, with the same leak.
- **eu:** total leak 0.95 → 0.32 (3 → 1 of 315 values; the one left is in fr). Maltese
  over-masking 12.9 → 0, Irish 7.7 → 0.
- **Selection split:** `dates` false alarms 67 → 1, and `numbers` `PHONE`/`BANK_ACCOUNT` 3/1 → 3/0.

**MAPA EUR-Lex (report-only, 21 languages, 42 documents, scored locally and never uploaded):**

| | v2.0 | B1 | B2 | B3 | B4 |
|---|--:|--:|--:|--:|--:|
| leak % | 8.24 | 8.78 | 9.32 | 8.51 | **5.54** |
| over-masking % | 55.5 | 45.5 | 45.5 | **44.7** | 48.5 |

B3 leaks slightly more MAPA names than v2.0 (8.51 against 8.24) and much less than v4.1-A1 did
on its own commit (5.9). The targeted data costs part of A1's MAPA gain. MAPA is not a gate.

What the round shows, read after the choice:

- **The birth-date fix works through the data.** Every v4.2 candidate cuts the `dates` false
  alarms from 116 (A1) to 1-3, and agent-traffic-dev over-masking falls below v2.0's.
- **The dose of targeted data decides the smoke over-masking.** B1 and B3 differ only in
  copies (1 vs 2), and smoke over-masking goes 1.63 → 1.09.
- **Ignoring uncued birth dates (B2) is worse than teaching the implausible ones as `O`.**
- **The soup (B4)** cuts the MAPA leak by a third (8.24 → 5.54) but leaks one more agent-traffic-dev value.
- **The selection split** ranks B3 first among the passers. Its `numbers` slice still
  over-masks about 15 %, mostly from rules (Hungarian TAJ, tax and ID formats on order numbers).
  That is not NER, and it is filed separately.

### Post-hoc check, not a protocol candidate: dev-calibrated thresholds on B3

The LAB-1650 finding (thresholds alone don't fix v4.1) prompted this check. `thresholds_v33.py`
calibration was run on B3, on dev files only ([`thresholds-b3.json`](thresholds-b3.json)): s11
hu/en dev, OpenPII hu/en/de dev and the v4.2 targeted dev files, 1,631 documents. The selection
split and the gate sets were not used. **`hu-poa-dev` is left out:** its regenerated copy does
not match LAB-1547's hash, because LAB-1597 changed Hungarian vowel harmony.

The table raises most types to 0.9. It is scored as `v42-b3t` on the same records:

| | smoke leak / over | agent-traffic-dev leak / over | selection-v42 leak / over |
|---|--:|--:|--:|
| B3 | 0.00 / 1.09 | 0.13 / 0.66 | 0.00 / 1.58 |
| B3 + thresholds | **0.58** / 0.56 | **1.86** / 0.49 | 0.00 / 1.23 |

The thresholds cut over-masking further but fail the smoke and agent-traffic leak gates. **Raw
B3 stays the pick.** This variant was added after results were seen, so it could not have been
selected anyway.

## Compute and cost

| Provider | What | Cost |
|---|---|--:|
| Modal | B1, B2, B3: one A10G each, about 25 min of training (`modal billing report`: $0.510, $0.522, $0.534). Latency gate: one CPU container, $0.007 | **$1.57** (cap $11; estimate was $1.70) |
| Fireworks | not used | $0 |
| Meta Model API | not used | $0 |
| Local CPU | data, soup B4, all scoring, threshold calibration, one process at a time | $0 |

No deployment was created. Each Modal app was ephemeral (`modal run`) and stopped when it
returned.

- Decontamination: `train.py` dropped 0 of 179,895 distinct train and dev documents on Modal.
- Weights sha256: B1 `458be3c9…`, B2 `439a9034…`, B3 `40e8406c…`, B4 `c1ec9758…`.
- The checkpoints are on the `pii-guard-ner-runs` volume (`pii-guard-ner-xlmr-base-v42-b1`
  to `-b3`). B4 is local only. None is published.
