# pii-guard evaluation

- commit: `477196a3427c (dirty)`, pii-guard 0.1.0
- detectors: `rules`, `ner`
- fixtures: `eval/fixtures/hu-smoke.jsonl` sha256 `3766a651708e8749`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `hu` | 31 | 120 | 122 | 81.1 | 82.5 | 81.8 | 90.2 | 92.5 | 91.3 | 84.6 | 0.9 | 1.9 | 2.6 | 100.0 | 99.1 | 13.91 | 20.31 |
| **overall** | 31 | 120 | 122 | 81.1 | 82.5 | 81.8 | 90.2 | 92.5 | 91.3 | 84.6 | 0.9 | 1.9 | 2.6 | 100.0 | 99.1 | 13.91 | 20.31 |

## Per entity type: `hu`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 38 | 38 | 86.8 | 86.8 | 86.8 | 97.4 | 97.4 | 97.4 | 2.7 | 5.4 |
| `ADDRESS` | 13 | 17 | 76.5 | 100.0 | 86.7 | 76.5 | 100.0 | 86.7 | 0.0 | 0.0 |
| `EMAIL` | 6 | 6 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `PHONE` | 7 | 7 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `DATE_OF_BIRTH` | 6 | 7 | 71.4 | 83.3 | 76.9 | 85.7 | 100.0 | 92.3 | 0.0 | 0.0 |
| `NATIONAL_ID_HU_TAX` | 5 | 8 | 62.5 | 100.0 | 76.9 | 62.5 | 100.0 | 76.9 | 0.0 | 0.0 |
| `NATIONAL_ID_HU_TAJ` | 5 | 5 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `ID_DOCUMENT` | 10 | 12 | 50.0 | 60.0 | 54.5 | 75.0 | 100.0 | 85.7 | 0.0 | 0.0 |
| `BANK_ACCOUNT` | 6 | 6 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `COMPANY_ID_HU` | 4 | 0 | — | 0.0 | 0.0 | — | 0.0 | 0.0 | keep | keep |
| `ORGANIZATION` | 9 | 8 | 62.5 | 55.6 | 58.8 | 100.0 | 88.9 | 94.1 | keep | keep |
| `PARCEL_NUMBER_HU` | 6 | 3 | 100.0 | 50.0 | 66.7 | 100.0 | 50.0 | 66.7 | 0.0 | 0.0 |
| `VEHICLE_PLATE` | 5 | 5 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| **all (micro)** | 120 | 122 | 81.1 | 82.5 | 81.8 | 90.2 | 92.5 | 91.3 | 0.9 | 1.9 |
