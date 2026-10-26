# pii-guard evaluation

- commit: `0ba3c1a50e8c (dirty)`, pii-guard 0.1.0
- detectors: `rules`, `ner`
- fixtures: `eval/fixtures/en-smoke.jsonl` sha256 `5983d84d8dfc9fe3`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `en` | 10 | 34 | 40 | 72.5 | 85.3 | 78.4 | 80.0 | 94.1 | 86.5 | 92.9 | 3.3 | 6.7 | 16.2 | 100.0 | 14.37 | 197.73 |
| **overall** | 10 | 34 | 40 | 72.5 | 85.3 | 78.4 | 80.0 | 94.1 | 86.5 | 92.9 | 3.3 | 6.7 | 16.2 | 100.0 | 14.37 | 197.73 |

## Per entity type: `en`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 10 | 16 | 50.0 | 80.0 | 61.5 | 62.5 | 100.0 | 76.9 | 0.0 | 10.0 |
| `ADDRESS` | 4 | 5 | 60.0 | 75.0 | 66.7 | 60.0 | 75.0 | 66.7 | 25.0 | 0.0 |
| `EMAIL` | 3 | 3 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 33.3 |
| `PHONE` | 4 | 4 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `DATE_OF_BIRTH` | 2 | 2 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `NATIONAL_ID_HU_TAX` | 1 | 1 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `ID_DOCUMENT` | 1 | 1 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `BANK_ACCOUNT` | 4 | 4 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `ORGANIZATION` | 4 | 3 | 66.7 | 50.0 | 57.1 | 100.0 | 75.0 | 85.7 | keep | keep |
| `VEHICLE_PLATE` | 1 | 1 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| **all (micro)** | 34 | 40 | 72.5 | 85.3 | 78.4 | 80.0 | 94.1 | 86.5 | 3.3 | 6.7 |
