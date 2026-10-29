# pii-guard evaluation

- commit: `910a6a27f002 (dirty)`, pii-guard 0.1.0
- detectors: `rules`, `ner_gliner`
- fixtures: `eval/generated/distill-s11/labelled/en-distill-dev.jsonl` sha256 `b13f9983ca99ade6`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `en` | 373 | 2677 | 3557 | 56.7 | 75.3 | 64.7 | 77.9 | 89.6 | 83.3 | 91.0 | 7.8 | 24.0 | 21.3 | 83.9 | 76.0 | 123.71 | 368.21 |
| **overall** | 373 | 2677 | 3557 | 56.7 | 75.3 | 64.7 | 77.9 | 89.6 | 83.3 | 91.0 | 7.8 | 24.0 | 21.3 | 83.9 | 76.0 | 123.71 | 368.21 |

## Per entity type: `en`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 1295 | 1707 | 59.2 | 78.0 | 67.3 | 60.3 | 79.5 | 68.6 | 18.5 | 14.7 |
| `ADDRESS` | 361 | 741 | 0.1 | 0.3 | 0.2 | 98.9 | 100.0 | 99.5 | 0.0 | 97.8 |
| `EMAIL` | 283 | 292 | 96.9 | 100.0 | 98.4 | 96.9 | 100.0 | 98.4 | 0.0 | 10.5 |
| `PHONE` | 297 | 298 | 99.7 | 100.0 | 99.8 | 99.7 | 100.0 | 99.8 | 0.0 | 0.0 |
| `DATE_OF_BIRTH` | 108 | 101 | 99.0 | 92.6 | 95.7 | 99.0 | 92.6 | 95.7 | 6.6 | 0.0 |
| `ID_DOCUMENT` | 47 | 64 | 71.9 | 97.9 | 82.9 | 71.9 | 97.9 | 82.9 | 0.0 | 0.0 |
| `BANK_ACCOUNT` | 98 | 102 | 96.1 | 100.0 | 98.0 | 96.1 | 100.0 | 98.0 | 0.0 | 0.0 |
| `ORGANIZATION` | 135 | 202 | 65.3 | 97.8 | 78.3 | 65.8 | 98.5 | 78.9 | keep | keep |
| `VEHICLE_PLATE` | 53 | 50 | 100.0 | 94.3 | 97.1 | 100.0 | 94.3 | 97.1 | 2.6 | 0.0 |
| **all (micro)** | 2677 | 3557 | 56.7 | 75.3 | 64.7 | 77.9 | 89.6 | 83.3 | 7.8 | 24.0 |
