# pii-guard evaluation

- commit: `0ba3c1a50e8c (dirty)`, pii-guard 0.1.0
- detectors: `rules`, `ner`
- fixtures: `eval/fixtures/hu-smoke.jsonl` sha256 `292c687941f295cb`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `hu` | 28 | 111 | 100 | 90.0 | 81.1 | 85.3 | 100.0 | 89.2 | 94.3 | 84.3 | 12.4 | 4.1 | 0.0 | 100.0 | 15.32 | 21.61 |
| **overall** | 28 | 111 | 100 | 90.0 | 81.1 | 85.3 | 100.0 | 89.2 | 94.3 | 84.3 | 12.4 | 4.1 | 0.0 | 100.0 | 15.32 | 21.61 |

## Per entity type: `hu`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 36 | 34 | 85.3 | 80.6 | 82.9 | 100.0 | 91.7 | 95.7 | 8.6 | 8.6 |
| `ADDRESS` | 13 | 13 | 76.9 | 76.9 | 76.9 | 100.0 | 100.0 | 100.0 | 0.0 | 7.7 |
| `EMAIL` | 6 | 6 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `PHONE` | 7 | 7 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `DATE_OF_BIRTH` | 6 | 6 | 83.3 | 83.3 | 83.3 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `NATIONAL_ID_HU_TAX` | 5 | 5 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `NATIONAL_ID_HU_TAJ` | 5 | 5 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `ID_DOCUMENT` | 5 | 0 | - | 0.0 | 0.0 | - | 0.0 | 0.0 | 100.0 | 0.0 |
| `BANK_ACCOUNT` | 6 | 6 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `COMPANY_ID_HU` | 4 | 4 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | keep | keep |
| `ORGANIZATION` | 9 | 9 | 88.9 | 88.9 | 88.9 | 100.0 | 100.0 | 100.0 | keep | keep |
| `PARCEL_NUMBER_HU` | 4 | 0 | - | 0.0 | 0.0 | - | 0.0 | 0.0 | 100.0 | 0.0 |
| `VEHICLE_PLATE` | 5 | 5 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| **all (micro)** | 111 | 100 | 90.0 | 81.1 | 85.3 | 100.0 | 89.2 | 94.3 | 12.4 | 4.1 |
