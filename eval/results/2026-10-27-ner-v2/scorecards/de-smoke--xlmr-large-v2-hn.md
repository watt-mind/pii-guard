# pii-guard evaluation

- commit: `910a6a27f002 (dirty)`, pii-guard 0.1.0
- detectors: `rules`, `ner`
- fixtures: `eval/fixtures/de-smoke.jsonl` sha256 `b623ca3b33af7ef7`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `de` | 10 | 40 | 40 | 85.0 | 85.0 | 85.0 | 97.5 | 95.0 | 96.2 | 93.3 | 0.0 | 0.0 | 0.0 | 100.0 | 97.3 | 23.35 | 34.79 |
| **overall** | 10 | 40 | 40 | 85.0 | 85.0 | 85.0 | 97.5 | 95.0 | 96.2 | 93.3 | 0.0 | 0.0 | 0.0 | 100.0 | 97.3 | 23.35 | 34.79 |

## Per entity type: `de`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 13 | 14 | 85.7 | 92.3 | 88.9 | 92.9 | 100.0 | 96.3 | 0.0 | 0.0 |
| `ADDRESS` | 5 | 6 | 66.7 | 80.0 | 72.7 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `EMAIL` | 3 | 3 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `PHONE` | 5 | 5 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `DATE_OF_BIRTH` | 3 | 3 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `ID_DOCUMENT` | 6 | 6 | 83.3 | 83.3 | 83.3 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `BANK_ACCOUNT` | 2 | 2 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `ORGANIZATION` | 3 | 1 | 0.0 | 0.0 | 0.0 | 100.0 | 33.3 | 50.0 | keep | keep |
| **all (micro)** | 40 | 40 | 85.0 | 85.0 | 85.0 | 97.5 | 95.0 | 96.2 | 0.0 | 0.0 |
