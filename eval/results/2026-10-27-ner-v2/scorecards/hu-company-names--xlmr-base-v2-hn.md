# pii-guard evaluation

- commit: `910a6a27f002 (dirty)`, pii-guard 0.1.0
- detectors: `rules`, `ner`
- fixtures: `eval/fixtures/hu-company-names.jsonl` sha256 `d4565df38ae2803a`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `hu` | 44 | 93 | 125 | 63.2 | 84.9 | 72.5 | 74.4 | 96.8 | 84.1 | 92.5 | 0.0 | 2.5 | 5.7 | 100.0 | 100.0 | 27.63 | 52.34 |
| **overall** | 44 | 93 | 125 | 63.2 | 84.9 | 72.5 | 74.4 | 96.8 | 84.1 | 92.5 | 0.0 | 2.5 | 5.7 | 100.0 | 100.0 | 27.63 | 52.34 |

## Per entity type: `hu`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 60 | 67 | 86.6 | 96.7 | 91.3 | 89.6 | 100.0 | 94.5 | 0.0 | 2.7 |
| `ADDRESS` | 1 | 1 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `EMAIL` | 1 | 1 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `PHONE` | 1 | 1 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `ORGANIZATION` | 30 | 55 | 32.7 | 60.0 | 42.4 | 54.5 | 90.0 | 67.9 | keep | keep |
| **all (micro)** | 93 | 125 | 63.2 | 84.9 | 72.5 | 74.4 | 96.8 | 84.1 | 0.0 | 2.5 |
