# pii-guard evaluation

- commit: `b6e7bac54675 (dirty)`, pii-guard 0.1.0
- detectors: `rules`, `ner`
- fixtures: `eval/fixtures/public/de-ai4privacy.jsonl` sha256 `d0005390afa5e1a6`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `de` | 200 | 628 | 640 | 73.7 | 68.3 | 70.9 | 86.1 | 78.5 | 82.1 | 55.2 | 13.5 | 1.8 | 3.3 | 100.0 | 82.6 | 16.93 | 23.98 |
| **overall** | 200 | 628 | 640 | 73.7 | 68.3 | 70.9 | 86.1 | 78.5 | 82.1 | 55.2 | 13.5 | 1.8 | 3.3 | 100.0 | 82.6 | 16.93 | 23.98 |

## Per entity type: `de`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 182 | 210 | 71.4 | 82.4 | 76.5 | 90.5 | 98.4 | 94.2 | 1.6 | 2.2 |
| `ADDRESS` | 84 | 54 | 48.1 | 31.0 | 37.7 | 88.9 | 60.7 | 72.1 | 35.7 | 4.8 |
| `EMAIL` | 99 | 99 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `PHONE` | 64 | 74 | 81.1 | 93.8 | 87.0 | 86.5 | 100.0 | 92.8 | 0.0 | 0.0 |
| `NATIONAL_ID_HU_TAX` | 0 | 15 | 0.0 | - | 0.0 | 0.0 | - | 0.0 | keep | keep |
| `NATIONAL_ID_HU_TAJ` | 0 | 12 | 0.0 | - | 0.0 | 0.0 | - | 0.0 | keep | keep |
| `ID_DOCUMENT` | 156 | 59 | 89.8 | 34.0 | 49.3 | 100.0 | 37.8 | 54.9 | 33.3 | 1.9 |
| `BANK_ACCOUNT` | 43 | 56 | 73.2 | 95.3 | 82.8 | 73.2 | 95.3 | 82.8 | 0.0 | 0.0 |
| `ORGANIZATION` | 0 | 3 | 0.0 | - | 0.0 | 0.0 | - | 0.0 | keep | keep |
| **all (micro)** | 628 | 582 | 73.7 | 68.3 | 70.9 | 86.1 | 78.5 | 82.1 | 13.5 | 1.8 |
