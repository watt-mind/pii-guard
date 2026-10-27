# pii-guard evaluation

- commit: `910a6a27f002 (dirty)`, pii-guard 0.1.0
- detectors: `rules`, `ner_gliner`
- fixtures: `eval/generated/distill-s11/labelled/en-distill-dev.jsonl` sha256 `b13f9983ca99ade6`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `en` | 373 | 2677 | 2830 | 94.3 | 99.7 | 97.0 | 94.3 | 99.7 | 97.0 | 93.1 | 0.2 | 1.3 | 5.2 | 99.7 | 99.8 | 106.62 | 333.08 |
| **overall** | 373 | 2677 | 2830 | 94.3 | 99.7 | 97.0 | 94.3 | 99.7 | 97.0 | 93.1 | 0.2 | 1.3 | 5.2 | 99.7 | 99.8 | 106.62 | 333.08 |

## Per entity type: `en`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 1295 | 1300 | 99.5 | 99.8 | 99.7 | 99.5 | 99.8 | 99.7 | 0.3 | 0.0 |
| `ADDRESS` | 361 | 424 | 85.1 | 100.0 | 92.0 | 85.1 | 100.0 | 92.0 | 0.0 | 7.6 |
| `EMAIL` | 283 | 283 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `PHONE` | 297 | 298 | 99.7 | 100.0 | 99.8 | 99.7 | 100.0 | 99.8 | 0.0 | 0.0 |
| `DATE_OF_BIRTH` | 108 | 107 | 100.0 | 99.1 | 99.5 | 100.0 | 99.1 | 99.5 | 0.0 | 0.0 |
| `ID_DOCUMENT` | 47 | 117 | 39.3 | 97.9 | 56.1 | 39.3 | 97.9 | 56.1 | 2.1 | 0.0 |
| `BANK_ACCOUNT` | 98 | 99 | 99.0 | 100.0 | 99.5 | 99.0 | 100.0 | 99.5 | 0.0 | 0.0 |
| `ORGANIZATION` | 135 | 152 | 88.8 | 100.0 | 94.1 | 88.8 | 100.0 | 94.1 | keep | keep |
| `VEHICLE_PLATE` | 53 | 50 | 100.0 | 94.3 | 97.1 | 100.0 | 94.3 | 97.1 | 0.0 | 0.0 |
| **all (micro)** | 2677 | 2830 | 94.3 | 99.7 | 97.0 | 94.3 | 99.7 | 97.0 | 0.2 | 1.3 |
