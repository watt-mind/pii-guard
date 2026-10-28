# pii-guard evaluation

- commit: `477196a3427c (dirty)`, pii-guard 0.1.0
- detectors: `rules`, `ner`
- fixtures: `eval/fixtures/hu-smoke.jsonl` sha256 `3766a651708e8749`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `hu` | 31 | 120 | 118 | 85.6 | 84.2 | 84.9 | 89.8 | 89.2 | 89.5 | 79.3 | 0.9 | 1.9 | 0.9 | 100.0 | 99.1 | 16.46 | 21.97 |
| **overall** | 31 | 120 | 118 | 85.6 | 84.2 | 84.9 | 89.8 | 89.2 | 89.5 | 79.3 | 0.9 | 1.9 | 0.9 | 100.0 | 99.1 | 16.46 | 21.97 |

## Per entity type: `hu`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 38 | 38 | 92.1 | 92.1 | 92.1 | 97.4 | 97.4 | 97.4 | 2.7 | 5.4 |
| `ADDRESS` | 13 | 19 | 68.4 | 100.0 | 81.3 | 68.4 | 100.0 | 81.3 | 0.0 | 0.0 |
| `EMAIL` | 6 | 6 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `PHONE` | 7 | 9 | 77.8 | 100.0 | 87.5 | 77.8 | 100.0 | 87.5 | 0.0 | 0.0 |
| `DATE_OF_BIRTH` | 6 | 6 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `NATIONAL_ID_HU_TAX` | 5 | 8 | 62.5 | 100.0 | 76.9 | 62.5 | 100.0 | 76.9 | 0.0 | 0.0 |
| `NATIONAL_ID_HU_TAJ` | 5 | 5 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `ID_DOCUMENT` | 10 | 9 | 77.8 | 70.0 | 73.7 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `BANK_ACCOUNT` | 6 | 6 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `COMPANY_ID_HU` | 4 | 0 | — | 0.0 | 0.0 | — | 0.0 | 0.0 | keep | keep |
| `ORGANIZATION` | 9 | 7 | 85.7 | 66.7 | 75.0 | 100.0 | 77.8 | 87.5 | keep | keep |
| `PARCEL_NUMBER_HU` | 6 | 0 | — | 0.0 | 0.0 | — | 0.0 | 0.0 | 0.0 | 0.0 |
| `VEHICLE_PLATE` | 5 | 5 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| **all (micro)** | 120 | 118 | 85.6 | 84.2 | 84.9 | 89.8 | 89.2 | 89.5 | 0.9 | 1.9 |
