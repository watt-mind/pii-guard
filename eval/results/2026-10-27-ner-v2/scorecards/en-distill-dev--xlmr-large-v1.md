# pii-guard evaluation

- commit: `910a6a27f002 (dirty)`, pii-guard 0.1.0
- detectors: `rules`, `ner`
- fixtures: `eval/generated/distill-s11/labelled/en-distill-dev.jsonl` sha256 `b13f9983ca99ade6`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `en` | 373 | 2677 | 2716 | 97.8 | 99.2 | 98.5 | 97.9 | 99.3 | 98.6 | 98.4 | 0.5 | 1.3 | 2.2 | 99.5 | 99.4 | 73.86 | 315.31 |
| **overall** | 373 | 2677 | 2716 | 97.8 | 99.2 | 98.5 | 97.9 | 99.3 | 98.6 | 98.4 | 0.5 | 1.3 | 2.2 | 99.5 | 99.4 | 73.86 | 315.31 |

## Per entity type: `en`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 1295 | 1289 | 99.9 | 99.5 | 99.7 | 99.9 | 99.5 | 99.7 | 1.0 | 0.0 |
| `ADDRESS` | 361 | 418 | 86.1 | 99.7 | 92.4 | 86.6 | 100.0 | 92.8 | 0.0 | 7.6 |
| `EMAIL` | 283 | 283 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `PHONE` | 297 | 297 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `DATE_OF_BIRTH` | 108 | 107 | 100.0 | 99.1 | 99.5 | 100.0 | 99.1 | 99.5 | 0.0 | 0.0 |
| `ID_DOCUMENT` | 47 | 46 | 100.0 | 97.9 | 98.9 | 100.0 | 97.9 | 98.9 | 2.1 | 0.0 |
| `BANK_ACCOUNT` | 98 | 98 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `ORGANIZATION` | 135 | 128 | 99.2 | 94.1 | 96.6 | 100.0 | 94.8 | 97.3 | keep | keep |
| `VEHICLE_PLATE` | 53 | 50 | 100.0 | 94.3 | 97.1 | 100.0 | 94.3 | 97.1 | 5.1 | 0.0 |
| **all (micro)** | 2677 | 2716 | 97.8 | 99.2 | 98.5 | 97.9 | 99.3 | 98.6 | 0.5 | 1.3 |
