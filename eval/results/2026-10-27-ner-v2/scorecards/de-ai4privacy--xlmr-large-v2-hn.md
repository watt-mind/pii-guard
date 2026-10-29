# pii-guard evaluation

- commit: `b6e7bac54675 (dirty)`, pii-guard 0.1.0
- detectors: `rules`, `ner`
- fixtures: `eval/fixtures/public/de-ai4privacy.jsonl` sha256 `d0005390afa5e1a6`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `de` | 200 | 628 | 662 | 95.5 | 95.1 | 95.3 | 98.9 | 98.6 | 98.7 | 74.0 | 0.5 | 0.2 | 0.0 | 100.0 | 99.0 | 34.92 | 61.13 |
| **overall** | 200 | 628 | 662 | 95.5 | 95.1 | 95.3 | 98.9 | 98.6 | 98.7 | 74.0 | 0.5 | 0.2 | 0.0 | 100.0 | 99.0 | 34.92 | 61.13 |

## Per entity type: `de`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 182 | 181 | 97.8 | 97.3 | 97.5 | 100.0 | 99.5 | 99.7 | 0.5 | 0.0 |
| `ADDRESS` | 84 | 81 | 90.1 | 86.9 | 88.5 | 100.0 | 97.6 | 98.8 | 2.4 | 1.2 |
| `EMAIL` | 99 | 99 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `PHONE` | 64 | 67 | 89.6 | 93.8 | 91.6 | 95.5 | 100.0 | 97.7 | 0.0 | 0.0 |
| `NATIONAL_ID_HU_TAX` | 0 | 1 | 0.0 | - | 0.0 | 0.0 | - | 0.0 | keep | keep |
| `NATIONAL_ID_HU_TAJ` | 0 | 1 | 0.0 | - | 0.0 | 0.0 | - | 0.0 | keep | keep |
| `ID_DOCUMENT` | 156 | 150 | 96.7 | 92.9 | 94.8 | 100.0 | 96.2 | 98.0 | 0.0 | 0.0 |
| `BANK_ACCOUNT` | 43 | 45 | 95.6 | 100.0 | 97.7 | 95.6 | 100.0 | 97.7 | 0.0 | 0.0 |
| **all (micro)** | 628 | 625 | 95.5 | 95.1 | 95.3 | 98.9 | 98.6 | 98.7 | 0.5 | 0.2 |
