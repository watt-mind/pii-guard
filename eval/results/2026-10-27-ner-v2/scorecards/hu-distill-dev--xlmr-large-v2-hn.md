# pii-guard evaluation

- commit: `910a6a27f002 (dirty)`, pii-guard 0.1.0
- detectors: `rules`, `ner`
- fixtures: `eval/generated/distill-s11/labelled/hu-distill-dev.jsonl` sha256 `f6dca4b60ca8dfa5`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `hu` | 368 | 3351 | 3359 | 94.7 | 94.9 | 94.8 | 96.7 | 96.8 | 96.8 | 88.1 | 0.0 | 0.0 | 0.0 | 100.0 | 99.6 | 79.07 | 274.47 |
| **overall** | 368 | 3351 | 3359 | 94.7 | 94.9 | 94.8 | 96.7 | 96.8 | 96.8 | 88.1 | 0.0 | 0.0 | 0.0 | 100.0 | 99.6 | 79.07 | 274.47 |

## Per entity type: `hu`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 1503 | 1502 | 96.5 | 96.4 | 96.4 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `ADDRESS` | 444 | 468 | 94.9 | 100.0 | 97.4 | 94.9 | 100.0 | 97.4 | 0.0 | 0.0 |
| `EMAIL` | 194 | 195 | 99.5 | 100.0 | 99.7 | 99.5 | 100.0 | 99.7 | 0.0 | 0.0 |
| `PHONE` | 326 | 327 | 99.7 | 100.0 | 99.8 | 99.7 | 100.0 | 99.8 | 0.0 | 0.0 |
| `DATE_OF_BIRTH` | 161 | 166 | 93.4 | 96.3 | 94.8 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `NATIONAL_ID_HU_TAX` | 73 | 155 | 47.1 | 100.0 | 64.0 | 47.1 | 100.0 | 64.0 | 0.0 | 0.0 |
| `NATIONAL_ID_HU_TAJ` | 88 | 88 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `ID_DOCUMENT` | 70 | 71 | 98.6 | 100.0 | 99.3 | 98.6 | 100.0 | 99.3 | 0.0 | 0.0 |
| `BANK_ACCOUNT` | 122 | 122 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `COMPANY_ID_HU` | 91 | 8 | 100.0 | 8.8 | 16.2 | 100.0 | 8.8 | 16.2 | keep | keep |
| `ORGANIZATION` | 181 | 183 | 97.3 | 98.3 | 97.8 | 99.5 | 100.0 | 99.7 | keep | keep |
| `PARCEL_NUMBER_HU` | 51 | 27 | 100.0 | 52.9 | 69.2 | 100.0 | 52.9 | 69.2 | 0.0 | 0.0 |
| `VEHICLE_PLATE` | 47 | 47 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| **all (micro)** | 3351 | 3359 | 94.7 | 94.9 | 94.8 | 96.7 | 96.8 | 96.8 | 0.0 | 0.0 |
