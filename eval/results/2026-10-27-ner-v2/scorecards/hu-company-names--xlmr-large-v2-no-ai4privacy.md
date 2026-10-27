# pii-guard evaluation

- commit: `910a6a27f002 (dirty)`, pii-guard 0.1.0
- detectors: `rules`, `ner`
- fixtures: `eval/fixtures/hu-company-names.jsonl` sha256 `d4565df38ae2803a`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `hu` | 44 | 93 | 128 | 67.2 | 92.5 | 77.8 | 72.7 | 100.0 | 84.2 | 92.6 | 0.0 | 2.5 | 3.1 | 100.0 | 95.0 | 20.70 | 23.93 |
| **overall** | 44 | 93 | 128 | 67.2 | 92.5 | 77.8 | 72.7 | 100.0 | 84.2 | 92.6 | 0.0 | 2.5 | 3.1 | 100.0 | 95.0 | 20.70 | 23.93 |

## Per entity type: `hu`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 60 | 62 | 91.9 | 95.0 | 93.4 | 96.8 | 100.0 | 98.4 | 0.0 | 2.7 |
| `ADDRESS` | 1 | 1 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `EMAIL` | 1 | 1 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `PHONE` | 1 | 1 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `ORGANIZATION` | 30 | 63 | 41.3 | 86.7 | 55.9 | 47.6 | 100.0 | 64.5 | keep | keep |
| **all (micro)** | 93 | 128 | 67.2 | 92.5 | 77.8 | 72.7 | 100.0 | 84.2 | 0.0 | 2.5 |
