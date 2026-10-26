# pii-guard evaluation

- commit: `0ba3c1a50e8c (dirty)`, pii-guard 0.1.0
- detectors: `rules`, `ner`
- fixtures: `eval/fixtures/en-synth-sample.jsonl` sha256 `2c7ab3d12880065d`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `en` | 10 | 120 | 150 | 62.7 | 78.3 | 69.6 | 98.7 | 95.0 | 96.8 | 88.7 | 7.5 | 0.0 | 1.4 | 100.0 | 133.24 | 513.63 |
| **overall** | 10 | 120 | 150 | 62.7 | 78.3 | 69.6 | 98.7 | 95.0 | 96.8 | 88.7 | 7.5 | 0.0 | 1.4 | 100.0 | 133.24 | 513.63 |

## Per entity type: `en`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 59 | 59 | 96.6 | 96.6 | 96.6 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `ADDRESS` | 17 | 53 | 0.0 | 0.0 | 0.0 | 96.2 | 100.0 | 98.1 | 0.0 | 0.0 |
| `EMAIL` | 7 | 7 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `PHONE` | 8 | 8 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `DATE_OF_BIRTH` | 6 | 0 | - | 0.0 | 0.0 | - | 0.0 | 0.0 | 100.0 | 0.0 |
| `ID_DOCUMENT` | 3 | 3 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `BANK_ACCOUNT` | 7 | 7 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `ORGANIZATION` | 10 | 10 | 90.0 | 90.0 | 90.0 | 100.0 | 100.0 | 100.0 | keep | keep |
| `VEHICLE_PLATE` | 3 | 3 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| **all (micro)** | 120 | 150 | 62.7 | 78.3 | 69.6 | 98.7 | 95.0 | 96.8 | 7.5 | 0.0 |
