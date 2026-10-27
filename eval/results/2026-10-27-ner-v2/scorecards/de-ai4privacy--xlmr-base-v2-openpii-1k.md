# pii-guard evaluation

- commit: `b6e7bac54675 (dirty)`, pii-guard 0.1.0
- detectors: `rules`, `ner`
- fixtures: `eval/fixtures/public/de-ai4privacy.jsonl` sha256 `d0005390afa5e1a6`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `de` | 200 | 628 | 700 | 91.0 | 93.2 | 92.1 | 96.6 | 98.9 | 97.7 | 97.6 | 0.6 | 0.3 | 2.0 | 100.0 | 97.9 | 16.58 | 24.74 |
| **overall** | 200 | 628 | 700 | 91.0 | 93.2 | 92.1 | 96.6 | 98.9 | 97.7 | 97.6 | 0.6 | 0.3 | 2.0 | 100.0 | 97.9 | 16.58 | 24.74 |

## Per entity type: `de`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 182 | 183 | 95.1 | 95.6 | 95.3 | 98.9 | 98.9 | 98.9 | 1.1 | 0.0 |
| `ADDRESS` | 84 | 91 | 70.3 | 76.2 | 73.1 | 89.0 | 97.6 | 93.1 | 2.4 | 2.4 |
| `EMAIL` | 99 | 99 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `PHONE` | 64 | 67 | 88.1 | 92.2 | 90.1 | 95.5 | 100.0 | 97.7 | 0.0 | 0.0 |
| `ID_DOCUMENT` | 156 | 161 | 91.9 | 94.9 | 93.4 | 95.7 | 98.7 | 97.2 | 0.0 | 0.0 |
| `BANK_ACCOUNT` | 43 | 42 | 97.6 | 95.3 | 96.5 | 100.0 | 97.7 | 98.8 | 0.0 | 0.0 |
| **all (micro)** | 628 | 643 | 91.0 | 93.2 | 92.1 | 96.6 | 98.9 | 97.7 | 0.6 | 0.3 |
