# pii-guard evaluation

- commit: `910a6a27f002 (dirty)`, pii-guard 0.1.0
- detectors: `rules`, `ner`
- fixtures: `eval/fixtures/hu-company-names.jsonl` sha256 `d4565df38ae2803a`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `hu` | 44 | 93 | 130 | 68.5 | 95.7 | 79.8 | 71.5 | 100.0 | 83.4 | 92.2 | 0.0 | 2.5 | 7.4 | 100.0 | 100.0 | 15.89 | 19.65 |
| **overall** | 44 | 93 | 130 | 68.5 | 95.7 | 79.8 | 71.5 | 100.0 | 83.4 | 92.2 | 0.0 | 2.5 | 7.4 | 100.0 | 100.0 | 15.89 | 19.65 |

## Per entity type: `hu`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 60 | 65 | 89.2 | 96.7 | 92.8 | 92.3 | 100.0 | 96.0 | 0.0 | 2.7 |
| `ADDRESS` | 1 | 1 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `EMAIL` | 1 | 1 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `PHONE` | 1 | 1 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `ORGANIZATION` | 30 | 62 | 45.2 | 93.3 | 60.9 | 48.4 | 100.0 | 65.2 | keep | keep |
| **all (micro)** | 93 | 130 | 68.5 | 95.7 | 79.8 | 71.5 | 100.0 | 83.4 | 0.0 | 2.5 |
