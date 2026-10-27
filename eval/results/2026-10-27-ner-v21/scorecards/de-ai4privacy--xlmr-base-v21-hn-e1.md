# pii-guard evaluation

- commit: `477196a3427c (dirty)`, pii-guard 0.1.0
- detectors: `rules`, `ner`
- fixtures: `eval/fixtures/public/de-ai4privacy.jsonl` sha256 `d0005390afa5e1a6`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `de` | 200 | 628 | 712 | 92.6 | 93.5 | 93.0 | 97.5 | 98.7 | 98.1 | 83.7 | 0.3 | 0.3 | 0.9 | 100.0 | 98.9 | 13.31 | 22.41 |
| **overall** | 200 | 628 | 712 | 92.6 | 93.5 | 93.0 | 97.5 | 98.7 | 98.1 | 83.7 | 0.3 | 0.3 | 0.9 | 100.0 | 98.9 | 13.31 | 22.41 |

## Per entity type: `de`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 182 | 182 | 98.4 | 98.4 | 98.4 | 99.5 | 100.0 | 99.7 | 0.0 | 0.0 |
| `ADDRESS` | 84 | 88 | 71.6 | 75.0 | 73.3 | 90.9 | 97.6 | 94.1 | 2.4 | 2.4 |
| `EMAIL` | 99 | 99 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `PHONE` | 64 | 67 | 89.6 | 93.8 | 91.6 | 95.5 | 100.0 | 97.7 | 0.0 | 0.0 |
| `NATIONAL_ID_HU_TAX` | 0 | 1 | 0.0 | — | 0.0 | 0.0 | — | 0.0 | keep | keep |
| `ID_DOCUMENT` | 156 | 151 | 94.7 | 91.7 | 93.2 | 100.0 | 96.2 | 98.0 | 0.0 | 0.0 |
| `BANK_ACCOUNT` | 43 | 46 | 93.5 | 100.0 | 96.6 | 93.5 | 100.0 | 96.6 | 0.0 | 0.0 |
| **all (micro)** | 628 | 634 | 92.6 | 93.5 | 93.0 | 97.5 | 98.7 | 98.1 | 0.3 | 0.3 |
