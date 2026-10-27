# pii-guard evaluation

- commit: `910a6a27f002 (dirty)`, pii-guard 0.1.0
- detectors: `rules`, `ner`, `ner_gliner`
- fixtures: `eval/fixtures/hu-company-names.jsonl` sha256 `d4565df38ae2803a`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `hu` | 44 | 93 | 146 | 57.5 | 90.3 | 70.3 | 64.4 | 98.9 | 78.0 | 83.8 | 0.0 | 2.5 | 12.0 | 100.0 | 95.0 | 57.31 | 80.39 |
| **overall** | 44 | 93 | 146 | 57.5 | 90.3 | 70.3 | 64.4 | 98.9 | 78.0 | 83.8 | 0.0 | 2.5 | 12.0 | 100.0 | 95.0 | 57.31 | 80.39 |

## Per entity type: `hu`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 60 | 71 | 74.6 | 88.3 | 80.9 | 83.1 | 98.3 | 90.1 | 0.0 | 2.7 |
| `ADDRESS` | 1 | 1 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `EMAIL` | 1 | 1 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `PHONE` | 1 | 2 | 50.0 | 100.0 | 66.7 | 50.0 | 100.0 | 66.7 | 0.0 | 0.0 |
| `ORGANIZATION` | 30 | 71 | 39.4 | 93.3 | 55.4 | 45.1 | 100.0 | 62.1 | keep | keep |
| **all (micro)** | 93 | 146 | 57.5 | 90.3 | 70.3 | 64.4 | 98.9 | 78.0 | 0.0 | 2.5 |
