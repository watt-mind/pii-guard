# pii-guard evaluation

- commit: `910a6a27f002 (dirty)`, pii-guard 0.1.0
- detectors: `rules`, `ner_gliner`
- fixtures: `eval/fixtures/en-smoke.jsonl` sha256 `5983d84d8dfc9fe3`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `en` | 10 | 34 | 38 | 71.1 | 79.4 | 75.0 | 94.7 | 94.1 | 94.4 | 94.2 | 3.3 | 10.0 | 5.7 | 100.0 | 86.7 | 69.96 | 85.09 |
| **overall** | 10 | 34 | 38 | 71.1 | 79.4 | 75.0 | 94.7 | 94.1 | 94.4 | 94.2 | 3.3 | 10.0 | 5.7 | 100.0 | 86.7 | 69.96 | 85.09 |

## Per entity type: `en`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 10 | 11 | 90.9 | 100.0 | 95.2 | 90.9 | 100.0 | 95.2 | 0.0 | 10.0 |
| `ADDRESS` | 4 | 9 | 0.0 | 0.0 | 0.0 | 88.9 | 100.0 | 94.1 | 0.0 | 50.0 |
| `EMAIL` | 3 | 3 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `PHONE` | 4 | 4 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `DATE_OF_BIRTH` | 2 | 1 | 100.0 | 50.0 | 66.7 | 100.0 | 50.0 | 66.7 | 50.0 | 0.0 |
| `NATIONAL_ID_HU_TAX` | 1 | 1 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `ID_DOCUMENT` | 1 | 1 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `BANK_ACCOUNT` | 4 | 4 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `ORGANIZATION` | 4 | 3 | 66.7 | 50.0 | 57.1 | 100.0 | 75.0 | 85.7 | keep | keep |
| `VEHICLE_PLATE` | 1 | 1 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| **all (micro)** | 34 | 38 | 71.1 | 79.4 | 75.0 | 94.7 | 94.1 | 94.4 | 3.3 | 10.0 |
