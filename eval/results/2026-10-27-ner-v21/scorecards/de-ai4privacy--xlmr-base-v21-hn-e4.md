# pii-guard evaluation

- commit: `477196a3427c (dirty)`, pii-guard 0.1.0
- detectors: `rules`, `ner`
- fixtures: `eval/fixtures/public/de-ai4privacy.jsonl` sha256 `d0005390afa5e1a6`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `de` | 200 | 628 | 748 | 94.8 | 95.4 | 95.1 | 98.1 | 99.0 | 98.6 | 98.4 | 0.6 | 0.0 | 1.4 | 100.0 | 99.0 | 11.54 | 17.51 |
| **overall** | 200 | 628 | 748 | 94.8 | 95.4 | 95.1 | 98.1 | 99.0 | 98.6 | 98.4 | 0.6 | 0.0 | 1.4 | 100.0 | 99.0 | 11.54 | 17.51 |

## Per entity type: `de`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 182 | 181 | 98.3 | 97.8 | 98.1 | 99.4 | 99.5 | 99.4 | 0.5 | 0.0 |
| `ADDRESS` | 84 | 85 | 84.7 | 85.7 | 85.2 | 95.3 | 97.6 | 96.4 | 2.4 | 0.0 |
| `EMAIL` | 99 | 99 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `PHONE` | 64 | 67 | 89.6 | 93.8 | 91.6 | 95.5 | 100.0 | 97.7 | 0.0 | 0.0 |
| `ID_DOCUMENT` | 156 | 158 | 94.3 | 95.5 | 94.9 | 97.5 | 98.7 | 98.1 | 0.0 | 0.0 |
| `BANK_ACCOUNT` | 43 | 42 | 97.6 | 95.3 | 96.5 | 100.0 | 97.7 | 98.8 | 2.3 | 0.0 |
| **all (micro)** | 628 | 632 | 94.8 | 95.4 | 95.1 | 98.1 | 99.0 | 98.6 | 0.6 | 0.0 |
