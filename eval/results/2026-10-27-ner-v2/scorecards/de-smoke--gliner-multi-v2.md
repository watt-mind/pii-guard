# pii-guard evaluation

- commit: `910a6a27f002 (dirty)`, pii-guard 0.1.0
- detectors: `rules`, `ner_gliner`
- fixtures: `eval/fixtures/de-smoke.jsonl` sha256 `b623ca3b33af7ef7`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `de` | 10 | 40 | 45 | 80.0 | 90.0 | 84.7 | 91.1 | 100.0 | 95.3 | 94.8 | 0.0 | 2.7 | 9.5 | 100.0 | 97.3 | 69.71 | 82.56 |
| **overall** | 10 | 40 | 45 | 80.0 | 90.0 | 84.7 | 91.1 | 100.0 | 95.3 | 94.8 | 0.0 | 2.7 | 9.5 | 100.0 | 97.3 | 69.71 | 82.56 |

## Per entity type: `de`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 13 | 13 | 76.9 | 76.9 | 76.9 | 100.0 | 100.0 | 100.0 | 0.0 | 7.7 |
| `ADDRESS` | 5 | 7 | 57.1 | 80.0 | 66.7 | 85.7 | 100.0 | 92.3 | 0.0 | 0.0 |
| `EMAIL` | 3 | 3 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `PHONE` | 5 | 5 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `DATE_OF_BIRTH` | 3 | 3 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `ID_DOCUMENT` | 6 | 8 | 75.0 | 100.0 | 85.7 | 75.0 | 100.0 | 85.7 | 0.0 | 0.0 |
| `BANK_ACCOUNT` | 2 | 3 | 66.7 | 100.0 | 80.0 | 66.7 | 100.0 | 80.0 | 0.0 | 0.0 |
| `ORGANIZATION` | 3 | 3 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | keep | keep |
| **all (micro)** | 40 | 45 | 80.0 | 90.0 | 84.7 | 91.1 | 100.0 | 95.3 | 0.0 | 2.7 |
