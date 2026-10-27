# pii-guard evaluation

- commit: `b6e7bac54675 (dirty)`, pii-guard 0.1.0
- detectors: `rules`, `ner`
- fixtures: `eval/fixtures/public/de-ai4privacy.jsonl` sha256 `d0005390afa5e1a6`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `de` | 200 | 628 | 663 | 95.2 | 95.4 | 95.3 | 98.3 | 98.9 | 98.6 | 84.5 | 0.5 | 0.0 | 1.0 | 100.0 | 99.4 | 16.14 | 24.71 |
| **overall** | 200 | 628 | 663 | 95.2 | 95.4 | 95.3 | 98.3 | 98.9 | 98.6 | 84.5 | 0.5 | 0.0 | 1.0 | 100.0 | 99.4 | 16.14 | 24.71 |

## Per entity type: `de`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 182 | 180 | 98.3 | 97.3 | 97.8 | 100.0 | 99.5 | 99.7 | 0.5 | 0.0 |
| `ADDRESS` | 84 | 82 | 89.0 | 86.9 | 88.0 | 97.6 | 97.6 | 97.6 | 2.4 | 0.0 |
| `EMAIL` | 99 | 99 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `PHONE` | 64 | 66 | 89.4 | 92.2 | 90.8 | 95.5 | 98.4 | 96.9 | 0.0 | 0.0 |
| `NATIONAL_ID_HU_TAJ` | 0 | 1 | 0.0 | - | 0.0 | 0.0 | - | 0.0 | keep | keep |
| `ID_DOCUMENT` | 156 | 158 | 93.7 | 94.9 | 94.3 | 96.8 | 98.1 | 97.5 | 0.0 | 0.0 |
| `BANK_ACCOUNT` | 43 | 43 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| **all (micro)** | 628 | 629 | 95.2 | 95.4 | 95.3 | 98.3 | 98.9 | 98.6 | 0.5 | 0.0 |
