# pii-guard evaluation

- commit: `910a6a27f002 (dirty)`, pii-guard 0.1.0
- detectors: `rules`, `ner`
- fixtures: `eval/fixtures/hu-company-names.jsonl` sha256 `d4565df38ae2803a`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `hu` | 44 | 93 | 129 | 64.3 | 89.2 | 74.8 | 70.5 | 97.8 | 82.0 | 80.3 | 0.0 | 2.5 | 1.6 | 100.0 | 97.5 | 15.34 | 21.85 |
| **overall** | 44 | 93 | 129 | 64.3 | 89.2 | 74.8 | 70.5 | 97.8 | 82.0 | 80.3 | 0.0 | 2.5 | 1.6 | 100.0 | 97.5 | 15.34 | 21.85 |

## Per entity type: `hu`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 60 | 58 | 94.8 | 91.7 | 93.2 | 100.0 | 96.7 | 98.3 | 0.0 | 2.7 |
| `ADDRESS` | 1 | 4 | 25.0 | 100.0 | 40.0 | 25.0 | 100.0 | 40.0 | 0.0 | 0.0 |
| `EMAIL` | 1 | 1 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `PHONE` | 1 | 1 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `ORGANIZATION` | 30 | 65 | 38.5 | 83.3 | 52.6 | 46.2 | 100.0 | 63.2 | keep | keep |
| **all (micro)** | 93 | 129 | 64.3 | 89.2 | 74.8 | 70.5 | 97.8 | 82.0 | 0.0 | 2.5 |
