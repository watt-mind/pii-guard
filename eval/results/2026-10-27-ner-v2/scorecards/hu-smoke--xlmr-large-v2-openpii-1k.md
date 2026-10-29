# pii-guard evaluation

- commit: `910a6a27f002 (dirty)`, pii-guard 0.1.0
- detectors: `rules`, `ner`
- fixtures: `eval/fixtures/hu-smoke.jsonl` sha256 `3766a651708e8749`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `hu` | 31 | 120 | 124 | 82.3 | 85.0 | 83.6 | 90.3 | 90.8 | 90.6 | 82.2 | 1.9 | 1.9 | 2.6 | 100.0 | 96.2 | 26.07 | 34.78 |
| **overall** | 31 | 120 | 124 | 82.3 | 85.0 | 83.6 | 90.3 | 90.8 | 90.6 | 82.2 | 1.9 | 1.9 | 2.6 | 100.0 | 96.2 | 26.07 | 34.78 |

## Per entity type: `hu`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 38 | 36 | 94.4 | 89.5 | 91.9 | 100.0 | 94.7 | 97.3 | 5.4 | 5.4 |
| `ADDRESS` | 13 | 19 | 68.4 | 100.0 | 81.3 | 68.4 | 100.0 | 81.3 | 0.0 | 0.0 |
| `EMAIL` | 6 | 6 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `PHONE` | 7 | 7 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `DATE_OF_BIRTH` | 6 | 8 | 50.0 | 66.7 | 57.1 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `NATIONAL_ID_HU_TAX` | 5 | 7 | 71.4 | 100.0 | 83.3 | 71.4 | 100.0 | 83.3 | 0.0 | 0.0 |
| `NATIONAL_ID_HU_TAJ` | 5 | 6 | 83.3 | 100.0 | 90.9 | 83.3 | 100.0 | 90.9 | 0.0 | 0.0 |
| `ID_DOCUMENT` | 10 | 13 | 69.2 | 90.0 | 78.3 | 76.9 | 100.0 | 87.0 | 0.0 | 0.0 |
| `BANK_ACCOUNT` | 6 | 6 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `COMPANY_ID_HU` | 4 | 0 | - | 0.0 | 0.0 | - | 0.0 | 0.0 | keep | keep |
| `ORGANIZATION` | 9 | 10 | 70.0 | 77.8 | 73.7 | 100.0 | 100.0 | 100.0 | keep | keep |
| `PARCEL_NUMBER_HU` | 6 | 1 | 100.0 | 16.7 | 28.6 | 100.0 | 16.7 | 28.6 | 0.0 | 0.0 |
| `VEHICLE_PLATE` | 5 | 5 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| **all (micro)** | 120 | 124 | 82.3 | 85.0 | 83.6 | 90.3 | 90.8 | 90.6 | 1.9 | 1.9 |
