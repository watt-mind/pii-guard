# pii-guard evaluation

- commit: `477196a3427c (dirty)`, pii-guard 0.1.0
- detectors: `rules`, `ner`
- fixtures: `eval/fixtures/hu-smoke.jsonl` sha256 `3766a651708e8749`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `hu` | 31 | 120 | 121 | 82.6 | 83.3 | 83.0 | 92.6 | 92.5 | 92.5 | 84.9 | 0.9 | 4.7 | 0.9 | 100.0 | 98.1 | 17.67 | 38.42 |
| **overall** | 31 | 120 | 121 | 82.6 | 83.3 | 83.0 | 92.6 | 92.5 | 92.5 | 84.9 | 0.9 | 4.7 | 0.9 | 100.0 | 98.1 | 17.67 | 38.42 |

## Per entity type: `hu`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 38 | 38 | 81.6 | 81.6 | 81.6 | 100.0 | 97.4 | 98.7 | 2.7 | 13.5 |
| `ADDRESS` | 13 | 18 | 66.7 | 92.3 | 77.4 | 72.2 | 100.0 | 83.9 | 0.0 | 0.0 |
| `EMAIL` | 6 | 6 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `PHONE` | 7 | 7 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `DATE_OF_BIRTH` | 6 | 6 | 83.3 | 83.3 | 83.3 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `NATIONAL_ID_HU_TAX` | 5 | 9 | 55.6 | 100.0 | 71.4 | 55.6 | 100.0 | 71.4 | 0.0 | 0.0 |
| `NATIONAL_ID_HU_TAJ` | 5 | 5 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `ID_DOCUMENT` | 10 | 10 | 90.0 | 90.0 | 90.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `BANK_ACCOUNT` | 6 | 6 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `COMPANY_ID_HU` | 4 | 0 | — | 0.0 | 0.0 | — | 0.0 | 0.0 | keep | keep |
| `ORGANIZATION` | 9 | 9 | 77.8 | 77.8 | 77.8 | 100.0 | 100.0 | 100.0 | keep | keep |
| `PARCEL_NUMBER_HU` | 6 | 2 | 100.0 | 33.3 | 50.0 | 100.0 | 33.3 | 50.0 | 0.0 | 0.0 |
| `VEHICLE_PLATE` | 5 | 5 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| **all (micro)** | 120 | 121 | 82.6 | 83.3 | 83.0 | 92.6 | 92.5 | 92.5 | 0.9 | 4.7 |
