# pii-guard evaluation

- commit: `910a6a27f002 (dirty)`, pii-guard 0.1.0
- detectors: `rules`, `ner`, `ner_gliner`
- fixtures: `eval/generated/distill-s11/labelled/en-distill-dev.jsonl` sha256 `b13f9983ca99ade6`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `en` | 373 | 2677 | 3457 | 76.6 | 98.9 | 86.3 | 77.2 | 99.7 | 87.1 | 92.7 | 0.2 | 1.3 | 22.1 | 83.9 | 99.8 | 125.29 | 371.75 |
| **overall** | 373 | 2677 | 3457 | 76.6 | 98.9 | 86.3 | 77.2 | 99.7 | 87.1 | 92.7 | 0.2 | 1.3 | 22.1 | 83.9 | 99.8 | 125.29 | 371.75 |

## Per entity type: `en`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 1295 | 1972 | 64.6 | 98.3 | 77.9 | 65.5 | 99.8 | 79.1 | 0.4 | 0.0 |
| `ADDRESS` | 361 | 368 | 98.1 | 100.0 | 99.0 | 98.1 | 100.0 | 99.0 | 0.0 | 7.6 |
| `EMAIL` | 283 | 291 | 97.3 | 100.0 | 98.6 | 97.3 | 100.0 | 98.6 | 0.0 | 0.0 |
| `PHONE` | 297 | 298 | 99.7 | 100.0 | 99.8 | 99.7 | 100.0 | 99.8 | 0.0 | 0.0 |
| `DATE_OF_BIRTH` | 108 | 109 | 99.1 | 100.0 | 99.5 | 99.1 | 100.0 | 99.5 | 0.0 | 0.0 |
| `ID_DOCUMENT` | 47 | 66 | 68.2 | 95.7 | 79.6 | 71.2 | 100.0 | 83.2 | 0.0 | 0.0 |
| `BANK_ACCOUNT` | 98 | 102 | 96.1 | 100.0 | 98.0 | 96.1 | 100.0 | 98.0 | 0.0 | 0.0 |
| `ORGANIZATION` | 135 | 201 | 66.2 | 98.5 | 79.2 | 66.7 | 99.3 | 79.8 | keep | keep |
| `VEHICLE_PLATE` | 53 | 50 | 100.0 | 94.3 | 97.1 | 100.0 | 94.3 | 97.1 | 0.0 | 0.0 |
| **all (micro)** | 2677 | 3457 | 76.6 | 98.9 | 86.3 | 77.2 | 99.7 | 87.1 | 0.2 | 1.3 |
