# pii-guard evaluation

- commit: `c611f9935cbe (dirty)`, pii-guard 0.1.0
- detectors: `rules`, `ner`
- fixtures: `eval/generated/distill-s11/en-distill-dev.jsonl` sha256 `52844202fd84cac1`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `en` | 373 | 2632 | 2717 | 96.6 | 99.7 | 98.1 | 96.7 | 99.8 | 98.2 | 88.7 | 0.1 | 1.3 | 3.4 | 99.2 | 99.8 | 130.92 | 341.12 |
| **overall** | 373 | 2632 | 2717 | 96.6 | 99.7 | 98.1 | 96.7 | 99.8 | 98.2 | 88.7 | 0.1 | 1.3 | 3.4 | 99.2 | 99.8 | 130.92 | 341.12 |

## Per entity type: `en`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 1257 | 1289 | 97.5 | 100.0 | 98.7 | 97.5 | 100.0 | 98.7 | 0.0 | 0.0 |
| `ADDRESS` | 361 | 418 | 86.1 | 99.7 | 92.4 | 86.6 | 100.0 | 92.8 | 0.0 | 7.6 |
| `EMAIL` | 283 | 283 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `PHONE` | 297 | 297 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `DATE_OF_BIRTH` | 108 | 107 | 100.0 | 99.1 | 99.5 | 100.0 | 99.1 | 99.5 | 0.0 | 0.0 |
| `NATIONAL_ID_HU_TAJ` | 0 | 1 | 0.0 | - | 0.0 | 0.0 | - | 0.0 | keep | keep |
| `ID_DOCUMENT` | 47 | 46 | 100.0 | 97.9 | 98.9 | 100.0 | 97.9 | 98.9 | 0.0 | 0.0 |
| `BANK_ACCOUNT` | 98 | 98 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `ORGANIZATION` | 128 | 128 | 99.2 | 99.2 | 99.2 | 100.0 | 100.0 | 100.0 | keep | keep |
| `VEHICLE_PLATE` | 53 | 50 | 100.0 | 94.3 | 97.1 | 100.0 | 94.3 | 97.1 | 5.1 | 0.0 |
| **all (micro)** | 2632 | 2717 | 96.6 | 99.7 | 98.1 | 96.7 | 99.8 | 98.2 | 0.1 | 1.3 |
