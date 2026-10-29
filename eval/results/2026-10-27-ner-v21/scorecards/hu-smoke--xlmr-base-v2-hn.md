# pii-guard evaluation

- commit: `477196a3427c (dirty)`, pii-guard 0.1.0
- detectors: `rules`, `ner`
- fixtures: `eval/fixtures/hu-smoke.jsonl` sha256 `3766a651708e8749`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `hu` | 31 | 120 | 119 | 89.1 | 88.3 | 88.7 | 94.1 | 92.5 | 93.3 | 86.4 | 0.0 | 1.9 | 0.9 | 100.0 | 99.1 | 18.05 | 23.97 |
| **overall** | 31 | 120 | 119 | 89.1 | 88.3 | 88.7 | 94.1 | 92.5 | 93.3 | 86.4 | 0.0 | 1.9 | 0.9 | 100.0 | 99.1 | 18.05 | 23.97 |

## Per entity type: `hu`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 38 | 40 | 87.5 | 92.1 | 89.7 | 97.5 | 100.0 | 98.7 | 0.0 | 5.4 |
| `ADDRESS` | 13 | 15 | 86.7 | 100.0 | 92.9 | 86.7 | 100.0 | 92.9 | 0.0 | 0.0 |
| `EMAIL` | 6 | 6 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `PHONE` | 7 | 7 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `DATE_OF_BIRTH` | 6 | 6 | 83.3 | 83.3 | 83.3 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `NATIONAL_ID_HU_TAX` | 5 | 8 | 62.5 | 100.0 | 76.9 | 62.5 | 100.0 | 76.9 | 0.0 | 0.0 |
| `NATIONAL_ID_HU_TAJ` | 5 | 5 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `ID_DOCUMENT` | 10 | 11 | 81.8 | 90.0 | 85.7 | 90.9 | 100.0 | 95.2 | 0.0 | 0.0 |
| `BANK_ACCOUNT` | 6 | 6 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `COMPANY_ID_HU` | 4 | 0 | — | 0.0 | 0.0 | — | 0.0 | 0.0 | keep | keep |
| `ORGANIZATION` | 9 | 6 | 100.0 | 66.7 | 80.0 | 100.0 | 66.7 | 80.0 | keep | keep |
| `PARCEL_NUMBER_HU` | 6 | 4 | 100.0 | 66.7 | 80.0 | 100.0 | 66.7 | 80.0 | 0.0 | 0.0 |
| `VEHICLE_PLATE` | 5 | 5 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| **all (micro)** | 120 | 119 | 89.1 | 88.3 | 88.7 | 94.1 | 92.5 | 93.3 | 0.0 | 1.9 |
