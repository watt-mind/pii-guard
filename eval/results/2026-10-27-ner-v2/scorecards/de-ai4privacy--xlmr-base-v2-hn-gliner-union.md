# pii-guard evaluation

- commit: `b6e7bac54675 (dirty)`, pii-guard 0.1.0
- detectors: `rules`, `ner`, `ner_gliner`
- fixtures: `eval/fixtures/public/de-ai4privacy.jsonl` sha256 `d0005390afa5e1a6`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `de` | 200 | 628 | 796 | 72.4 | 82.0 | 76.9 | 86.8 | 99.0 | 92.5 | 82.8 | 0.3 | 0.0 | 5.9 | 100.0 | 99.5 | 129.22 | 229.44 |
| **overall** | 200 | 628 | 796 | 72.4 | 82.0 | 76.9 | 86.8 | 99.0 | 92.5 | 82.8 | 0.3 | 0.0 | 5.9 | 100.0 | 99.5 | 129.22 | 229.44 |

## Per entity type: `de`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 182 | 199 | 53.3 | 58.2 | 55.6 | 90.5 | 99.5 | 94.7 | 0.5 | 0.0 |
| `ADDRESS` | 84 | 79 | 73.4 | 69.0 | 71.2 | 97.5 | 96.4 | 96.9 | 1.2 | 0.0 |
| `EMAIL` | 99 | 106 | 93.4 | 100.0 | 96.6 | 93.4 | 100.0 | 96.6 | 0.0 | 0.0 |
| `PHONE` | 64 | 71 | 84.5 | 93.8 | 88.9 | 90.1 | 100.0 | 94.8 | 0.0 | 0.0 |
| `ID_DOCUMENT` | 156 | 163 | 91.4 | 95.5 | 93.4 | 94.5 | 98.7 | 96.6 | 0.0 | 0.0 |
| `BANK_ACCOUNT` | 43 | 43 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `ORGANIZATION` | 0 | 50 | 0.0 | - | 0.0 | 0.0 | - | 0.0 | keep | keep |
| **all (micro)** | 628 | 711 | 72.4 | 82.0 | 76.9 | 86.8 | 99.0 | 92.5 | 0.3 | 0.0 |
