# pii-guard evaluation

- commit: `910a6a27f002 (dirty)`, pii-guard 0.1.0
- detectors: `rules`, `ner`
- fixtures: `eval/fixtures/de-smoke.jsonl` sha256 `b623ca3b33af7ef7`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `de` | 10 | 40 | 43 | 76.7 | 82.5 | 79.5 | 90.7 | 97.5 | 94.0 | 95.9 | 0.0 | 8.1 | 10.0 | 100.0 | 100.0 | 15.64 | 19.76 |
| **overall** | 10 | 40 | 43 | 76.7 | 82.5 | 79.5 | 90.7 | 97.5 | 94.0 | 95.9 | 0.0 | 8.1 | 10.0 | 100.0 | 100.0 | 15.64 | 19.76 |

## Per entity type: `de`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 13 | 12 | 75.0 | 69.2 | 72.0 | 100.0 | 92.3 | 96.0 | 0.0 | 15.4 |
| `ADDRESS` | 5 | 6 | 66.7 | 80.0 | 72.7 | 83.3 | 100.0 | 90.9 | 0.0 | 0.0 |
| `EMAIL` | 3 | 3 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 33.3 |
| `PHONE` | 5 | 5 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `DATE_OF_BIRTH` | 3 | 3 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `ID_DOCUMENT` | 6 | 9 | 55.6 | 83.3 | 66.7 | 66.7 | 100.0 | 80.0 | 0.0 | 0.0 |
| `BANK_ACCOUNT` | 2 | 2 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `ORGANIZATION` | 3 | 3 | 66.7 | 66.7 | 66.7 | 100.0 | 100.0 | 100.0 | keep | keep |
| **all (micro)** | 40 | 43 | 76.7 | 82.5 | 79.5 | 90.7 | 97.5 | 94.0 | 0.0 | 8.1 |
