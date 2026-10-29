# pii-guard evaluation

- commit: `b6e7bac54675 (dirty)`, pii-guard 0.1.0
- detectors: `rules`, `ner`
- fixtures: `eval/fixtures/public/de-ai4privacy.jsonl` sha256 `d0005390afa5e1a6`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `de` | 200 | 628 | 688 | 95.4 | 95.2 | 95.3 | 98.9 | 98.9 | 98.9 | 74.2 | 0.5 | 0.0 | 0.3 | 100.0 | 99.0 | 28.52 | 43.72 |
| **overall** | 200 | 628 | 688 | 95.4 | 95.2 | 95.3 | 98.9 | 98.9 | 98.9 | 74.2 | 0.5 | 0.0 | 0.3 | 100.0 | 99.0 | 28.52 | 43.72 |

## Per entity type: `de`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 182 | 181 | 97.2 | 96.7 | 97.0 | 100.0 | 99.5 | 99.7 | 0.5 | 0.0 |
| `ADDRESS` | 84 | 83 | 88.0 | 86.9 | 87.4 | 97.6 | 97.6 | 97.6 | 2.4 | 0.0 |
| `EMAIL` | 99 | 99 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `PHONE` | 64 | 67 | 89.6 | 93.8 | 91.6 | 95.5 | 100.0 | 97.7 | 0.0 | 0.0 |
| `NATIONAL_ID_HU_TAX` | 0 | 1 | 0.0 | - | 0.0 | 0.0 | - | 0.0 | keep | keep |
| `NATIONAL_ID_HU_TAJ` | 0 | 1 | 0.0 | - | 0.0 | 0.0 | - | 0.0 | keep | keep |
| `ID_DOCUMENT` | 156 | 152 | 96.7 | 94.2 | 95.5 | 100.0 | 97.4 | 98.7 | 0.0 | 0.0 |
| `BANK_ACCOUNT` | 43 | 43 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| **all (micro)** | 628 | 627 | 95.4 | 95.2 | 95.3 | 98.9 | 98.9 | 98.9 | 0.5 | 0.0 |
