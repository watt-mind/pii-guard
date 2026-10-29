# pii-guard evaluation

- commit: `b6e7bac54675 (dirty)`, pii-guard 0.1.0
- detectors: `rules`, `ner`
- fixtures: `eval/fixtures/public/de-ai4privacy.jsonl` sha256 `d0005390afa5e1a6`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `de` | 200 | 628 | 682 | 93.4 | 93.9 | 93.7 | 98.6 | 99.0 | 98.8 | 98.5 | 0.5 | 0.2 | 0.8 | 100.0 | 98.6 | 28.29 | 43.67 |
| **overall** | 200 | 628 | 682 | 93.4 | 93.9 | 93.7 | 98.6 | 99.0 | 98.8 | 98.5 | 0.5 | 0.2 | 0.8 | 100.0 | 98.6 | 28.29 | 43.67 |

## Per entity type: `de`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 182 | 182 | 94.0 | 94.0 | 94.0 | 100.0 | 99.5 | 99.7 | 0.5 | 0.0 |
| `ADDRESS` | 84 | 86 | 81.4 | 83.3 | 82.4 | 94.2 | 97.6 | 95.9 | 2.4 | 1.2 |
| `EMAIL` | 99 | 99 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `PHONE` | 64 | 68 | 86.8 | 92.2 | 89.4 | 95.6 | 100.0 | 97.7 | 0.0 | 0.0 |
| `ID_DOCUMENT` | 156 | 155 | 96.1 | 95.5 | 95.8 | 99.4 | 98.7 | 99.0 | 0.0 | 0.0 |
| `BANK_ACCOUNT` | 43 | 42 | 100.0 | 97.7 | 98.8 | 100.0 | 97.7 | 98.8 | 0.0 | 0.0 |
| **all (micro)** | 628 | 632 | 93.4 | 93.9 | 93.7 | 98.6 | 99.0 | 98.8 | 0.5 | 0.2 |
