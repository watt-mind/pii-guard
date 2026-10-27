# pii-guard evaluation

- commit: `e394a0636ca0 (dirty)`, pii-guard 0.1.0
- detectors: `rules`, `ner`, `llm`
- fixtures: `eval/fixtures/public/de-ai4privacy.jsonl` sha256 `d0005390afa5e1a6`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `de` | 200 | 628 | 673 | 77.3 | 82.8 | 79.9 | 84.8 | 93.5 | 88.9 | 63.1 | 4.3 | 0.0 | 11.5 | 100.0 | 94.9 | 1880.92 | 3775.63 |
| **overall** | 200 | 628 | 673 | 77.3 | 82.8 | 79.9 | 84.8 | 93.5 | 88.9 | 63.1 | 4.3 | 0.0 | 11.5 | 100.0 | 94.9 | 1880.92 | 3775.63 |

## Per entity type: `de`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 182 | 185 | 87.6 | 89.0 | 88.3 | 97.8 | 98.9 | 98.4 | 1.1 | 0.0 |
| `ADDRESS` | 84 | 54 | 48.1 | 31.0 | 37.7 | 98.1 | 85.7 | 91.5 | 13.1 | 0.0 |
| `EMAIL` | 99 | 100 | 99.0 | 100.0 | 99.5 | 99.0 | 100.0 | 99.5 | 0.0 | 0.0 |
| `PHONE` | 64 | 74 | 86.5 | 100.0 | 92.8 | 86.5 | 100.0 | 92.8 | 0.0 | 0.0 |
| `DATE_OF_BIRTH` | 0 | 71 | 0.0 | - | 0.0 | 0.0 | - | 0.0 | keep | keep |
| `ID_DOCUMENT` | 156 | 138 | 94.9 | 84.0 | 89.1 | 98.6 | 85.9 | 91.8 | 7.1 | 0.0 |
| `BANK_ACCOUNT` | 43 | 38 | 100.0 | 88.4 | 93.8 | 100.0 | 88.4 | 93.8 | 7.0 | 0.0 |
| `ORGANIZATION` | 0 | 11 | 0.0 | - | 0.0 | 0.0 | - | 0.0 | keep | keep |
| `VEHICLE_PLATE` | 0 | 2 | 0.0 | - | 0.0 | 0.0 | - | 0.0 | keep | keep |
| **all (micro)** | 628 | 673 | 77.3 | 82.8 | 79.9 | 84.8 | 93.5 | 88.9 | 4.3 | 0.0 |
