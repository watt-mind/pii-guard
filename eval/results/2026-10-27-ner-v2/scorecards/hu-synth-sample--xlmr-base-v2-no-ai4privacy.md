# pii-guard evaluation

- commit: `910a6a27f002 (dirty)`, pii-guard 0.1.0
- detectors: `rules`, `ner`
- fixtures: `eval/fixtures/hu-synth-sample.jsonl` sha256 `ed547228ddc329bb`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `hu` | 20 | 271 | 271 | 95.9 | 95.9 | 95.9 | 95.9 | 95.9 | 95.9 | 87.1 | 0.0 | 0.0 | 0.0 | 100.0 | 100.0 | 27.48 | 50.81 |
| **overall** | 20 | 271 | 271 | 95.9 | 95.9 | 95.9 | 95.9 | 95.9 | 95.9 | 87.1 | 0.0 | 0.0 | 0.0 | 100.0 | 100.0 | 27.48 | 50.81 |

## Per entity type: `hu`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 107 | 107 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `ADDRESS` | 39 | 39 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `EMAIL` | 9 | 9 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `PHONE` | 14 | 14 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `DATE_OF_BIRTH` | 17 | 17 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `NATIONAL_ID_HU_TAX` | 8 | 9 | 88.9 | 100.0 | 94.1 | 88.9 | 100.0 | 94.1 | 0.0 | 0.0 |
| `NATIONAL_ID_HU_TAJ` | 5 | 11 | 45.5 | 100.0 | 62.5 | 45.5 | 100.0 | 62.5 | 0.0 | 0.0 |
| `ID_DOCUMENT` | 8 | 10 | 80.0 | 100.0 | 88.9 | 80.0 | 100.0 | 88.9 | 0.0 | 0.0 |
| `BANK_ACCOUNT` | 17 | 19 | 89.5 | 100.0 | 94.4 | 89.5 | 100.0 | 94.4 | 0.0 | 0.0 |
| `COMPANY_ID_HU` | 10 | 0 | - | 0.0 | 0.0 | - | 0.0 | 0.0 | keep | keep |
| `ORGANIZATION` | 22 | 22 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | keep | keep |
| `PARCEL_NUMBER_HU` | 7 | 6 | 100.0 | 85.7 | 92.3 | 100.0 | 85.7 | 92.3 | 0.0 | 0.0 |
| `VEHICLE_PLATE` | 8 | 8 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| **all (micro)** | 271 | 271 | 95.9 | 95.9 | 95.9 | 95.9 | 95.9 | 95.9 | 0.0 | 0.0 |
