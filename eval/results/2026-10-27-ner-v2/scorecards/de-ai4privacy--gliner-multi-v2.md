# pii-guard evaluation

- commit: `b6e7bac54675 (dirty)`, pii-guard 0.1.0
- detectors: `rules`, `ner_gliner`
- fixtures: `eval/fixtures/public/de-ai4privacy.jsonl` sha256 `d0005390afa5e1a6`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `de` | 200 | 628 | 634 | 93.4 | 93.0 | 93.2 | 96.3 | 96.3 | 96.3 | 65.2 | 0.8 | 0.0 | 0.2 | 100.0 | 99.0 | 181.36 | 344.64 |
| **overall** | 200 | 628 | 634 | 93.4 | 93.0 | 93.2 | 96.3 | 96.3 | 96.3 | 65.2 | 0.8 | 0.0 | 0.2 | 100.0 | 99.0 | 181.36 | 344.64 |

## Per entity type: `de`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 182 | 179 | 97.2 | 95.6 | 96.4 | 100.0 | 98.9 | 99.4 | 1.1 | 0.0 |
| `ADDRESS` | 84 | 79 | 88.6 | 83.3 | 85.9 | 98.7 | 95.2 | 97.0 | 3.6 | 0.0 |
| `EMAIL` | 99 | 99 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `PHONE` | 64 | 68 | 88.2 | 93.8 | 90.9 | 94.1 | 100.0 | 97.0 | 0.0 | 0.0 |
| `NATIONAL_ID_HU_TAX` | 0 | 7 | 0.0 | - | 0.0 | 0.0 | - | 0.0 | keep | keep |
| `NATIONAL_ID_HU_TAJ` | 0 | 7 | 0.0 | - | 0.0 | 0.0 | - | 0.0 | keep | keep |
| `ID_DOCUMENT` | 156 | 141 | 98.6 | 89.1 | 93.6 | 99.3 | 89.7 | 94.3 | 0.0 | 0.0 |
| `BANK_ACCOUNT` | 43 | 42 | 100.0 | 97.7 | 98.8 | 100.0 | 97.7 | 98.8 | 0.0 | 0.0 |
| `ORGANIZATION` | 0 | 3 | 0.0 | - | 0.0 | 0.0 | - | 0.0 | keep | keep |
| **all (micro)** | 628 | 625 | 93.4 | 93.0 | 93.2 | 96.3 | 96.3 | 96.3 | 0.8 | 0.0 |
