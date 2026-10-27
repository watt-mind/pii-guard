# pii-guard evaluation

- commit: `910a6a27f002 (dirty)`, pii-guard 0.1.0
- detectors: `rules`, `ner`
- fixtures: `eval/generated/distill-s11/labelled/en-distill-dev.jsonl` sha256 `b13f9983ca99ade6`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `en` | 373 | 2677 | 3428 | 60.5 | 77.5 | 68.0 | 94.5 | 93.9 | 94.2 | 85.0 | 7.2 | 4.9 | 2.5 | 99.7 | 75.4 | 27.25 | 83.04 |
| **overall** | 373 | 2677 | 3428 | 60.5 | 77.5 | 68.0 | 94.5 | 93.9 | 94.2 | 85.0 | 7.2 | 4.9 | 2.5 | 99.7 | 75.4 | 27.25 | 83.04 |

## Per entity type: `en`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 1295 | 1295 | 92.1 | 92.1 | 92.1 | 96.8 | 96.8 | 96.8 | 3.2 | 7.7 |
| `ADDRESS` | 361 | 1156 | 0.0 | 0.0 | 0.0 | 93.8 | 100.0 | 96.8 | 0.0 | 2.5 |
| `EMAIL` | 283 | 283 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 11.0 |
| `PHONE` | 297 | 297 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `DATE_OF_BIRTH` | 108 | 0 | - | 0.0 | 0.0 | - | 0.0 | 0.0 | 100.0 | 0.0 |
| `ID_DOCUMENT` | 47 | 46 | 100.0 | 97.9 | 98.9 | 100.0 | 97.9 | 98.9 | 2.1 | 0.0 |
| `BANK_ACCOUNT` | 98 | 98 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `ORGANIZATION` | 135 | 203 | 53.2 | 80.0 | 63.9 | 62.6 | 94.1 | 75.1 | keep | keep |
| `VEHICLE_PLATE` | 53 | 50 | 100.0 | 94.3 | 97.1 | 100.0 | 94.3 | 97.1 | 5.1 | 0.0 |
| **all (micro)** | 2677 | 3428 | 60.5 | 77.5 | 68.0 | 94.5 | 93.9 | 94.2 | 7.2 | 4.9 |
