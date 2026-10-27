# pii-guard evaluation

- commit: `910a6a27f002 (dirty)`, pii-guard 0.1.0
- detectors: `rules`, `ner_gliner`
- fixtures: `eval/generated/distill-s11/labelled/hu-distill-dev.jsonl` sha256 `f6dca4b60ca8dfa5`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `hu` | 368 | 3351 | 3895 | 77.9 | 90.6 | 83.8 | 80.0 | 93.0 | 86.0 | 93.4 | 7.6 | 5.9 | 19.3 | 89.7 | 92.2 | 173.47 | 712.98 |
| **overall** | 368 | 3351 | 3895 | 77.9 | 90.6 | 83.8 | 80.0 | 93.0 | 86.0 | 93.4 | 7.6 | 5.9 | 19.3 | 89.7 | 92.2 | 173.47 | 712.98 |

## Per entity type: `hu`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 1503 | 1949 | 63.9 | 82.8 | 72.1 | 67.2 | 87.2 | 75.9 | 16.1 | 13.4 |
| `ADDRESS` | 444 | 448 | 99.1 | 100.0 | 99.6 | 99.1 | 100.0 | 99.6 | 0.0 | 0.0 |
| `EMAIL` | 194 | 200 | 97.0 | 100.0 | 98.5 | 97.0 | 100.0 | 98.5 | 0.0 | 12.0 |
| `PHONE` | 326 | 340 | 95.9 | 100.0 | 97.9 | 95.9 | 100.0 | 97.9 | 0.0 | 0.0 |
| `DATE_OF_BIRTH` | 161 | 142 | 90.8 | 80.1 | 85.1 | 94.4 | 83.2 | 88.4 | 16.0 | 0.0 |
| `NATIONAL_ID_HU_TAX` | 73 | 76 | 96.1 | 100.0 | 98.0 | 96.1 | 100.0 | 98.0 | 0.0 | 0.0 |
| `NATIONAL_ID_HU_TAJ` | 88 | 88 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `ID_DOCUMENT` | 70 | 84 | 83.3 | 100.0 | 90.9 | 83.3 | 100.0 | 90.9 | 0.0 | 0.0 |
| `BANK_ACCOUNT` | 122 | 122 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `COMPANY_ID_HU` | 91 | 86 | 100.0 | 94.5 | 97.2 | 100.0 | 94.5 | 97.2 | keep | keep |
| `ORGANIZATION` | 181 | 273 | 63.0 | 95.0 | 75.8 | 66.3 | 100.0 | 79.7 | keep | keep |
| `PARCEL_NUMBER_HU` | 51 | 40 | 100.0 | 78.4 | 87.9 | 100.0 | 78.4 | 87.9 | 22.4 | 0.0 |
| `VEHICLE_PLATE` | 47 | 47 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| **all (micro)** | 3351 | 3895 | 77.9 | 90.6 | 83.8 | 80.0 | 93.0 | 86.0 | 7.6 | 5.9 |
