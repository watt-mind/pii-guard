# pii-guard evaluation

- commit: `910a6a27f002 (dirty)`, pii-guard 0.1.0
- detectors: `rules`, `ner`
- fixtures: `eval/generated/distill-s11/labelled/hu-distill-dev.jsonl` sha256 `f6dca4b60ca8dfa5`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `hu` | 368 | 3351 | 3355 | 95.1 | 95.2 | 95.1 | 96.8 | 96.7 | 96.7 | 86.4 | 0.0 | 0.0 | 0.0 | 100.0 | 99.5 | 87.77 | 327.63 |
| **overall** | 368 | 3351 | 3355 | 95.1 | 95.2 | 95.1 | 96.8 | 96.7 | 96.7 | 86.4 | 0.0 | 0.0 | 0.0 | 100.0 | 99.5 | 87.77 | 327.63 |

## Per entity type: `hu`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 1503 | 1501 | 97.4 | 97.3 | 97.3 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `ADDRESS` | 444 | 444 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `EMAIL` | 194 | 194 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `PHONE` | 326 | 327 | 99.7 | 100.0 | 99.8 | 99.7 | 100.0 | 99.8 | 0.0 | 0.0 |
| `DATE_OF_BIRTH` | 161 | 167 | 92.2 | 95.7 | 93.9 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `NATIONAL_ID_HU_TAX` | 73 | 118 | 61.9 | 100.0 | 76.4 | 61.9 | 100.0 | 76.4 | 0.0 | 0.0 |
| `NATIONAL_ID_HU_TAJ` | 88 | 89 | 98.9 | 100.0 | 99.4 | 98.9 | 100.0 | 99.4 | 0.0 | 0.0 |
| `ID_DOCUMENT` | 70 | 131 | 53.4 | 100.0 | 69.7 | 53.4 | 100.0 | 69.7 | 0.0 | 0.0 |
| `BANK_ACCOUNT` | 122 | 122 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `COMPANY_ID_HU` | 91 | 0 | - | 0.0 | 0.0 | - | 0.0 | 0.0 | keep | keep |
| `ORGANIZATION` | 181 | 182 | 97.3 | 97.8 | 97.5 | 99.5 | 100.0 | 99.7 | keep | keep |
| `PARCEL_NUMBER_HU` | 51 | 33 | 100.0 | 64.7 | 78.6 | 100.0 | 64.7 | 78.6 | 2.0 | 0.0 |
| `VEHICLE_PLATE` | 47 | 47 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| **all (micro)** | 3351 | 3355 | 95.1 | 95.2 | 95.1 | 96.8 | 96.7 | 96.7 | 0.0 | 0.0 |
