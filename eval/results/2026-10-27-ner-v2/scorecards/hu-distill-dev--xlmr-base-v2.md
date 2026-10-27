# pii-guard evaluation

- commit: `910a6a27f002 (dirty)`, pii-guard 0.1.0
- detectors: `rules`, `ner`
- fixtures: `eval/generated/distill-s11/labelled/hu-distill-dev.jsonl` sha256 `f6dca4b60ca8dfa5`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `hu` | 368 | 3351 | 3351 | 95.3 | 95.3 | 95.3 | 96.3 | 96.4 | 96.3 | 85.1 | 0.0 | 0.0 | 0.0 | 100.0 | 99.9 | 25.72 | 63.16 |
| **overall** | 368 | 3351 | 3351 | 95.3 | 95.3 | 95.3 | 96.3 | 96.4 | 96.3 | 85.1 | 0.0 | 0.0 | 0.0 | 100.0 | 99.9 | 25.72 | 63.16 |

## Per entity type: `hu`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 1503 | 1501 | 97.9 | 97.8 | 97.9 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `ADDRESS` | 444 | 474 | 93.7 | 100.0 | 96.7 | 93.7 | 100.0 | 96.7 | 0.0 | 0.0 |
| `EMAIL` | 194 | 194 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `PHONE` | 326 | 327 | 99.7 | 100.0 | 99.8 | 99.7 | 100.0 | 99.8 | 0.0 | 0.0 |
| `DATE_OF_BIRTH` | 161 | 161 | 99.4 | 99.4 | 99.4 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `NATIONAL_ID_HU_TAX` | 73 | 142 | 51.4 | 100.0 | 67.9 | 51.4 | 100.0 | 67.9 | 0.0 | 0.0 |
| `NATIONAL_ID_HU_TAJ` | 88 | 89 | 98.9 | 100.0 | 99.4 | 98.9 | 100.0 | 99.4 | 0.0 | 0.0 |
| `ID_DOCUMENT` | 70 | 92 | 76.1 | 100.0 | 86.4 | 76.1 | 100.0 | 86.4 | 0.0 | 0.0 |
| `BANK_ACCOUNT` | 122 | 122 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `COMPANY_ID_HU` | 91 | 0 | - | 0.0 | 0.0 | - | 0.0 | 0.0 | keep | keep |
| `ORGANIZATION` | 181 | 182 | 98.4 | 98.9 | 98.6 | 99.5 | 100.0 | 99.7 | keep | keep |
| `PARCEL_NUMBER_HU` | 51 | 20 | 100.0 | 39.2 | 56.3 | 100.0 | 39.2 | 56.3 | 0.0 | 0.0 |
| `VEHICLE_PLATE` | 47 | 47 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| **all (micro)** | 3351 | 3351 | 95.3 | 95.3 | 95.3 | 96.3 | 96.4 | 96.3 | 0.0 | 0.0 |
