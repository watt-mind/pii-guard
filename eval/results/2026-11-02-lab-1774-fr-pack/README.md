# French language pack (LAB-1774)

*Before* is `origin/develop` at `ec2828b` without a `fr` pack. *After* is the same commit with
the pack (`src/pii_guard/languages/fr/`). Scorecards in this folder:
[rules](fr-smoke-rules.json) and [fast](fr-smoke-fast.json) (rules + the published NER, on
CPU) on the new `eval/fixtures/fr-smoke.jsonl`. They are kept out of the run log, as the Polish
pack's were at first: a record there would add French to the headline `smoke` set before any
comparison tool has run on it.

## fr-smoke (11 hand-written documents, 41 labels, 2 hard negatives)

| Detector | P overlap | R overlap | R exact | Leak | Over-masked | Round trip |
|---|---:|---:|---:|---:|---:|---:|
| `rules` | 100.0 | 53.7 | 53.7 | 43.6 % (17/39) | 0 | 100.0 |
| `rules,ner` (fast) | 97.5 | 95.1 | 95.1 | 2.6 % (1/39) | 1 | 100.0 |

Every structured identifier is found by the rules (NIRs including a Corsican one, numéros
fiscaux, passport, CNI and driving-licence numbers, IBANs, phones, addresses: 100 % overlap
recall on those types). The rules misses are names, dates of birth and organisations, which
the rules don't cover by design. In fast mode one name leaks.

## The EU gates (`eval/fixtures/eu/fr-*.jsonl`, rules)

| Fixture | Leak before | Leak after | Round trip |
|---|---:|---:|---:|
| `eu/fr-smoke.jsonl` (5 documents) | 81.2 % (13/16) | 50.0 % (8/16) | 100.0 |
| `eu/fr-inflection.jsonl` (4 documents, names only) | 100.0 % (10/10) | 100.0 % (10/10) | 100.0 |

After: every phone, address and the passport number in `eu/fr-smoke` is masked; what leaks
are names and a date of birth. `eu/fr-inflection` holds names only, which the rules don't
find; it is in the pack's smoke set for the round trip (elided `d'`/`l'` stay outside the
placeholder).

## Other languages unchanged

Rules detector, every committed hu/en/de/pl fixture, before and after (predicted spans, leaked
values, over-masked spans). Every scorecard is identical apart from timings.

| Fixture | Before | After |
|---|---|---|
| `hu-smoke` | 69 pred, leak 41/106, 0 over-masked | same |
| `en-smoke` | 16 pred, leak 14/30, 0 | same |
| `de-smoke` | 22 pred, leak 16/37, 0 | same |
| `pl-smoke` | 26 pred, leak 17/43, 0 | same |
| `hu-synth-sample` | 125 pred, leak 72/173, 0 | same |
| `en-synth-sample` | 45 pred, leak 37/80, 0 | same |
| `de-synth-sample` | 52 pred, leak 65/114, 0 | same |
| `hu-inflection` | 9 pred, leak 42/50, 0 | same |
| `hu-company-names` | 57 pred, leak 1/40, 0 | same |
| `hu-injection` / `en-injection` | 42 pred, leak 46/88 / 38 pred, leak 49/87 | same |
| `public/hu-ai4privacy` | 274 pred, leak 478/752, 0 | same |
| `public/en-ai4privacy` | 281 pred, leak 524/805, 1 | same |
| `public/de-ai4privacy` | 267 pred, leak 360/628, 0 | same |
| `negative/{hu,en,de,pl}-uncued-numbers`, `-brand-names` | 0 pred | same |

The unlabelled NIR is the only French rule that runs on other languages' text without a
label. Over the 4 156 non-French documents under `eval/` (fixtures and benchmark datasets) it
fires once: `gretel-finance-30411` (German), an EDIFACT reference that the dataset itself
labels `ID_DOCUMENT`.

## Reproduce

```bash
uv run pii-guard lang check fr
uv run pii-guard eval --fixtures eval/fixtures/fr-smoke.jsonl --detectors rules
PII_GUARD_NER_DEVICE=cpu uv run pii-guard eval --fixtures eval/fixtures/fr-smoke.jsonl \
    --detectors rules,ner
```

The before/after rows come from running `pii-guard eval --detectors rules --json` on each
fixture with and without `src/pii_guard/languages/fr/` and comparing the JSON scorecards.
