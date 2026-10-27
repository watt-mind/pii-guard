# pii-guard evaluation

- commit: `b6e7bac54675 (dirty)`, pii-guard 0.1.0
- detectors: `rules`, `ner`
- fixtures: `eval/fixtures/public/de-ai4privacy.jsonl` sha256 `d0005390afa5e1a6`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `de` | 200 | 628 | 684 | 73.7 | 70.9 | 72.2 | 90.6 | 82.8 | 86.5 | 58.9 | 10.8 | 2.2 | 1.7 | 100.0 | 84.1 | 28.69 | 43.86 |
| **overall** | 200 | 628 | 684 | 73.7 | 70.9 | 72.2 | 90.6 | 82.8 | 86.5 | 58.9 | 10.8 | 2.2 | 1.7 | 100.0 | 84.1 | 28.69 | 43.86 |

## Per entity type: `de`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 182 | 210 | 71.4 | 82.4 | 76.5 | 97.1 | 98.9 | 98.0 | 1.1 | 2.7 |
| `ADDRESS` | 84 | 66 | 53.0 | 41.7 | 46.7 | 93.9 | 71.4 | 81.2 | 28.6 | 2.4 |
| `EMAIL` | 99 | 99 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `PHONE` | 64 | 69 | 87.0 | 93.8 | 90.2 | 92.8 | 100.0 | 96.2 | 0.0 | 0.0 |
| `NATIONAL_ID_HU_TAX` | 0 | 20 | 0.0 | - | 0.0 | 0.0 | - | 0.0 | keep | keep |
| `NATIONAL_ID_HU_TAJ` | 0 | 13 | 0.0 | - | 0.0 | 0.0 | - | 0.0 | keep | keep |
| `ID_DOCUMENT` | 156 | 85 | 77.6 | 42.3 | 54.8 | 96.5 | 51.9 | 67.5 | 25.6 | 4.5 |
| `BANK_ACCOUNT` | 43 | 40 | 87.5 | 81.4 | 84.3 | 90.0 | 83.7 | 86.7 | 4.7 | 0.0 |
| `ORGANIZATION` | 0 | 2 | 0.0 | - | 0.0 | 0.0 | - | 0.0 | keep | keep |
| **all (micro)** | 628 | 604 | 73.7 | 70.9 | 72.2 | 90.6 | 82.8 | 86.5 | 10.8 | 2.2 |
