# Italian language pack: smoke scores and the hu/en/de/pl check (LAB-1776)

Rules detector, offline, on CPU. *Before* is `origin/develop` at `ec2828b` without an `it`
pack; *after* is the same commit with the pack (`src/pii_guard/languages/it/`). The Italian
scorecard in this folder: [it-smoke-rules.json](it-smoke-rules.json) (the pack's three smoke
files together, as `pii-guard lang check it` scores them).

## Italian sets

| Rules | Docs | Labels | P overlap | R overlap | Leak | Over-masked | Round trip |
|---|---:|---:|---:|---:|---:|---:|---:|
| `it-smoke` before | 12 | 53 | 100.0 | 17.0 | 81.6 % (40/49) | 0 | 100 |
| **`it-smoke` after** | 12 | 53 | 100.0 | **64.2** | **30.6 %** (15/49) | 0 | 100 |
| `it-smoke` + `eu/it-smoke` + `eu/it-inflection` before | 21 | 82 | 100.0 | 15.9 | 82.7 % (62/75) | 0 | 100 |
| **the same, after** | 21 | 82 | 100.0 | **51.2** | **44.0 %** (33/75) | 0 | 100 |
| `negative/it-uncued-numbers` before / after | 12 | 0 | — | — | — | 0 / 0 | 100 |

After the pack, every structured value in the three smoke files is found: 15/15 identifiers
(codici fiscali, one omocodic, one with a bad check letter after its cue; partite IVA, an
`IT` VAT number, CIE, passport and driving-licence numbers), 9/9 addresses, 8/8 phones, 5/5
e-mail addresses and 5/5 IBANs and cards. What leaks is the 29 names and 4 dates of birth, which
the rules don't cover by design (the NER and LLM passes do). The two hard negatives in
`it-smoke` and the twelve uncued numbers (order, invoice, shipment, protocol and customer
numbers, a valid partita IVA shape after `Fattura n.`, amounts, dates, a CAP) mask nothing.

`eu/it-smoke.jsonl` and `eu/it-inflection.jsonl` (LAB-1525) keep their ids `0001`-`0005`; the
pack's own documents start at `0101`, since `lang check` loads all three files together.

## hu/en/de/pl unchanged

Each set scored alone with `pii-guard eval --fixtures <set> --detectors rules`, before and
after. "Before = after" compares the whole scorecard (per-type detection, leak, over-masking
and round-trip counts), not only the columns shown:

| Fixture set | Docs | P overlap | R overlap | Leak | Over-masked | Round trip | Before = after |
|---|---:|---:|---:|---:|---:|---:|:-:|
| `agent-text` | 90 | 100.0 | 56.1 | 43.7 | 0 | 100 | yes |
| `de-smoke` | 10 | 100.0 | 52.5 | 43.2 | 0 | 100 | yes |
| `de-synth-sample` | 14 | 100.0 | 33.1 | 57.0 | 0 | 100 | yes |
| `en-injection` | 31 | 100.0 | 43.7 | 56.3 | 0 | 100 | yes |
| `en-smoke` | 10 | 100.0 | 47.1 | 46.7 | 0 | 100 | yes |
| `en-synth-sample` | 10 | 100.0 | 37.5 | 46.2 | 0 | 100 | yes |
| `hu-company-names` | 44 | 100.0 | 61.3 | 2.5 | 0 | 100 | yes |
| `hu-inflection` | 12 | 100.0 | 14.8 | 84.0 | 0 | 100 | yes |
| `hu-injection` | 31 | 100.0 | 47.7 | 52.3 | 0 | 100 | yes |
| `hu-smoke` | 31 | 98.6 | 56.7 | 38.7 | 0 | 100 | yes |
| `hu-synth-sample` | 20 | 100.0 | 46.1 | 41.6 | 0 | 100 | yes |
| `negative/de-brand-names` | 6 | — | — | — | 0 | 100 | yes |
| `negative/de-uncued-numbers` | 11 | — | — | — | 0 | 100 | yes |
| `negative/en-brand-names` | 12 | — | — | — | 0 | 100 | yes |
| `negative/en-uncued-numbers` | 13 | — | — | — | 0 | 100 | yes |
| `negative/hu-brand-names` | 6 | — | — | — | 0 | 100 | yes |
| `negative/hu-uncued-numbers` | 17 | — | — | — | 0 | 100 | yes |
| `negative/pl-brand-names` | 6 | — | — | — | 0 | 100 | yes |
| `negative/pl-uncued-numbers` | 11 | — | — | — | 0 | 100 | yes |
| `pl-smoke` | 11 | 100.0 | 55.3 | 39.5 | 0 | 100 | yes |
| `public/de-ai4privacy` | 200 | 98.9 | 42.2 | 57.3 | 0 | 100 | yes |
| `public/en-ai4privacy` | 200 | 96.8 | 33.8 | 65.1 | 1 | 100 | yes |
| `public/hu-ai4privacy` | 200 | 100.0 | 36.4 | 63.6 | 0 | 100 | yes |
| `secrets/en-secrets` | 22 | 100.0 | 100.0 | 0.0 | 0 | 100 | yes |

The `EVERYWHERE` rules (codice fiscale, `IT` VAT number, labelled CIE), the Italian cues and
the Italian reference words run on all of these texts; none of them changes a count.

## Reproduce

```bash
uv run --no-sync pii-guard lang check it
uv run --no-sync pii-guard eval --fixtures eval/fixtures/it-smoke.jsonl \
    --fixtures eval/fixtures/eu/it-smoke.jsonl --fixtures eval/fixtures/eu/it-inflection.jsonl \
    --detectors rules --json it-smoke-rules.json
uv run --no-sync pii-guard eval --fixtures eval/fixtures/hu-smoke.jsonl --detectors rules  # per set
```

*Before* is the same commands with `src/pii_guard/languages/it/` moved out of the tree.
