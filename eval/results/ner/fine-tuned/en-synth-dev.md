# pii-guard evaluation

- commit: `0ba3c1a50e8c (dirty)`, pii-guard 0.1.0
- detectors: `rules`, `ner`
- fixtures: `eval/generated/ner-s7/en-synth-dev.jsonl` sha256 `9f676d54f09da017`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `en` | 24 | 275 | 274 | 99.3 | 98.9 | 99.1 | 99.6 | 99.3 | 99.5 | 88.9 | 0.5 | 2.7 | 0.0 | 100.0 | 27.11 | 100.53 |
| **overall** | 24 | 275 | 274 | 99.3 | 98.9 | 99.1 | 99.6 | 99.3 | 99.5 | 88.9 | 0.5 | 2.7 | 0.0 | 100.0 | 27.11 | 100.53 |

## Per entity type: `en`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 141 | 141 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `ADDRESS` | 43 | 43 | 97.7 | 97.7 | 97.7 | 100.0 | 100.0 | 100.0 | 0.0 | 13.2 |
| `EMAIL` | 13 | 13 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `PHONE` | 18 | 18 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `DATE_OF_BIRTH` | 13 | 13 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `NATIONAL_ID_HU_TAJ` | 0 | 1 | 0.0 | - | 0.0 | 0.0 | - | 0.0 | keep | keep |
| `ID_DOCUMENT` | 10 | 9 | 100.0 | 90.0 | 94.7 | 100.0 | 90.0 | 94.7 | 0.0 | 0.0 |
| `BANK_ACCOUNT` | 16 | 16 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `ORGANIZATION` | 12 | 12 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | keep | keep |
| `VEHICLE_PLATE` | 9 | 8 | 100.0 | 88.9 | 94.1 | 100.0 | 88.9 | 94.1 | 11.1 | 0.0 |
| **all (micro)** | 275 | 274 | 99.3 | 98.9 | 99.1 | 99.6 | 99.3 | 99.5 | 0.5 | 2.7 |
