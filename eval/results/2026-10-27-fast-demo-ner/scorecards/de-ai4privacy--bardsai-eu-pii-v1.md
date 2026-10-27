# pii-guard evaluation

- commit: `e1268295b0d3 (dirty)`, pii-guard 0.1.0
- detectors: `rules`, `ner`
- fixtures: `eval/fixtures/public/de-ai4privacy.jsonl` sha256 `d0005390afa5e1a6`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `de` | 200 | 628 | 697 | 74.5 | 77.4 | 75.9 | 86.7 | 90.3 | 88.4 | 75.9 | 7.8 | 1.4 | 9.3 | 100.0 | 90.9 | 34.70 | 92.59 |
| **overall** | 200 | 628 | 697 | 74.5 | 77.4 | 75.9 | 86.7 | 90.3 | 88.4 | 75.9 | 7.8 | 1.4 | 9.3 | 100.0 | 90.9 | 34.70 | 92.59 |

## Per entity type: `de`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 182 | 187 | 78.6 | 80.8 | 79.7 | 97.3 | 96.7 | 97.0 | 2.7 | 2.7 |
| `ADDRESS` | 84 | 113 | 31.9 | 42.9 | 36.5 | 54.0 | 82.1 | 65.1 | 14.3 | 2.4 |
| `EMAIL` | 99 | 99 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `PHONE` | 64 | 66 | 84.8 | 87.5 | 86.2 | 93.9 | 96.9 | 95.4 | 0.0 | 0.0 |
| `ID_DOCUMENT` | 156 | 135 | 83.7 | 72.4 | 77.7 | 93.3 | 80.8 | 86.6 | 16.0 | 1.3 |
| `BANK_ACCOUNT` | 43 | 37 | 94.6 | 81.4 | 87.5 | 94.6 | 81.4 | 87.5 | 16.3 | 0.0 |
| `ORGANIZATION` | 0 | 15 | 0.0 | - | 0.0 | 0.0 | - | 0.0 | keep | keep |
| **all (micro)** | 628 | 652 | 74.5 | 77.4 | 75.9 | 86.7 | 90.3 | 88.4 | 7.8 | 1.4 |
