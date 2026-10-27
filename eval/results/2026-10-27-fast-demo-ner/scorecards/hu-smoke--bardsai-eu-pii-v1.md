# pii-guard evaluation

- commit: `e1268295b0d3 (dirty)`, pii-guard 0.1.0
- detectors: `rules`, `ner`
- fixtures: `eval/fixtures/hu-smoke.jsonl` sha256 `3766a651708e8749`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `hu` | 31 | 120 | 133 | 75.9 | 84.2 | 79.8 | 87.2 | 96.7 | 91.7 | 93.3 | 1.9 | 3.8 | 11.8 | 100.0 | 97.2 | 18.55 | 40.06 |
| **overall** | 31 | 120 | 133 | 75.9 | 84.2 | 79.8 | 87.2 | 96.7 | 91.7 | 93.3 | 1.9 | 3.8 | 11.8 | 100.0 | 97.2 | 18.55 | 40.06 |

## Per entity type: `hu`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 38 | 37 | 86.5 | 84.2 | 85.3 | 100.0 | 94.7 | 97.3 | 5.4 | 5.4 |
| `ADDRESS` | 13 | 20 | 45.0 | 69.2 | 54.5 | 65.0 | 100.0 | 78.8 | 0.0 | 0.0 |
| `EMAIL` | 6 | 6 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `PHONE` | 7 | 7 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `DATE_OF_BIRTH` | 6 | 7 | 57.1 | 66.7 | 61.5 | 85.7 | 100.0 | 92.3 | 0.0 | 33.3 |
| `NATIONAL_ID_HU_TAX` | 5 | 5 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `NATIONAL_ID_HU_TAJ` | 5 | 5 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `ID_DOCUMENT` | 10 | 17 | 35.3 | 60.0 | 44.4 | 52.9 | 100.0 | 69.2 | 0.0 | 0.0 |
| `BANK_ACCOUNT` | 6 | 6 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `COMPANY_ID_HU` | 4 | 4 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | keep | keep |
| `ORGANIZATION` | 9 | 10 | 80.0 | 88.9 | 84.2 | 90.0 | 100.0 | 94.7 | keep | keep |
| `PARCEL_NUMBER_HU` | 6 | 4 | 100.0 | 66.7 | 80.0 | 100.0 | 66.7 | 80.0 | 0.0 | 0.0 |
| `VEHICLE_PLATE` | 5 | 5 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| **all (micro)** | 120 | 133 | 75.9 | 84.2 | 79.8 | 87.2 | 96.7 | 91.7 | 1.9 | 3.8 |
