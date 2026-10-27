# pii-guard evaluation

- commit: `910a6a27f002 (dirty)`, pii-guard 0.1.0
- detectors: `rules`, `ner`
- fixtures: `eval/generated/distill-s11/labelled/hu-distill-dev.jsonl` sha256 `f6dca4b60ca8dfa5`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `hu` | 368 | 3351 | 3351 | 96.0 | 96.0 | 96.0 | 96.8 | 96.9 | 96.9 | 87.5 | 0.0 | 0.0 | 0.0 | 100.0 | 99.9 | 23.26 | 59.57 |
| **overall** | 368 | 3351 | 3351 | 96.0 | 96.0 | 96.0 | 96.8 | 96.9 | 96.9 | 87.5 | 0.0 | 0.0 | 0.0 | 100.0 | 99.9 | 23.26 | 59.57 |

## Per entity type: `hu`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 1503 | 1502 | 98.3 | 98.2 | 98.2 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `ADDRESS` | 444 | 444 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `EMAIL` | 194 | 194 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `PHONE` | 326 | 328 | 99.4 | 100.0 | 99.7 | 99.4 | 100.0 | 99.7 | 0.0 | 0.0 |
| `DATE_OF_BIRTH` | 161 | 161 | 99.4 | 99.4 | 99.4 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `NATIONAL_ID_HU_TAX` | 73 | 84 | 86.9 | 100.0 | 93.0 | 86.9 | 100.0 | 93.0 | 0.0 | 0.0 |
| `NATIONAL_ID_HU_TAJ` | 88 | 150 | 58.7 | 100.0 | 73.9 | 58.7 | 100.0 | 73.9 | 0.0 | 0.0 |
| `ID_DOCUMENT` | 70 | 88 | 79.5 | 100.0 | 88.6 | 79.5 | 100.0 | 88.6 | 0.0 | 0.0 |
| `BANK_ACCOUNT` | 122 | 134 | 91.0 | 100.0 | 95.3 | 91.0 | 100.0 | 95.3 | 0.0 | 0.0 |
| `COMPANY_ID_HU` | 91 | 4 | 100.0 | 4.4 | 8.4 | 100.0 | 4.4 | 8.4 | keep | keep |
| `ORGANIZATION` | 181 | 182 | 98.9 | 99.4 | 99.2 | 99.5 | 100.0 | 99.7 | keep | keep |
| `PARCEL_NUMBER_HU` | 51 | 33 | 100.0 | 64.7 | 78.6 | 100.0 | 64.7 | 78.6 | 0.0 | 0.0 |
| `VEHICLE_PLATE` | 47 | 47 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| **all (micro)** | 3351 | 3351 | 96.0 | 96.0 | 96.0 | 96.8 | 96.9 | 96.9 | 0.0 | 0.0 |
