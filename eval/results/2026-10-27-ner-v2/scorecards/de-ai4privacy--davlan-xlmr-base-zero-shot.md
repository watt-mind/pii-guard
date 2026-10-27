# pii-guard evaluation

- commit: `b6e7bac54675 (dirty)`, pii-guard 0.1.0
- detectors: `rules`, `ner`
- fixtures: `eval/fixtures/public/de-ai4privacy.jsonl` sha256 `d0005390afa5e1a6`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `de` | 200 | 628 | 565 | 71.3 | 64.2 | 67.6 | 86.9 | 74.8 | 80.4 | 67.9 | 24.5 | 4.1 | 10.0 | 100.0 | 72.0 | 21.93 | 34.58 |
| **overall** | 200 | 628 | 565 | 71.3 | 64.2 | 67.6 | 86.9 | 74.8 | 80.4 | 67.9 | 24.5 | 4.1 | 10.0 | 100.0 | 72.0 | 21.93 | 34.58 |

## Per entity type: `de`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 182 | 178 | 83.7 | 81.9 | 82.8 | 98.9 | 95.1 | 96.9 | 4.4 | 2.7 |
| `ADDRESS` | 84 | 128 | 14.1 | 21.4 | 17.0 | 57.0 | 65.5 | 61.0 | 34.5 | 19.0 |
| `EMAIL` | 99 | 99 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `PHONE` | 64 | 54 | 90.7 | 76.6 | 83.1 | 94.4 | 79.7 | 86.4 | 20.3 | 0.0 |
| `ID_DOCUMENT` | 156 | 69 | 94.2 | 41.7 | 57.8 | 100.0 | 44.2 | 61.3 | 53.8 | 3.2 |
| `BANK_ACCOUNT` | 43 | 23 | 100.0 | 53.5 | 69.7 | 100.0 | 53.5 | 69.7 | 46.5 | 0.0 |
| `ORGANIZATION` | 0 | 14 | 0.0 | - | 0.0 | 0.0 | - | 0.0 | keep | keep |
| **all (micro)** | 628 | 565 | 71.3 | 64.2 | 67.6 | 86.9 | 74.8 | 80.4 | 24.5 | 4.1 |
