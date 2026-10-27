# pii-guard evaluation

- commit: `477196a3427c (dirty)`, pii-guard 0.1.0
- detectors: `rules`, `ner`
- fixtures: `eval/fixtures/public/de-ai4privacy.jsonl` sha256 `d0005390afa5e1a6`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `de` | 200 | 628 | 724 | 90.2 | 94.1 | 92.1 | 94.5 | 99.0 | 96.7 | 95.5 | 0.6 | 0.0 | 5.0 | 100.0 | 98.9 | 15.10 | 28.34 |
| **overall** | 200 | 628 | 724 | 90.2 | 94.1 | 92.1 | 94.5 | 99.0 | 96.7 | 95.5 | 0.6 | 0.0 | 5.0 | 100.0 | 98.9 | 15.10 | 28.34 |

## Per entity type: `de`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 182 | 183 | 95.6 | 96.2 | 95.9 | 98.9 | 99.5 | 99.2 | 0.5 | 0.0 |
| `ADDRESS` | 84 | 82 | 82.9 | 81.0 | 81.9 | 97.6 | 97.6 | 97.6 | 2.4 | 0.0 |
| `EMAIL` | 99 | 99 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `PHONE` | 64 | 67 | 89.6 | 93.8 | 91.6 | 95.5 | 100.0 | 97.7 | 0.0 | 0.0 |
| `ID_DOCUMENT` | 156 | 166 | 88.6 | 94.2 | 91.3 | 92.2 | 98.7 | 95.3 | 0.0 | 0.0 |
| `BANK_ACCOUNT` | 43 | 58 | 72.4 | 97.7 | 83.2 | 72.4 | 97.7 | 83.2 | 2.3 | 0.0 |
| **all (micro)** | 628 | 655 | 90.2 | 94.1 | 92.1 | 94.5 | 99.0 | 96.7 | 0.6 | 0.0 |
