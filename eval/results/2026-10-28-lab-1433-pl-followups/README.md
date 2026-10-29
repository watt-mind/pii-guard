# Polish pack follow-ups (LAB-1433)

Follow-ups from the `pl` pack (LAB-1400, [results](../2026-10-28-lab-1400-pl-pack/README.md)):

1. **NER number lexicon** (`detect/ner_numbers.py`): Polish order, invoice, shipment, parcel,
   booking, ticket and transaction words in `_NEGATIVE`, so an NER number right after one is
   dropped. `numer` is in `_GENERIC` and `_FILLER`: before, the Polish cues (`numer konta`,
   `numer dowodu` ...) made it a positive cue word on its own.
2. **Shared reference helper** (`detect/rules/_base.py`): the Polish words, `numer`, `PLN` and
   `zł`, so `reference_or_amount_before` covers Polish for every rule. The `pl` pack's local
   copy is gone.
3. **TAJ scope** (`languages/hu/rules.py`): a TAJ number without its label runs for Hungarian
   text only. A labelled one still runs everywhere. The Polish phone score goes back from
   0.82 (a workaround that beat the unlabelled TAJ) to 0.8.
4. **Cue date guard** (`languages/cues.py`): a date inside a cued value needs digit boundaries
   and a month and day in range, so `05936/42/00` after `prawo jazdy` is masked.

*Before* is `origin/develop` at `6254fd1`, *after* is this branch. Fast mode is rules + the
published NER v2.0 (`watt-mind/pii-guard-ner-xlmr-base`), on CPU.

## pl-pii-bench and pl-smoke: unchanged

| Set | Mode | Leak | `negative` over-masked | Over-masking | F1 (overlap) |
|---|---|---:|---:|---:|---:|
| pl-pii-bench | fast, before and after | 3.5 % (29/825) | 117 | 11.7 % | 89.2 % |
| pl-pii-bench | rules, before and after | 54.1 % (446/825) | 39 | 8.6 % | 54.7 % |
| pl-smoke | fast, before and after | 0.0 % (0/43) | — | 0 | 98.9 % |
| pl-smoke | rules, before and after | 39.5 % (17/43) | — | 0 | 71.2 % |

Every lane of pl-pii-bench gives the same counts before and after. Its `negative` lane holds
none of the cases fixed here: by detector, its 117 over-masked spans are 59 NER
`BANK_ACCOUNT`, 34 rule `ID_DOCUMENT` (the cue rule on labelled numbers with a bad check
digit), 9 NER `ID_DOCUMENT`, 9 NER `PHONE`, 5 NER `EMAIL` and 1 NER TAJ (count-only, no text
read; [lanes.py](lanes.py)). pl-pii-bench stays report-only: nothing here was tuned on it.

## Synthetic dev split: leak 4 → 0, over-masked 71 → 6

[`pl_dev_split.py`](pl_dev_split.py) writes 80 synthetic documents (seed 1433): a labelled
PESEL (valid, or with a bad check digit), phone number or driving-licence number in two
layouts, and a name, each followed by a hard negative (a number after an order, invoice,
shipment, booking or amount label). **It is in-sample**: it was written for these fixes, from
the same words. It shows that the fixes work, not how well they generalise.

| Fast mode, by template | Leak before | Leak after | Over-masked before | Over-masked after |
|---|---:|---:|---:|---:|
| PESEL | 0/44 | 0/44 | 21 | 2 |
| PESEL, bad check digit | 0/28 | 0/28 | 11 | 1 |
| phone | 0/42 | 0/42 | 20 | 2 |
| driving licence `NNNNN/NN/NNNN` | 0/34 | 0/34 | 14 | 0 |
| driving licence `NNNN/NN/NN` | 4/12 | **0/12** | 5 | 1 |
| **all** | 4/160 | **0/160** | 71 | **6** |

Before, the 71 over-masked spans were 26 NER Hungarian tax IDs, 23 NER `ID_DOCUMENT`, 11 NER
`BANK_ACCOUNT` and 8 rule TAJs (all on numbers after Polish order labels), plus 3 others.
After, 2 NER `BANK_ACCOUNT`, 2 NER `PERSON`, 1 NER `PHONE` and 1 NER `ID_DOCUMENT` are left:
`BANK_ACCOUNT`, `PHONE` and `PERSON` are not number-checked types.

## Other languages

Rules on the hu/en/de smoke, synth-sample, inflection, company-names, known-values, secrets and
negative sets, and fast mode on the hu/en/de smoke sets: the same counts before and after.
`make gate` passes. Three rule scorecards moved, all for the better (run records:
[ai4privacy before](../runs/2026-10-28-lab-1433-ai4privacy-rules-before.json) /
[after](../runs/2026-10-28-lab-1433-ai4privacy-rules-after.json),
[gretel-finance before](../runs/2026-10-28-lab-1433-gretel-finance-rules-before.json) /
[after](../runs/2026-10-28-lab-1433-gretel-finance-rules-after.json),
[cee-pii before](../runs/2026-10-28-lab-1433-cee-pii-rules-before.json) /
[after](../runs/2026-10-28-lab-1433-cee-pii-rules-after.json)):

| Rules | Leak before | Leak after | Over-masked before | Over-masked after | Predicted spans |
|---|---:|---:|---:|---:|---:|
| ai4privacy (600 docs) | 63.07 % (1378/2185) | **62.93 %** (1375/2185) | 1 | 1 | 805 → 808 |
| gretel-finance (400 docs) | 80.83 % (763/944) | 80.83 % | 65 | **59** | 280 → 273 |
| cee-pii (451 docs) | 41.27 % (208/504) | 41.27 % | 0 | 0 | 326 → 315 |

- **ai4privacy:** 3 more phone numbers caught (2 en, 1 de). Each follows a phone cue and
  holds digits the old date guard took for a date; nothing else in this change adds masks.
- **gretel-finance:** the 6 over-masks that go are unlabelled TAJ matches in English and
  German text.
- **cee-pii:** 11 unlabelled TAJ matches in its English half go; they were on ignore regions
  (unscored), so no score moves. The Hungarian half is unchanged: all 172 of its TAJ documents
  are Hungarian.

The cost of the TAJ scope: a TAJ number with no label in a text that is not Hungarian is no
longer masked by the rules (the NER and the cue rule still see it). None of the sets above
has one.

## Reproduce

```bash
uv sync --extra ner
export PII_GUARD_NER_DEVICE=cpu
uv run --no-sync pii-guard eval --fixtures eval/datasets/pl-pii-bench/pl-pl-pii-bench.jsonl \
    --detectors rules,ner
uv run --no-sync pii-guard eval --fixtures eval/fixtures/pl-smoke.jsonl --detectors rules,ner
uv run --no-sync python eval/results/2026-10-28-lab-1433-pl-followups/pl_dev_split.py dev.jsonl
uv run --no-sync python eval/results/2026-10-28-lab-1433-pl-followups/lanes.py dev.jsonl rules,ner
uv run --no-sync pii-guard eval --fixtures eval/fixtures/public --detectors rules
```

Cost: $0, everything ran on a local CPU.
