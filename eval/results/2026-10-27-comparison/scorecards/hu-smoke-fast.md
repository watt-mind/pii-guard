# pii-guard evaluation

- commit: `4f84c6adc9ba`, pii-guard 0.1.0
- detectors: `rules`, `ner`
- fixtures: `eval/fixtures/hu-smoke.jsonl` sha256 `3766a651708e8749`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `hu` | 31 | 120 | 121 | 93.4 | 94.2 | 93.8 | 97.5 | 98.3 | 97.9 | 97.9 | 0.9 | 1.9 | 0.9 | 100.0 | 99.1 | 28.46 | 43.40 |
| **overall** | 31 | 120 | 121 | 93.4 | 94.2 | 93.8 | 97.5 | 98.3 | 97.9 | 97.9 | 0.9 | 1.9 | 0.9 | 100.0 | 99.1 | 28.46 | 43.40 |

## Per entity type: `hu`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 38 | 37 | 94.6 | 92.1 | 93.3 | 100.0 | 97.4 | 98.7 | 2.7 | 5.4 |
| `ADDRESS` | 13 | 14 | 78.6 | 84.6 | 81.5 | 92.9 | 100.0 | 96.3 | 0.0 | 0.0 |
| `EMAIL` | 6 | 6 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `PHONE` | 7 | 7 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `DATE_OF_BIRTH` | 6 | 7 | 85.7 | 100.0 | 92.3 | 85.7 | 100.0 | 92.3 | 0.0 | 0.0 |
| `NATIONAL_ID_HU_TAX` | 5 | 5 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `NATIONAL_ID_HU_TAJ` | 5 | 5 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `ID_DOCUMENT` | 10 | 10 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `BANK_ACCOUNT` | 6 | 6 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `COMPANY_ID_HU` | 4 | 4 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | keep | keep |
| `ORGANIZATION` | 9 | 10 | 80.0 | 88.9 | 84.2 | 90.0 | 100.0 | 94.7 | keep | keep |
| `PARCEL_NUMBER_HU` | 6 | 5 | 100.0 | 83.3 | 90.9 | 100.0 | 83.3 | 90.9 | 0.0 | 0.0 |
| `VEHICLE_PLATE` | 5 | 5 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| **all (micro)** | 120 | 121 | 93.4 | 94.2 | 93.8 | 97.5 | 98.3 | 97.9 | 0.9 | 1.9 |
