# pii-guard evaluation

- commit: `b6e7bac54675 (dirty)`, pii-guard 0.1.0
- detectors: `rules`, `ner`
- fixtures: `eval/fixtures/public/de-ai4privacy.jsonl` sha256 `d0005390afa5e1a6`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `de` | 200 | 628 | 607 | 72.2 | 62.6 | 67.1 | 95.2 | 76.0 | 84.5 | 70.3 | 23.4 | 2.4 | 2.1 | 100.0 | 69.9 | 61.87 | 114.74 |
| **overall** | 200 | 628 | 607 | 72.2 | 62.6 | 67.1 | 95.2 | 76.0 | 84.5 | 70.3 | 23.4 | 2.4 | 2.1 | 100.0 | 69.9 | 61.87 | 114.74 |

## Per entity type: `de`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 182 | 223 | 61.4 | 75.3 | 67.7 | 96.4 | 97.8 | 97.1 | 2.2 | 3.3 |
| `ADDRESS` | 84 | 68 | 29.4 | 23.8 | 26.3 | 89.7 | 67.9 | 77.3 | 31.0 | 4.8 |
| `EMAIL` | 99 | 99 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `PHONE` | 64 | 54 | 90.7 | 76.6 | 83.1 | 94.4 | 79.7 | 86.4 | 20.3 | 0.0 |
| `ID_DOCUMENT` | 156 | 69 | 94.2 | 41.7 | 57.8 | 100.0 | 44.2 | 61.3 | 53.8 | 3.2 |
| `BANK_ACCOUNT` | 43 | 23 | 100.0 | 53.5 | 69.7 | 100.0 | 53.5 | 69.7 | 46.5 | 0.0 |
| `ORGANIZATION` | 0 | 8 | 0.0 | - | 0.0 | 0.0 | - | 0.0 | keep | keep |
| **all (micro)** | 628 | 544 | 72.2 | 62.6 | 67.1 | 95.2 | 76.0 | 84.5 | 23.4 | 2.4 |
