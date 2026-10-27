# pii-guard evaluation

- commit: `4f84c6adc9ba (dirty)`, pii-guard 0.1.0
- detectors: `rules`, `ner`, `llm`
- fixtures: `eval/fixtures/public/de-ai4privacy.jsonl` sha256 `d0005390afa5e1a6`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `de` | 200 | 628 | 668 | 77.7 | 82.6 | 80.1 | 85.3 | 93.5 | 89.2 | 63.3 | 4.8 | 0.0 | 11.5 | 100.0 | 94.4 | 2011.50 | 4325.59 |
| **overall** | 200 | 628 | 668 | 77.7 | 82.6 | 80.1 | 85.3 | 93.5 | 89.2 | 63.3 | 4.8 | 0.0 | 11.5 | 100.0 | 94.4 | 2011.50 | 4325.59 |

## Per entity type: `de`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 182 | 185 | 87.6 | 89.0 | 88.3 | 97.8 | 98.9 | 98.4 | 1.1 | 0.0 |
| `ADDRESS` | 84 | 57 | 49.1 | 33.3 | 39.7 | 98.2 | 89.3 | 93.6 | 10.7 | 0.0 |
| `EMAIL` | 99 | 100 | 99.0 | 100.0 | 99.5 | 99.0 | 100.0 | 99.5 | 0.0 | 0.0 |
| `PHONE` | 64 | 70 | 90.0 | 98.4 | 94.0 | 90.0 | 98.4 | 94.0 | 0.0 | 0.0 |
| `DATE_OF_BIRTH` | 0 | 71 | 0.0 | - | 0.0 | 0.0 | - | 0.0 | keep | keep |
| `ID_DOCUMENT` | 156 | 134 | 95.5 | 82.1 | 88.3 | 98.5 | 84.0 | 90.7 | 10.3 | 0.0 |
| `BANK_ACCOUNT` | 43 | 40 | 97.5 | 90.7 | 94.0 | 97.5 | 90.7 | 94.0 | 7.0 | 0.0 |
| `ORGANIZATION` | 0 | 9 | 0.0 | - | 0.0 | 0.0 | - | 0.0 | keep | keep |
| `VEHICLE_PLATE` | 0 | 2 | 0.0 | - | 0.0 | 0.0 | - | 0.0 | keep | keep |
| **all (micro)** | 628 | 668 | 77.7 | 82.6 | 80.1 | 85.3 | 93.5 | 89.2 | 4.8 | 0.0 |
