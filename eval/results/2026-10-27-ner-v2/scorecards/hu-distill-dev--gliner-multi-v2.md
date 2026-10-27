# pii-guard evaluation

- commit: `910a6a27f002 (dirty)`, pii-guard 0.1.0
- detectors: `rules`, `ner_gliner`
- fixtures: `eval/generated/distill-s11/labelled/hu-distill-dev.jsonl` sha256 `f6dca4b60ca8dfa5`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `hu` | 368 | 3351 | 3428 | 92.4 | 94.6 | 93.5 | 94.3 | 96.5 | 95.4 | 85.2 | 0.1 | 0.0 | 2.5 | 100.0 | 99.9 | 161.40 | 652.56 |
| **overall** | 368 | 3351 | 3428 | 92.4 | 94.6 | 93.5 | 94.3 | 96.5 | 95.4 | 85.2 | 0.1 | 0.0 | 2.5 | 100.0 | 99.9 | 161.40 | 652.56 |

## Per entity type: `hu`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 1503 | 1500 | 95.7 | 95.5 | 95.6 | 99.9 | 99.8 | 99.8 | 0.4 | 0.0 |
| `ADDRESS` | 444 | 524 | 84.5 | 99.8 | 91.5 | 84.7 | 100.0 | 91.7 | 0.0 | 0.0 |
| `EMAIL` | 194 | 194 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `PHONE` | 326 | 327 | 99.7 | 100.0 | 99.8 | 99.7 | 100.0 | 99.8 | 0.0 | 0.0 |
| `DATE_OF_BIRTH` | 161 | 160 | 100.0 | 99.4 | 99.7 | 100.0 | 99.4 | 99.7 | 0.0 | 0.0 |
| `NATIONAL_ID_HU_TAX` | 73 | 118 | 61.9 | 100.0 | 76.4 | 61.9 | 100.0 | 76.4 | 0.0 | 0.0 |
| `NATIONAL_ID_HU_TAJ` | 88 | 88 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `ID_DOCUMENT` | 70 | 136 | 51.5 | 100.0 | 68.0 | 51.5 | 100.0 | 68.0 | 0.0 | 0.0 |
| `BANK_ACCOUNT` | 122 | 122 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `COMPANY_ID_HU` | 91 | 14 | 100.0 | 15.4 | 26.7 | 100.0 | 15.4 | 26.7 | keep | keep |
| `ORGANIZATION` | 181 | 183 | 98.9 | 100.0 | 99.5 | 98.9 | 100.0 | 99.5 | keep | keep |
| `PARCEL_NUMBER_HU` | 51 | 15 | 100.0 | 29.4 | 45.5 | 100.0 | 29.4 | 45.5 | 0.0 | 0.0 |
| `VEHICLE_PLATE` | 47 | 47 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| **all (micro)** | 3351 | 3428 | 92.4 | 94.6 | 93.5 | 94.3 | 96.5 | 95.4 | 0.1 | 0.0 |
