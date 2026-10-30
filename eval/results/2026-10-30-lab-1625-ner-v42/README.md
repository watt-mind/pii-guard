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
