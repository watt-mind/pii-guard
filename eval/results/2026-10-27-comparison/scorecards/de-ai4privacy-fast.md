# pii-guard evaluation

- commit: `4f84c6adc9ba (dirty)`, pii-guard 0.1.0
- detectors: `rules`, `ner`
- fixtures: `eval/fixtures/public/de-ai4privacy.jsonl` sha256 `d0005390afa5e1a6`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `de` | 200 | 628 | 510 | 59.2 | 48.1 | 53.1 | 82.5 | 60.2 | 69.6 | 46.1 | 39.2 | 1.8 | 14.9 | 100.0 | 54.0 | 25.79 | 38.57 |
| **overall** | 200 | 628 | 510 | 59.2 | 48.1 | 53.1 | 82.5 | 60.2 | 69.6 | 46.1 | 39.2 | 1.8 | 14.9 | 100.0 | 54.0 | 25.79 | 38.57 |

## Per entity type: `de`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 182 | 225 | 61.3 | 75.8 | 67.8 | 96.0 | 98.4 | 97.2 | 1.6 | 3.8 |
| `ADDRESS` | 84 | 68 | 29.4 | 23.8 | 26.3 | 89.7 | 65.5 | 75.7 | 33.3 | 3.6 |
| `EMAIL` | 99 | 99 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `PHONE` | 64 | 38 | 92.1 | 54.7 | 68.6 | 92.1 | 54.7 | 68.6 | 45.3 | 0.0 |
| `DATE_OF_BIRTH` | 0 | 63 | 0.0 | - | 0.0 | 0.0 | - | 0.0 | keep | keep |
| `ID_DOCUMENT` | 156 | 5 | 100.0 | 3.2 | 6.2 | 100.0 | 3.2 | 6.2 | 94.9 | 0.6 |
| `BANK_ACCOUNT` | 43 | 5 | 100.0 | 11.6 | 20.8 | 100.0 | 11.6 | 20.8 | 88.4 | 0.0 |
| `ORGANIZATION` | 0 | 7 | 0.0 | - | 0.0 | 0.0 | - | 0.0 | keep | keep |
| **all (micro)** | 628 | 510 | 59.2 | 48.1 | 53.1 | 82.5 | 60.2 | 69.6 | 39.2 | 1.8 |
