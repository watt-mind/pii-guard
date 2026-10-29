# pii-guard evaluation

- commit: `477196a3427c (dirty)`, pii-guard 0.1.0
- detectors: `rules`, `ner`
- fixtures: `eval/fixtures/de-smoke.jsonl` sha256 `b623ca3b33af7ef7`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `de` | 10 | 40 | 41 | 87.8 | 90.0 | 88.9 | 95.1 | 97.5 | 96.3 | 93.9 | 0.0 | 0.0 | 2.6 | 100.0 | 97.3 | 12.59 | 17.67 |
| **overall** | 10 | 40 | 41 | 87.8 | 90.0 | 88.9 | 95.1 | 97.5 | 96.3 | 93.9 | 0.0 | 0.0 | 2.6 | 100.0 | 97.3 | 12.59 | 17.67 |

## Per entity type: `de`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 13 | 13 | 84.6 | 84.6 | 84.6 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `ADDRESS` | 5 | 6 | 83.3 | 100.0 | 90.9 | 83.3 | 100.0 | 90.9 | 0.0 | 0.0 |
| `EMAIL` | 3 | 3 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `PHONE` | 5 | 5 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `DATE_OF_BIRTH` | 3 | 3 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `ID_DOCUMENT` | 6 | 6 | 83.3 | 83.3 | 83.3 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `BANK_ACCOUNT` | 2 | 3 | 66.7 | 100.0 | 80.0 | 66.7 | 100.0 | 80.0 | 0.0 | 0.0 |
| `ORGANIZATION` | 3 | 2 | 100.0 | 66.7 | 80.0 | 100.0 | 66.7 | 80.0 | keep | keep |
| **all (micro)** | 40 | 41 | 87.8 | 90.0 | 88.9 | 95.1 | 97.5 | 96.3 | 0.0 | 0.0 |
