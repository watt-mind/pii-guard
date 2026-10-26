# pii-guard evaluation

- commit: `0ba3c1a50e8c (dirty)`, pii-guard 0.1.0
- detectors: `rules`
- fixtures: `eval/fixtures/hu-synth-sample.jsonl` sha256 `ed547228ddc329bb`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `hu` | 20 | 271 | 110 | 64.5 | 26.2 | 37.3 | 100.0 | 40.6 | 57.7 | 61.5 | 50.3 | 22.5 | 0.0 | 100.0 | 0.80 | 1.61 |
| **overall** | 20 | 271 | 110 | 64.5 | 26.2 | 37.3 | 100.0 | 40.6 | 57.7 | 61.5 | 50.3 | 22.5 | 0.0 | 100.0 | 0.80 | 1.61 |

## Per entity type: `hu`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 107 | 0 | - | 0.0 | 0.0 | - | 0.0 | 0.0 | 100.0 | 0.0 |
| `ADDRESS` | 39 | 39 | 0.0 | 0.0 | 0.0 | 100.0 | 100.0 | 100.0 | 0.0 | 94.9 |
| `EMAIL` | 9 | 9 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 28.6 |
| `PHONE` | 14 | 14 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `DATE_OF_BIRTH` | 17 | 0 | - | 0.0 | 0.0 | - | 0.0 | 0.0 | 100.0 | 0.0 |
| `NATIONAL_ID_HU_TAX` | 8 | 8 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `NATIONAL_ID_HU_TAJ` | 5 | 5 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `ID_DOCUMENT` | 8 | 0 | - | 0.0 | 0.0 | - | 0.0 | 0.0 | 100.0 | 0.0 |
| `BANK_ACCOUNT` | 17 | 17 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `COMPANY_ID_HU` | 10 | 10 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | keep | keep |
| `ORGANIZATION` | 22 | 0 | - | 0.0 | 0.0 | - | 0.0 | 0.0 | keep | keep |
| `PARCEL_NUMBER_HU` | 7 | 0 | - | 0.0 | 0.0 | - | 0.0 | 0.0 | 100.0 | 0.0 |
| `VEHICLE_PLATE` | 8 | 8 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| **all (micro)** | 271 | 110 | 64.5 | 26.2 | 37.3 | 100.0 | 40.6 | 57.7 | 50.3 | 22.5 |
