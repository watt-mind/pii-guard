# pii-guard evaluation

- commit: `910a6a27f002 (dirty)`, pii-guard 0.1.0
- detectors: `rules`, `ner`
- fixtures: `eval/generated/distill-s11/labelled/hu-distill-dev.jsonl` sha256 `f6dca4b60ca8dfa5`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `hu` | 368 | 3351 | 3370 | 93.6 | 94.2 | 93.9 | 96.1 | 96.3 | 96.2 | 85.1 | 0.0 | 0.0 | 0.1 | 100.0 | 99.3 | 69.81 | 249.64 |
| **overall** | 368 | 3351 | 3370 | 93.6 | 94.2 | 93.9 | 96.1 | 96.3 | 96.2 | 85.1 | 0.0 | 0.0 | 0.1 | 100.0 | 99.3 | 69.81 | 249.64 |

## Per entity type: `hu`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 1503 | 1501 | 96.8 | 96.7 | 96.7 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `ADDRESS` | 444 | 481 | 92.3 | 100.0 | 96.0 | 92.3 | 100.0 | 96.0 | 0.0 | 0.0 |
| `EMAIL` | 194 | 195 | 99.5 | 100.0 | 99.7 | 99.5 | 100.0 | 99.7 | 0.0 | 0.0 |
| `PHONE` | 326 | 327 | 99.7 | 100.0 | 99.8 | 99.7 | 100.0 | 99.8 | 0.0 | 0.0 |
| `DATE_OF_BIRTH` | 161 | 175 | 83.4 | 90.7 | 86.9 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `NATIONAL_ID_HU_TAX` | 73 | 154 | 47.4 | 100.0 | 64.3 | 47.4 | 100.0 | 64.3 | 0.0 | 0.0 |
| `NATIONAL_ID_HU_TAJ` | 88 | 88 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `ID_DOCUMENT` | 70 | 78 | 89.7 | 100.0 | 94.6 | 89.7 | 100.0 | 94.6 | 0.0 | 0.0 |
| `BANK_ACCOUNT` | 122 | 122 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `COMPANY_ID_HU` | 91 | 1 | 100.0 | 1.1 | 2.2 | 100.0 | 1.1 | 2.2 | keep | keep |
| `ORGANIZATION` | 181 | 184 | 95.1 | 96.7 | 95.9 | 98.9 | 100.0 | 99.5 | keep | keep |
| `PARCEL_NUMBER_HU` | 51 | 17 | 100.0 | 33.3 | 50.0 | 100.0 | 33.3 | 50.0 | 0.0 | 0.0 |
| `VEHICLE_PLATE` | 47 | 47 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| **all (micro)** | 3351 | 3370 | 93.6 | 94.2 | 93.9 | 96.1 | 96.3 | 96.2 | 0.0 | 0.0 |
