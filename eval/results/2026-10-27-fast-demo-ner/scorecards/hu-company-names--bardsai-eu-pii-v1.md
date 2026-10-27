# pii-guard evaluation

- commit: `e1268295b0d3 (dirty)`, pii-guard 0.1.0
- detectors: `rules`, `ner`
- fixtures: `eval/fixtures/hu-company-names.jsonl` sha256 `d4565df38ae2803a`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `hu` | 44 | 93 | 125 | 68.8 | 92.5 | 78.9 | 74.4 | 100.0 | 85.3 | 86.5 | 0.0 | 2.5 | 1.6 | 100.0 | 100.0 | 21.84 | 30.32 |
| **overall** | 44 | 93 | 125 | 68.8 | 92.5 | 78.9 | 74.4 | 100.0 | 85.3 | 86.5 | 0.0 | 2.5 | 1.6 | 100.0 | 100.0 | 21.84 | 30.32 |

## Per entity type: `hu`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 60 | 60 | 95.0 | 95.0 | 95.0 | 100.0 | 100.0 | 100.0 | 0.0 | 2.7 |
| `ADDRESS` | 1 | 2 | 50.0 | 100.0 | 66.7 | 50.0 | 100.0 | 66.7 | 0.0 | 0.0 |
| `EMAIL` | 1 | 1 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `PHONE` | 1 | 1 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `ORGANIZATION` | 30 | 61 | 42.6 | 86.7 | 57.1 | 49.2 | 100.0 | 65.9 | keep | keep |
| **all (micro)** | 93 | 125 | 68.8 | 92.5 | 78.9 | 74.4 | 100.0 | 85.3 | 0.0 | 2.5 |
