# pii-guard evaluation

- commit: `910a6a27f002 (dirty)`, pii-guard 0.1.0
- detectors: `rules`, `ner`
- fixtures: `eval/fixtures/en-smoke.jsonl` sha256 `5983d84d8dfc9fe3`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `en` | 10 | 34 | 37 | 78.4 | 85.3 | 81.7 | 86.5 | 91.2 | 88.8 | 88.5 | 0.0 | 0.0 | 8.3 | 100.0 | 96.7 | 16.94 | 21.40 |
| **overall** | 10 | 34 | 37 | 78.4 | 85.3 | 81.7 | 86.5 | 91.2 | 88.8 | 88.5 | 0.0 | 0.0 | 8.3 | 100.0 | 96.7 | 16.94 | 21.40 |

## Per entity type: `en`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 10 | 13 | 69.2 | 90.0 | 78.3 | 76.9 | 100.0 | 87.0 | 0.0 | 0.0 |
| `ADDRESS` | 4 | 6 | 50.0 | 75.0 | 60.0 | 83.3 | 100.0 | 90.9 | 0.0 | 0.0 |
| `EMAIL` | 3 | 3 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `PHONE` | 4 | 4 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `DATE_OF_BIRTH` | 2 | 2 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `NATIONAL_ID_HU_TAX` | 1 | 1 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `ID_DOCUMENT` | 1 | 2 | 50.0 | 100.0 | 66.7 | 50.0 | 100.0 | 66.7 | 0.0 | 0.0 |
| `BANK_ACCOUNT` | 4 | 4 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `ORGANIZATION` | 4 | 1 | 100.0 | 25.0 | 40.0 | 100.0 | 25.0 | 40.0 | keep | keep |
| `VEHICLE_PLATE` | 1 | 1 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| **all (micro)** | 34 | 37 | 78.4 | 85.3 | 81.7 | 86.5 | 91.2 | 88.8 | 0.0 | 0.0 |
