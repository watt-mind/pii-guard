# pii-guard evaluation

- commit: `910a6a27f002 (dirty)`, pii-guard 0.1.0
- detectors: `rules`, `ner`
- fixtures: `eval/fixtures/hu-smoke.jsonl` sha256 `3766a651708e8749`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `hu` | 31 | 120 | 121 | 92.6 | 93.3 | 92.9 | 98.3 | 97.5 | 97.9 | 97.5 | 1.9 | 0.9 | 0.9 | 100.0 | 96.2 | 18.33 | 26.27 |
| **overall** | 31 | 120 | 121 | 92.6 | 93.3 | 92.9 | 98.3 | 97.5 | 97.9 | 97.5 | 1.9 | 0.9 | 0.9 | 100.0 | 96.2 | 18.33 | 26.27 |

## Per entity type: `hu`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 38 | 38 | 89.5 | 89.5 | 89.5 | 100.0 | 94.7 | 97.3 | 5.4 | 2.7 |
| `ADDRESS` | 13 | 13 | 84.6 | 84.6 | 84.6 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `EMAIL` | 6 | 6 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `PHONE` | 7 | 7 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `DATE_OF_BIRTH` | 6 | 7 | 71.4 | 83.3 | 76.9 | 85.7 | 100.0 | 92.3 | 0.0 | 0.0 |
| `NATIONAL_ID_HU_TAX` | 5 | 5 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `NATIONAL_ID_HU_TAJ` | 5 | 5 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `ID_DOCUMENT` | 10 | 10 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `BANK_ACCOUNT` | 6 | 7 | 85.7 | 100.0 | 92.3 | 85.7 | 100.0 | 92.3 | 0.0 | 0.0 |
| `COMPANY_ID_HU` | 4 | 3 | 100.0 | 75.0 | 85.7 | 100.0 | 75.0 | 85.7 | keep | keep |
| `ORGANIZATION` | 9 | 9 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | keep | keep |
| `PARCEL_NUMBER_HU` | 6 | 6 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `VEHICLE_PLATE` | 5 | 5 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| **all (micro)** | 120 | 121 | 92.6 | 93.3 | 92.9 | 98.3 | 97.5 | 97.9 | 1.9 | 0.9 |
