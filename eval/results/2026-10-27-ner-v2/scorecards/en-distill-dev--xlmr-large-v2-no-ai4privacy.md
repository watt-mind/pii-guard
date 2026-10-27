# pii-guard evaluation

- commit: `910a6a27f002 (dirty)`, pii-guard 0.1.0
- detectors: `rules`, `ner`
- fixtures: `eval/generated/distill-s11/labelled/en-distill-dev.jsonl` sha256 `b13f9983ca99ade6`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `en` | 373 | 2677 | 2678 | 99.2 | 99.3 | 99.2 | 99.4 | 99.4 | 99.4 | 99.1 | 0.4 | 1.4 | 0.4 | 99.7 | 99.6 | 74.65 | 270.66 |
| **overall** | 373 | 2677 | 2678 | 99.2 | 99.3 | 99.2 | 99.4 | 99.4 | 99.4 | 99.1 | 0.4 | 1.4 | 0.4 | 99.7 | 99.6 | 74.65 | 270.66 |

## Per entity type: `en`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 1295 | 1291 | 99.7 | 99.4 | 99.5 | 99.8 | 99.5 | 99.7 | 0.8 | 0.1 |
| `ADDRESS` | 361 | 370 | 97.6 | 100.0 | 98.8 | 97.6 | 100.0 | 98.8 | 0.0 | 7.6 |
| `EMAIL` | 283 | 283 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `PHONE` | 297 | 297 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `DATE_OF_BIRTH` | 108 | 108 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `ID_DOCUMENT` | 47 | 48 | 93.8 | 95.7 | 94.7 | 97.9 | 100.0 | 98.9 | 0.0 | 0.0 |
| `BANK_ACCOUNT` | 98 | 98 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `ORGANIZATION` | 135 | 133 | 96.2 | 94.8 | 95.5 | 97.7 | 96.3 | 97.0 | keep | keep |
| `VEHICLE_PLATE` | 53 | 50 | 100.0 | 94.3 | 97.1 | 100.0 | 94.3 | 97.1 | 2.6 | 2.6 |
| **all (micro)** | 2677 | 2678 | 99.2 | 99.3 | 99.2 | 99.4 | 99.4 | 99.4 | 0.4 | 1.4 |
