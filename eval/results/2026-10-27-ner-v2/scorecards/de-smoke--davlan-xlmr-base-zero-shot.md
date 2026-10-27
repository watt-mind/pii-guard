# pii-guard evaluation

- commit: `910a6a27f002 (dirty)`, pii-guard 0.1.0
- detectors: `rules`, `ner`
- fixtures: `eval/fixtures/de-smoke.jsonl` sha256 `b623ca3b33af7ef7`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `de` | 10 | 40 | 38 | 81.6 | 77.5 | 79.5 | 100.0 | 92.5 | 96.1 | 87.5 | 8.1 | 5.4 | 0.0 | 100.0 | 89.2 | 15.59 | 21.25 |
| **overall** | 10 | 40 | 38 | 81.6 | 77.5 | 79.5 | 100.0 | 92.5 | 96.1 | 87.5 | 8.1 | 5.4 | 0.0 | 100.0 | 89.2 | 15.59 | 21.25 |

## Per entity type: `de`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 13 | 13 | 76.9 | 76.9 | 76.9 | 100.0 | 100.0 | 100.0 | 0.0 | 7.7 |
| `ADDRESS` | 5 | 6 | 33.3 | 40.0 | 36.4 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `EMAIL` | 3 | 3 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 33.3 |
| `PHONE` | 5 | 5 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `DATE_OF_BIRTH` | 3 | 0 | - | 0.0 | 0.0 | - | 0.0 | 0.0 | 100.0 | 0.0 |
| `ID_DOCUMENT` | 6 | 6 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `BANK_ACCOUNT` | 2 | 2 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `ORGANIZATION` | 3 | 3 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | keep | keep |
| **all (micro)** | 40 | 38 | 81.6 | 77.5 | 79.5 | 100.0 | 92.5 | 96.1 | 8.1 | 5.4 |
