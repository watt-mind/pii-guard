# pii-guard evaluation

- commit: `477196a3427c (dirty)`, pii-guard 0.1.0
- detectors: `rules`, `ner`
- fixtures: `eval/datasets/gretel-finance/en-gretel-finance.jsonl` sha256 `12967fcd1a89b570`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `en` | 200 | 798 | 876 | 60.6 | 63.9 | 62.2 | 76.9 | 75.9 | 76.4 | 56.2 | 5.3 | 2.5 | 20.9 | 98.0 | 83.3 | 32.04 | 51.83 |
| **overall** | 200 | 798 | 876 | 60.6 | 63.9 | 62.2 | 76.9 | 75.9 | 76.4 | 56.2 | 5.3 | 2.5 | 20.9 | 98.0 | 83.3 | 32.04 | 51.83 |

## Per entity type: `en`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 242 | 276 | 72.8 | 83.1 | 77.6 | 79.7 | 90.1 | 84.6 | 8.2 | 0.6 |
| `ADDRESS` | 154 | 229 | 40.2 | 59.7 | 48.0 | 77.7 | 92.2 | 84.4 | 3.0 | 6.8 |
| `EMAIL` | 40 | 40 | 95.0 | 95.0 | 95.0 | 95.0 | 95.0 | 95.0 | 3.6 | 0.0 |
| `PHONE` | 31 | 36 | 75.0 | 87.1 | 80.6 | 86.1 | 96.8 | 91.1 | 3.4 | 0.0 |
| `DATE_OF_BIRTH` | 11 | 11 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `NATIONAL_ID_HU_TAX` | 0 | 2 | 0.0 | — | 0.0 | 0.0 | — | 0.0 | keep | keep |
| `NATIONAL_ID_HU_TAJ` | 0 | 5 | 0.0 | — | 0.0 | 0.0 | — | 0.0 | keep | keep |
| `ID_DOCUMENT` | 15 | 60 | 21.7 | 86.7 | 34.7 | 23.3 | 93.3 | 37.3 | 7.7 | 0.0 |
| `BANK_ACCOUNT` | 14 | 28 | 46.4 | 92.9 | 61.9 | 46.4 | 92.9 | 61.9 | 0.0 | 0.0 |
| `ORGANIZATION` | 291 | 153 | 75.2 | 39.5 | 51.8 | 92.8 | 48.1 | 63.4 | keep | keep |
| `SECRET` | 0 | 1 | 0.0 | — | 0.0 | 0.0 | — | 0.0 | keep | keep |
| **all (micro)** | 798 | 841 | 60.6 | 63.9 | 62.2 | 76.9 | 75.9 | 76.4 | 5.3 | 2.5 |
