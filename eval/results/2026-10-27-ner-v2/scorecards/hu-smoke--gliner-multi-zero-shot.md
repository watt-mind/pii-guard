# pii-guard evaluation

- commit: `910a6a27f002 (dirty)`, pii-guard 0.1.0
- detectors: `rules`, `ner_gliner`
- fixtures: `eval/fixtures/hu-smoke.jsonl` sha256 `3766a651708e8749`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `hu` | 31 | 120 | 124 | 84.7 | 87.5 | 86.1 | 93.5 | 96.7 | 95.1 | 97.0 | 2.8 | 0.9 | 6.3 | 100.0 | 97.2 | 73.40 | 111.72 |
| **overall** | 31 | 120 | 124 | 84.7 | 87.5 | 86.1 | 93.5 | 96.7 | 95.1 | 97.0 | 2.8 | 0.9 | 6.3 | 100.0 | 97.2 | 73.40 | 111.72 |

## Per entity type: `hu`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 38 | 42 | 69.0 | 76.3 | 72.5 | 85.7 | 94.7 | 90.0 | 5.4 | 2.7 |
| `ADDRESS` | 13 | 13 | 92.3 | 92.3 | 92.3 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `EMAIL` | 6 | 6 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `PHONE` | 7 | 7 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `DATE_OF_BIRTH` | 6 | 5 | 60.0 | 50.0 | 54.5 | 100.0 | 83.3 | 90.9 | 16.7 | 0.0 |
| `NATIONAL_ID_HU_TAX` | 5 | 6 | 83.3 | 100.0 | 90.9 | 83.3 | 100.0 | 90.9 | 0.0 | 0.0 |
| `NATIONAL_ID_HU_TAJ` | 5 | 5 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `ID_DOCUMENT` | 10 | 10 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `BANK_ACCOUNT` | 6 | 6 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `COMPANY_ID_HU` | 4 | 4 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | keep | keep |
| `ORGANIZATION` | 9 | 9 | 77.8 | 77.8 | 77.8 | 88.9 | 88.9 | 88.9 | keep | keep |
| `PARCEL_NUMBER_HU` | 6 | 6 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `VEHICLE_PLATE` | 5 | 5 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| **all (micro)** | 120 | 124 | 84.7 | 87.5 | 86.1 | 93.5 | 96.7 | 95.1 | 2.8 | 0.9 |
