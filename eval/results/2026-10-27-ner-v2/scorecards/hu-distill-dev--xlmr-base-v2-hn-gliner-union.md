# pii-guard evaluation

- commit: `910a6a27f002 (dirty)`, pii-guard 0.1.0
- detectors: `rules`, `ner`, `ner_gliner`
- fixtures: `eval/generated/distill-s11/labelled/hu-distill-dev.jsonl` sha256 `f6dca4b60ca8dfa5`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `hu` | 368 | 3351 | 4125 | 76.5 | 94.2 | 84.4 | 78.3 | 96.4 | 86.4 | 81.8 | 0.0 | 0.0 | 17.8 | 89.7 | 99.7 | 165.74 | 589.61 |
| **overall** | 368 | 3351 | 4125 | 76.5 | 94.2 | 84.4 | 78.3 | 96.4 | 86.4 | 81.8 | 0.0 | 0.0 | 17.8 | 89.7 | 99.7 | 165.74 | 589.61 |

## Per entity type: `hu`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 1503 | 2140 | 66.9 | 95.2 | 78.6 | 70.1 | 100.0 | 82.4 | 0.0 | 0.0 |
| `ADDRESS` | 444 | 478 | 92.9 | 100.0 | 96.3 | 92.9 | 100.0 | 96.3 | 0.0 | 0.0 |
| `EMAIL` | 194 | 200 | 97.0 | 100.0 | 98.5 | 97.0 | 100.0 | 98.5 | 0.0 | 0.0 |
| `PHONE` | 326 | 340 | 95.9 | 100.0 | 97.9 | 95.9 | 100.0 | 97.9 | 0.0 | 0.0 |
| `DATE_OF_BIRTH` | 161 | 169 | 94.1 | 98.8 | 96.4 | 95.3 | 100.0 | 97.6 | 0.0 | 0.0 |
| `NATIONAL_ID_HU_TAX` | 73 | 164 | 44.5 | 100.0 | 61.6 | 44.5 | 100.0 | 61.6 | 0.0 | 0.0 |
| `NATIONAL_ID_HU_TAJ` | 88 | 88 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `ID_DOCUMENT` | 70 | 83 | 84.3 | 100.0 | 91.5 | 84.3 | 100.0 | 91.5 | 0.0 | 0.0 |
| `BANK_ACCOUNT` | 122 | 122 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `COMPANY_ID_HU` | 91 | 4 | 100.0 | 4.4 | 8.4 | 100.0 | 4.4 | 8.4 | keep | keep |
| `ORGANIZATION` | 181 | 273 | 66.3 | 100.0 | 79.7 | 66.3 | 100.0 | 79.7 | keep | keep |
| `PARCEL_NUMBER_HU` | 51 | 17 | 100.0 | 33.3 | 50.0 | 100.0 | 33.3 | 50.0 | 0.0 | 0.0 |
| `VEHICLE_PLATE` | 47 | 47 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| **all (micro)** | 3351 | 4125 | 76.5 | 94.2 | 84.4 | 78.3 | 96.4 | 86.4 | 0.0 | 0.0 |
