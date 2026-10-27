# pii-guard evaluation

- commit: `910a6a27f002 (dirty)`, pii-guard 0.1.0
- detectors: `rules`, `ner_gliner`
- fixtures: `eval/fixtures/hu-company-names.jsonl` sha256 `d4565df38ae2803a`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `hu` | 44 | 93 | 126 | 73.0 | 98.9 | 84.0 | 73.0 | 98.9 | 84.0 | 86.1 | 0.0 | 2.5 | 0.0 | 100.0 | 100.0 | 46.85 | 66.08 |
| **overall** | 44 | 93 | 126 | 73.0 | 98.9 | 84.0 | 73.0 | 98.9 | 84.0 | 86.1 | 0.0 | 2.5 | 0.0 | 100.0 | 100.0 | 46.85 | 66.08 |

## Per entity type: `hu`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 60 | 59 | 100.0 | 98.3 | 99.2 | 100.0 | 98.3 | 99.2 | 0.0 | 2.7 |
| `ADDRESS` | 1 | 2 | 50.0 | 100.0 | 66.7 | 50.0 | 100.0 | 66.7 | 0.0 | 0.0 |
| `EMAIL` | 1 | 1 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `PHONE` | 1 | 1 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `ORGANIZATION` | 30 | 63 | 47.6 | 100.0 | 64.5 | 47.6 | 100.0 | 64.5 | keep | keep |
| **all (micro)** | 93 | 126 | 73.0 | 98.9 | 84.0 | 73.0 | 98.9 | 84.0 | 0.0 | 2.5 |
