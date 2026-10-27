# pii-guard evaluation

- commit: `910a6a27f002 (dirty)`, pii-guard 0.1.0
- detectors: `rules`, `ner`
- fixtures: `eval/fixtures/hu-smoke.jsonl` sha256 `3766a651708e8749`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `hu` | 31 | 120 | 123 | 89.4 | 91.7 | 90.5 | 96.7 | 97.5 | 97.1 | 94.9 | 0.0 | 2.8 | 0.9 | 100.0 | 98.1 | 25.62 | 35.49 |
| **overall** | 31 | 120 | 123 | 89.4 | 91.7 | 90.5 | 96.7 | 97.5 | 97.1 | 94.9 | 0.0 | 2.8 | 0.9 | 100.0 | 98.1 | 25.62 | 35.49 |

## Per entity type: `hu`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 38 | 38 | 92.1 | 92.1 | 92.1 | 100.0 | 100.0 | 100.0 | 0.0 | 8.1 |
| `ADDRESS` | 13 | 15 | 80.0 | 92.3 | 85.7 | 86.7 | 100.0 | 92.9 | 0.0 | 0.0 |
| `EMAIL` | 6 | 6 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `PHONE` | 7 | 7 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `DATE_OF_BIRTH` | 6 | 8 | 50.0 | 66.7 | 57.1 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `NATIONAL_ID_HU_TAX` | 5 | 7 | 71.4 | 100.0 | 83.3 | 71.4 | 100.0 | 83.3 | 0.0 | 0.0 |
| `NATIONAL_ID_HU_TAJ` | 5 | 5 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `ID_DOCUMENT` | 10 | 10 | 90.0 | 90.0 | 90.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `BANK_ACCOUNT` | 6 | 6 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `COMPANY_ID_HU` | 4 | 2 | 100.0 | 50.0 | 66.7 | 100.0 | 50.0 | 66.7 | keep | keep |
| `ORGANIZATION` | 9 | 9 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | keep | keep |
| `PARCEL_NUMBER_HU` | 6 | 5 | 100.0 | 83.3 | 90.9 | 100.0 | 83.3 | 90.9 | 0.0 | 0.0 |
| `VEHICLE_PLATE` | 5 | 5 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| **all (micro)** | 120 | 123 | 89.4 | 91.7 | 90.5 | 96.7 | 97.5 | 97.1 | 0.0 | 2.8 |
