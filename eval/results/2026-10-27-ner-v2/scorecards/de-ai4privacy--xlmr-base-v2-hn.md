# pii-guard evaluation

- commit: `b6e7bac54675 (dirty)`, pii-guard 0.1.0
- detectors: `rules`, `ner`
- fixtures: `eval/fixtures/public/de-ai4privacy.jsonl` sha256 `d0005390afa5e1a6`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `de` | 200 | 628 | 699 | 94.1 | 95.7 | 94.9 | 97.2 | 99.4 | 98.3 | 98.5 | 0.3 | 0.0 | 2.3 | 100.0 | 99.5 | 18.00 | 30.88 |
| **overall** | 200 | 628 | 699 | 94.1 | 95.7 | 94.9 | 97.2 | 99.4 | 98.3 | 98.5 | 0.3 | 0.0 | 2.3 | 100.0 | 99.5 | 18.00 | 30.88 |

## Per entity type: `de`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 182 | 180 | 98.9 | 97.8 | 98.3 | 100.0 | 99.5 | 99.7 | 0.5 | 0.0 |
| `ADDRESS` | 84 | 83 | 86.7 | 85.7 | 86.2 | 97.6 | 98.8 | 98.2 | 1.2 | 0.0 |
| `EMAIL` | 99 | 99 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `PHONE` | 64 | 67 | 89.6 | 93.8 | 91.6 | 95.5 | 100.0 | 97.7 | 0.0 | 0.0 |
| `ID_DOCUMENT` | 156 | 167 | 89.2 | 95.5 | 92.3 | 92.2 | 98.7 | 95.4 | 0.0 | 0.0 |
| `BANK_ACCOUNT` | 43 | 43 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| **all (micro)** | 628 | 639 | 94.1 | 95.7 | 94.9 | 97.2 | 99.4 | 98.3 | 0.3 | 0.0 |
