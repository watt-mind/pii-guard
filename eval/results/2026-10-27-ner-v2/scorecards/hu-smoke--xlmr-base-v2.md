# pii-guard evaluation

- commit: `910a6a27f002`, pii-guard 0.1.0
- detectors: `rules`, `ner`
- fixtures: `eval/fixtures/hu-smoke.jsonl` sha256 `3766a651708e8749`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `hu` | 31 | 120 | 122 | 85.2 | 86.7 | 86.0 | 89.3 | 89.2 | 89.3 | 81.2 | 1.9 | 0.9 | 4.3 | 100.0 | 97.2 | 16.28 | 28.79 |
| **overall** | 31 | 120 | 122 | 85.2 | 86.7 | 86.0 | 89.3 | 89.2 | 89.3 | 81.2 | 1.9 | 0.9 | 4.3 | 100.0 | 97.2 | 16.28 | 28.79 |

## Per entity type: `hu`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 38 | 37 | 94.6 | 92.1 | 93.3 | 100.0 | 94.7 | 97.3 | 5.4 | 2.7 |
| `ADDRESS` | 13 | 17 | 76.5 | 100.0 | 86.7 | 76.5 | 100.0 | 86.7 | 0.0 | 0.0 |
| `EMAIL` | 6 | 6 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `PHONE` | 7 | 7 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `DATE_OF_BIRTH` | 6 | 6 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `NATIONAL_ID_HU_TAX` | 5 | 11 | 45.5 | 100.0 | 62.5 | 45.5 | 100.0 | 62.5 | 0.0 | 0.0 |
| `NATIONAL_ID_HU_TAJ` | 5 | 7 | 71.4 | 100.0 | 83.3 | 71.4 | 100.0 | 83.3 | 0.0 | 0.0 |
| `ID_DOCUMENT` | 10 | 11 | 81.8 | 90.0 | 85.7 | 90.9 | 100.0 | 95.2 | 0.0 | 0.0 |
| `BANK_ACCOUNT` | 6 | 6 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `COMPANY_ID_HU` | 4 | 0 | - | 0.0 | 0.0 | - | 0.0 | 0.0 | keep | keep |
| `ORGANIZATION` | 9 | 7 | 71.4 | 55.6 | 62.5 | 100.0 | 66.7 | 80.0 | keep | keep |
| `PARCEL_NUMBER_HU` | 6 | 2 | 100.0 | 33.3 | 50.0 | 100.0 | 33.3 | 50.0 | 0.0 | 0.0 |
| `VEHICLE_PLATE` | 5 | 5 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| **all (micro)** | 120 | 122 | 85.2 | 86.7 | 86.0 | 89.3 | 89.2 | 89.3 | 1.9 | 0.9 |
