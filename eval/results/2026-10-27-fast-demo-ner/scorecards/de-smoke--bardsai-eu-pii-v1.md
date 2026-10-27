# pii-guard evaluation

- commit: `e1268295b0d3 (dirty)`, pii-guard 0.1.0
- detectors: `rules`, `ner`
- fixtures: `eval/fixtures/de-smoke.jsonl` sha256 `b623ca3b33af7ef7`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `de` | 10 | 40 | 42 | 76.2 | 80.0 | 78.0 | 97.6 | 100.0 | 98.8 | 99.0 | 0.0 | 8.1 | 2.6 | 100.0 | 97.3 | 26.91 | 34.22 |
| **overall** | 10 | 40 | 42 | 76.2 | 80.0 | 78.0 | 97.6 | 100.0 | 98.8 | 99.0 | 0.0 | 8.1 | 2.6 | 100.0 | 97.3 | 26.91 | 34.22 |

## Per entity type: `de`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 13 | 13 | 69.2 | 69.2 | 69.2 | 100.0 | 100.0 | 100.0 | 0.0 | 15.4 |
| `ADDRESS` | 5 | 6 | 33.3 | 40.0 | 36.4 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `EMAIL` | 3 | 3 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 33.3 |
| `PHONE` | 5 | 5 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `DATE_OF_BIRTH` | 3 | 3 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `ID_DOCUMENT` | 6 | 7 | 71.4 | 83.3 | 76.9 | 85.7 | 100.0 | 92.3 | 0.0 | 0.0 |
| `BANK_ACCOUNT` | 2 | 2 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `ORGANIZATION` | 3 | 3 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | keep | keep |
| **all (micro)** | 40 | 42 | 76.2 | 80.0 | 78.0 | 97.6 | 100.0 | 98.8 | 0.0 | 8.1 |
