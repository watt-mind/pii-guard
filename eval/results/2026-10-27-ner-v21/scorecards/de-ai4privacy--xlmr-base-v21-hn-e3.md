# pii-guard evaluation

- commit: `477196a3427c (dirty)`, pii-guard 0.1.0
- detectors: `rules`, `ner`
- fixtures: `eval/fixtures/public/de-ai4privacy.jsonl` sha256 `d0005390afa5e1a6`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `de` | 200 | 628 | 669 | 94.4 | 94.4 | 94.4 | 98.2 | 98.6 | 98.4 | 98.2 | 0.8 | 0.2 | 1.0 | 100.0 | 98.9 | 13.32 | 22.59 |
| **overall** | 200 | 628 | 669 | 94.4 | 94.4 | 94.4 | 98.2 | 98.6 | 98.4 | 98.2 | 0.8 | 0.2 | 1.0 | 100.0 | 98.9 | 13.32 | 22.59 |

## Per entity type: `de`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 182 | 179 | 98.9 | 97.3 | 98.1 | 100.0 | 98.9 | 99.4 | 0.5 | 0.0 |
| `ADDRESS` | 84 | 85 | 78.8 | 79.8 | 79.3 | 91.8 | 95.2 | 93.5 | 4.8 | 1.2 |
| `EMAIL` | 99 | 99 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `PHONE` | 64 | 68 | 86.8 | 92.2 | 89.4 | 95.6 | 100.0 | 97.7 | 0.0 | 0.0 |
| `ID_DOCUMENT` | 156 | 154 | 96.1 | 94.9 | 95.5 | 99.4 | 98.1 | 98.7 | 0.0 | 0.0 |
| `BANK_ACCOUNT` | 43 | 43 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| **all (micro)** | 628 | 628 | 94.4 | 94.4 | 94.4 | 98.2 | 98.6 | 98.4 | 0.8 | 0.2 |
