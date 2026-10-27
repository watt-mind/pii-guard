# pii-guard evaluation

- commit: `b6e7bac54675 (dirty)`, pii-guard 0.1.0
- detectors: `rules`, `ner`
- fixtures: `eval/fixtures/public/en-ai4privacy.jsonl` sha256 `fcfc735dff402d7d`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `en` | 200 | 805 | 756 | 61.0 | 57.3 | 59.1 | 84.7 | 71.7 | 77.6 | 55.9 | 26.8 | 6.6 | 8.6 | 100.0 | 65.8 | 20.13 | 30.31 |
| **overall** | 200 | 805 | 756 | 61.0 | 57.3 | 59.1 | 84.7 | 71.7 | 77.6 | 55.9 | 26.8 | 6.6 | 8.6 | 100.0 | 65.8 | 20.13 | 30.31 |

## Per entity type: `en`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 205 | 216 | 78.2 | 82.4 | 80.3 | 95.8 | 97.6 | 96.7 | 1.0 | 5.4 |
| `ADDRESS` | 176 | 232 | 15.1 | 19.9 | 17.2 | 74.1 | 65.9 | 69.8 | 33.5 | 22.7 |
| `EMAIL` | 111 | 111 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `PHONE` | 85 | 81 | 86.4 | 82.4 | 84.3 | 91.4 | 87.1 | 89.2 | 12.9 | 1.2 |
| `NATIONAL_ID_HU_TAX` | 0 | 1 | 0.0 | - | 0.0 | 0.0 | - | 0.0 | keep | keep |
| `ID_DOCUMENT` | 187 | 66 | 100.0 | 35.3 | 52.2 | 100.0 | 35.3 | 52.2 | 60.4 | 0.5 |
| `BANK_ACCOUNT` | 41 | 10 | 100.0 | 24.4 | 39.2 | 100.0 | 24.4 | 39.2 | 75.6 | 0.0 |
| `ORGANIZATION` | 0 | 39 | 0.0 | - | 0.0 | 0.0 | - | 0.0 | keep | keep |
| **all (micro)** | 805 | 756 | 61.0 | 57.3 | 59.1 | 84.7 | 71.7 | 77.6 | 26.8 | 6.6 |
