# pii-guard evaluation

- commit: `910a6a27f002 (dirty)`, pii-guard 0.1.0
- detectors: `rules`, `ner_gliner`
- fixtures: `eval/fixtures/hu-smoke.jsonl` sha256 `3766a651708e8749`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `hu` | 31 | 120 | 129 | 79.8 | 85.8 | 82.7 | 83.7 | 90.8 | 87.1 | 77.6 | 0.9 | 1.9 | 9.2 | 100.0 | 99.1 | 71.30 | 93.40 |
| **overall** | 31 | 120 | 129 | 79.8 | 85.8 | 82.7 | 83.7 | 90.8 | 87.1 | 77.6 | 0.9 | 1.9 | 9.2 | 100.0 | 99.1 | 71.30 | 93.40 |

## Per entity type: `hu`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 38 | 37 | 91.9 | 89.5 | 90.7 | 100.0 | 97.4 | 98.7 | 2.7 | 5.4 |
| `ADDRESS` | 13 | 19 | 68.4 | 100.0 | 81.3 | 68.4 | 100.0 | 81.3 | 0.0 | 0.0 |
| `EMAIL` | 6 | 6 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `PHONE` | 7 | 7 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `DATE_OF_BIRTH` | 6 | 6 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `NATIONAL_ID_HU_TAX` | 5 | 11 | 45.5 | 100.0 | 62.5 | 45.5 | 100.0 | 62.5 | 0.0 | 0.0 |
| `NATIONAL_ID_HU_TAJ` | 5 | 5 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `ID_DOCUMENT` | 10 | 18 | 44.4 | 80.0 | 57.1 | 50.0 | 100.0 | 66.7 | 0.0 | 0.0 |
| `BANK_ACCOUNT` | 6 | 6 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `COMPANY_ID_HU` | 4 | 0 | - | 0.0 | 0.0 | - | 0.0 | 0.0 | keep | keep |
| `ORGANIZATION` | 9 | 9 | 88.9 | 88.9 | 88.9 | 100.0 | 100.0 | 100.0 | keep | keep |
| `PARCEL_NUMBER_HU` | 6 | 0 | - | 0.0 | 0.0 | - | 0.0 | 0.0 | 0.0 | 0.0 |
| `VEHICLE_PLATE` | 5 | 5 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| **all (micro)** | 120 | 129 | 79.8 | 85.8 | 82.7 | 83.7 | 90.8 | 87.1 | 0.9 | 1.9 |
