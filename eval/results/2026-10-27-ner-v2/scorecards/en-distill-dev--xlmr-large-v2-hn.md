# pii-guard evaluation

- commit: `910a6a27f002 (dirty)`, pii-guard 0.1.0
- detectors: `rules`, `ner`
- fixtures: `eval/generated/distill-s11/labelled/en-distill-dev.jsonl` sha256 `b13f9983ca99ade6`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `en` | 373 | 2677 | 2686 | 98.9 | 99.3 | 99.1 | 99.4 | 99.6 | 99.5 | 99.1 | 0.4 | 1.3 | 0.2 | 100.0 | 99.5 | 75.03 | 269.34 |
| **overall** | 373 | 2677 | 2686 | 98.9 | 99.3 | 99.1 | 99.4 | 99.6 | 99.5 | 99.1 | 0.4 | 1.3 | 0.2 | 100.0 | 99.5 | 75.03 | 269.34 |

## Per entity type: `en`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 1295 | 1290 | 99.8 | 99.4 | 99.6 | 99.9 | 99.5 | 99.7 | 0.8 | 0.0 |
| `ADDRESS` | 361 | 365 | 98.6 | 99.7 | 99.2 | 99.2 | 100.0 | 99.6 | 0.0 | 7.6 |
| `EMAIL` | 283 | 283 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `PHONE` | 297 | 297 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `DATE_OF_BIRTH` | 108 | 108 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `ID_DOCUMENT` | 47 | 48 | 93.8 | 95.7 | 94.7 | 97.9 | 100.0 | 98.9 | 0.0 | 0.0 |
| `BANK_ACCOUNT` | 98 | 98 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `ORGANIZATION` | 135 | 147 | 87.8 | 95.6 | 91.5 | 93.2 | 99.3 | 96.1 | keep | keep |
| `VEHICLE_PLATE` | 53 | 50 | 100.0 | 94.3 | 97.1 | 100.0 | 94.3 | 97.1 | 2.6 | 0.0 |
| **all (micro)** | 2677 | 2686 | 98.9 | 99.3 | 99.1 | 99.4 | 99.6 | 99.5 | 0.4 | 1.3 |
