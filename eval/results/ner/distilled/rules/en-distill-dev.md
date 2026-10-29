# pii-guard evaluation

- commit: `c611f9935cbe (dirty)`, pii-guard 0.1.0
- detectors: `rules`
- fixtures: `eval/generated/distill-s11/en-distill-dev.jsonl` sha256 `52844202fd84cac1`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `en` | 373 | 2632 | 1137 | 68.1 | 29.4 | 41.1 | 99.8 | 43.1 | 60.2 | 59.6 | 44.8 | 23.9 | 0.1 | 100.0 | 55.2 | 0.66 | 7.27 |
| **overall** | 373 | 2632 | 1137 | 68.1 | 29.4 | 41.1 | 99.8 | 43.1 | 60.2 | 59.6 | 44.8 | 23.9 | 0.1 | 100.0 | 55.2 | 0.66 | 7.27 |

## Per entity type: `en`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 1257 | 0 | - | 0.0 | 0.0 | - | 0.0 | 0.0 | 100.0 | 0.0 |
| `ADDRESS` | 361 | 362 | 0.0 | 0.0 | 0.0 | 99.7 | 100.0 | 99.9 | 0.0 | 100.0 |
| `EMAIL` | 283 | 283 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 48.5 |
| `PHONE` | 297 | 297 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `DATE_OF_BIRTH` | 108 | 0 | - | 0.0 | 0.0 | - | 0.0 | 0.0 | 100.0 | 0.0 |
| `NATIONAL_ID_HU_TAJ` | 0 | 1 | 0.0 | - | 0.0 | 0.0 | - | 0.0 | keep | keep |
| `ID_DOCUMENT` | 47 | 46 | 100.0 | 97.9 | 98.9 | 100.0 | 97.9 | 98.9 | 0.0 | 0.0 |
| `BANK_ACCOUNT` | 98 | 98 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `ORGANIZATION` | 128 | 0 | - | 0.0 | 0.0 | - | 0.0 | 0.0 | keep | keep |
| `VEHICLE_PLATE` | 53 | 50 | 100.0 | 94.3 | 97.1 | 100.0 | 94.3 | 97.1 | 5.1 | 0.0 |
| **all (micro)** | 2632 | 1137 | 68.1 | 29.4 | 41.1 | 99.8 | 43.1 | 60.2 | 44.8 | 23.9 |
