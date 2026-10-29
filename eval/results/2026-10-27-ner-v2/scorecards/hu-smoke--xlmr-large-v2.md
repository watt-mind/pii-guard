# pii-guard evaluation

- commit: `910a6a27f002 (dirty)`, pii-guard 0.1.0
- detectors: `rules`, `ner`
- fixtures: `eval/fixtures/hu-smoke.jsonl` sha256 `3766a651708e8749`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `hu` | 31 | 120 | 122 | 85.2 | 86.7 | 86.0 | 89.3 | 90.8 | 90.1 | 81.3 | 0.0 | 0.9 | 3.5 | 100.0 | 100.0 | 26.48 | 36.56 |
| **overall** | 31 | 120 | 122 | 85.2 | 86.7 | 86.0 | 89.3 | 90.8 | 90.1 | 81.3 | 0.0 | 0.9 | 3.5 | 100.0 | 100.0 | 26.48 | 36.56 |

## Per entity type: `hu`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 38 | 38 | 94.7 | 94.7 | 94.7 | 100.0 | 100.0 | 100.0 | 0.0 | 2.7 |
| `ADDRESS` | 13 | 19 | 68.4 | 100.0 | 81.3 | 68.4 | 100.0 | 81.3 | 0.0 | 0.0 |
| `EMAIL` | 6 | 6 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `PHONE` | 7 | 8 | 87.5 | 100.0 | 93.3 | 87.5 | 100.0 | 93.3 | 0.0 | 0.0 |
| `DATE_OF_BIRTH` | 6 | 6 | 83.3 | 83.3 | 83.3 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `NATIONAL_ID_HU_TAX` | 5 | 9 | 55.6 | 100.0 | 71.4 | 55.6 | 100.0 | 71.4 | 0.0 | 0.0 |
| `NATIONAL_ID_HU_TAJ` | 5 | 7 | 71.4 | 100.0 | 83.3 | 71.4 | 100.0 | 83.3 | 0.0 | 0.0 |
| `ID_DOCUMENT` | 10 | 10 | 90.0 | 90.0 | 90.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `BANK_ACCOUNT` | 6 | 6 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `COMPANY_ID_HU` | 4 | 1 | 100.0 | 25.0 | 40.0 | 100.0 | 25.0 | 40.0 | keep | keep |
| `ORGANIZATION` | 9 | 7 | 85.7 | 66.7 | 75.0 | 100.0 | 77.8 | 87.5 | keep | keep |
| `PARCEL_NUMBER_HU` | 6 | 0 | - | 0.0 | 0.0 | - | 0.0 | 0.0 | 0.0 | 0.0 |
| `VEHICLE_PLATE` | 5 | 5 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| **all (micro)** | 120 | 122 | 85.2 | 86.7 | 86.0 | 89.3 | 90.8 | 90.1 | 0.0 | 0.9 |
