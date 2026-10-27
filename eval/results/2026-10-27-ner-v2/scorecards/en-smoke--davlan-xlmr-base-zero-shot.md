# pii-guard evaluation

- commit: `910a6a27f002 (dirty)`, pii-guard 0.1.0
- detectors: `rules`, `ner`
- fixtures: `eval/fixtures/en-smoke.jsonl` sha256 `5983d84d8dfc9fe3`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `en` | 10 | 34 | 41 | 56.1 | 67.6 | 61.3 | 90.2 | 91.2 | 90.7 | 87.7 | 10.0 | 13.3 | 10.8 | 100.0 | 76.7 | 16.76 | 23.32 |
| **overall** | 10 | 34 | 41 | 56.1 | 67.6 | 61.3 | 90.2 | 91.2 | 90.7 | 87.7 | 10.0 | 13.3 | 10.8 | 100.0 | 76.7 | 16.76 | 23.32 |

## Per entity type: `en`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 10 | 10 | 60.0 | 60.0 | 60.0 | 90.0 | 90.0 | 90.0 | 10.0 | 30.0 |
| `ADDRESS` | 4 | 13 | 0.0 | 0.0 | 0.0 | 76.9 | 100.0 | 87.0 | 0.0 | 0.0 |
| `EMAIL` | 3 | 3 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 33.3 |
| `PHONE` | 4 | 4 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `DATE_OF_BIRTH` | 2 | 0 | - | 0.0 | 0.0 | - | 0.0 | 0.0 | 100.0 | 0.0 |
| `NATIONAL_ID_HU_TAX` | 1 | 1 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `ID_DOCUMENT` | 1 | 1 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `BANK_ACCOUNT` | 4 | 4 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `ORGANIZATION` | 4 | 4 | 75.0 | 75.0 | 75.0 | 100.0 | 100.0 | 100.0 | keep | keep |
| `VEHICLE_PLATE` | 1 | 1 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| **all (micro)** | 34 | 41 | 56.1 | 67.6 | 61.3 | 90.2 | 91.2 | 90.7 | 10.0 | 13.3 |
