# pii-guard evaluation

- commit: `910a6a27f002 (dirty)`, pii-guard 0.1.0
- detectors: `rules`, `ner`
- fixtures: `eval/generated/distill-s11/labelled/hu-distill-dev.jsonl` sha256 `f6dca4b60ca8dfa5`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `hu` | 368 | 3351 | 3296 | 90.4 | 89.0 | 89.7 | 95.9 | 94.4 | 95.1 | 90.1 | 7.7 | 3.5 | 3.5 | 98.4 | 91.5 | 28.56 | 84.52 |
| **overall** | 368 | 3351 | 3296 | 90.4 | 89.0 | 89.7 | 95.9 | 94.4 | 95.1 | 90.1 | 7.7 | 3.5 | 3.5 | 98.4 | 91.5 | 28.56 | 84.52 |

## Per entity type: `hu`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 1503 | 1527 | 87.7 | 89.1 | 88.4 | 98.0 | 99.6 | 98.8 | 0.4 | 8.6 |
| `ADDRESS` | 444 | 537 | 81.2 | 98.2 | 88.9 | 82.7 | 100.0 | 90.5 | 0.0 | 0.0 |
| `EMAIL` | 194 | 194 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 3.8 |
| `PHONE` | 326 | 327 | 99.7 | 100.0 | 99.8 | 99.7 | 100.0 | 99.8 | 0.0 | 0.0 |
| `DATE_OF_BIRTH` | 161 | 0 | - | 0.0 | 0.0 | - | 0.0 | 0.0 | 100.0 | 0.0 |
| `NATIONAL_ID_HU_TAX` | 73 | 73 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `NATIONAL_ID_HU_TAJ` | 88 | 88 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `ID_DOCUMENT` | 70 | 70 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `BANK_ACCOUNT` | 122 | 122 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `COMPANY_ID_HU` | 91 | 90 | 100.0 | 98.9 | 99.4 | 100.0 | 98.9 | 99.4 | keep | keep |
| `ORGANIZATION` | 181 | 181 | 86.2 | 86.2 | 86.2 | 94.5 | 94.5 | 94.5 | keep | keep |
| `PARCEL_NUMBER_HU` | 51 | 40 | 100.0 | 78.4 | 87.9 | 100.0 | 78.4 | 87.9 | 22.4 | 0.0 |
| `VEHICLE_PLATE` | 47 | 47 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| **all (micro)** | 3351 | 3296 | 90.4 | 89.0 | 89.7 | 95.9 | 94.4 | 95.1 | 7.7 | 3.5 |
