# pii-guard evaluation

- commit: `0ba3c1a50e8c (dirty)`, pii-guard 0.1.0
- detectors: `rules`, `ner`
- fixtures: `eval/generated/ner-s7/hu-synth-dev.jsonl` sha256 `ed64235a130a0b5a`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `hu` | 24 | 319 | 395 | 58.2 | 72.1 | 64.4 | 95.9 | 87.5 | 91.5 | 76.1 | 18.0 | 0.0 | 3.7 | 95.8 | 182.53 | 381.09 |
| **overall** | 24 | 319 | 395 | 58.2 | 72.1 | 64.4 | 95.9 | 87.5 | 91.5 | 76.1 | 18.0 | 0.0 | 3.7 | 95.8 | 182.53 | 381.09 |

## Per entity type: `hu`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 115 | 120 | 94.2 | 98.3 | 96.2 | 98.3 | 100.0 | 99.2 | 0.0 | 0.0 |
| `ADDRESS` | 46 | 154 | 0.0 | 0.0 | 0.0 | 92.9 | 100.0 | 96.3 | 0.0 | 0.0 |
| `EMAIL` | 14 | 14 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `PHONE` | 20 | 20 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `DATE_OF_BIRTH` | 21 | 0 | - | 0.0 | 0.0 | - | 0.0 | 0.0 | 100.0 | 0.0 |
| `NATIONAL_ID_HU_TAX` | 13 | 13 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `NATIONAL_ID_HU_TAJ` | 10 | 10 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `ID_DOCUMENT` | 12 | 0 | - | 0.0 | 0.0 | - | 0.0 | 0.0 | 100.0 | 0.0 |
| `BANK_ACCOUNT` | 19 | 19 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `COMPANY_ID_HU` | 12 | 12 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | keep | keep |
| `ORGANIZATION` | 25 | 28 | 85.7 | 96.0 | 90.6 | 89.3 | 100.0 | 94.3 | keep | keep |
| `PARCEL_NUMBER_HU` | 7 | 0 | - | 0.0 | 0.0 | - | 0.0 | 0.0 | 100.0 | 0.0 |
| `VEHICLE_PLATE` | 5 | 5 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| **all (micro)** | 319 | 395 | 58.2 | 72.1 | 64.4 | 95.9 | 87.5 | 91.5 | 18.0 | 0.0 |
