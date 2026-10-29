# pii-guard evaluation

- commit: `b6e7bac54675 (dirty)`, pii-guard 0.1.0
- detectors: `rules`, `ner_gliner`
- fixtures: `eval/fixtures/public/de-ai4privacy.jsonl` sha256 `d0005390afa5e1a6`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `de` | 200 | 628 | 668 | 59.4 | 56.2 | 57.8 | 79.5 | 74.5 | 76.9 | 53.1 | 18.8 | 3.0 | 5.2 | 100.0 | 79.8 | 91.69 | 178.61 |
| **overall** | 200 | 628 | 668 | 59.4 | 56.2 | 57.8 | 79.5 | 74.5 | 76.9 | 53.1 | 18.8 | 3.0 | 5.2 | 100.0 | 79.8 | 91.69 | 178.61 |

## Per entity type: `de`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 182 | 192 | 47.4 | 50.0 | 48.7 | 90.1 | 94.5 | 92.3 | 5.5 | 3.8 |
| `ADDRESS` | 84 | 58 | 37.9 | 26.2 | 31.0 | 98.3 | 64.3 | 77.7 | 29.8 | 13.1 |
| `EMAIL` | 99 | 108 | 91.7 | 100.0 | 95.7 | 91.7 | 100.0 | 95.7 | 0.0 | 0.0 |
| `PHONE` | 64 | 72 | 77.8 | 87.5 | 82.4 | 80.6 | 90.6 | 85.3 | 7.8 | 0.0 |
| `NATIONAL_ID_HU_TAX` | 0 | 21 | 0.0 | - | 0.0 | 0.0 | - | 0.0 | keep | keep |
| `NATIONAL_ID_HU_TAJ` | 0 | 3 | 0.0 | - | 0.0 | 0.0 | - | 0.0 | keep | keep |
| `ID_DOCUMENT` | 156 | 63 | 96.8 | 39.1 | 55.7 | 96.8 | 39.1 | 55.7 | 38.5 | 0.6 |
| `BANK_ACCOUNT` | 43 | 24 | 100.0 | 55.8 | 71.6 | 100.0 | 55.8 | 71.6 | 41.9 | 0.0 |
| `ORGANIZATION` | 0 | 53 | 0.0 | - | 0.0 | 0.0 | - | 0.0 | keep | keep |
| **all (micro)** | 628 | 594 | 59.4 | 56.2 | 57.8 | 79.5 | 74.5 | 76.9 | 18.8 | 3.0 |
