# pii-guard evaluation

- commit: `477196a3427c (dirty)`, pii-guard 0.1.0
- detectors: `rules`, `ner`
- fixtures: `eval/fixtures/hu-company-names.jsonl` sha256 `d4565df38ae2803a`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `hu` | 44 | 93 | 132 | 70.5 | 100.0 | 82.7 | 70.5 | 100.0 | 82.7 | 92.1 | 0.0 | 2.5 | 1.6 | 100.0 | 100.0 | 12.54 | 24.62 |
| **overall** | 44 | 93 | 132 | 70.5 | 100.0 | 82.7 | 70.5 | 100.0 | 82.7 | 92.1 | 0.0 | 2.5 | 1.6 | 100.0 | 100.0 | 12.54 | 24.62 |

## Per entity type: `hu`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 60 | 61 | 98.4 | 100.0 | 99.2 | 98.4 | 100.0 | 99.2 | 0.0 | 2.7 |
| `ADDRESS` | 1 | 1 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `EMAIL` | 1 | 1 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `PHONE` | 1 | 1 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `ORGANIZATION` | 30 | 68 | 44.1 | 100.0 | 61.2 | 44.1 | 100.0 | 61.2 | keep | keep |
| **all (micro)** | 93 | 132 | 70.5 | 100.0 | 82.7 | 70.5 | 100.0 | 82.7 | 0.0 | 2.5 |
