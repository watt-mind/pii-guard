# pii-guard evaluation

- commit: `910a6a27f002 (dirty)`, pii-guard 0.1.0
- detectors: `rules`, `ner`
- fixtures: `eval/fixtures/hu-company-names.jsonl` sha256 `d4565df38ae2803a`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `hu` | 44 | 93 | 118 | 60.2 | 76.3 | 67.3 | 78.8 | 95.7 | 86.4 | 93.5 | 0.0 | 2.5 | 5.6 | 100.0 | 97.5 | 27.98 | 231.35 |
| **overall** | 44 | 93 | 118 | 60.2 | 76.3 | 67.3 | 78.8 | 95.7 | 86.4 | 93.5 | 0.0 | 2.5 | 5.6 | 100.0 | 97.5 | 27.98 | 231.35 |

## Per entity type: `hu`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 60 | 68 | 80.9 | 91.7 | 85.9 | 88.2 | 100.0 | 93.8 | 0.0 | 2.7 |
| `ADDRESS` | 1 | 1 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `EMAIL` | 1 | 1 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `PHONE` | 1 | 1 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `ORGANIZATION` | 30 | 47 | 27.7 | 43.3 | 33.8 | 63.8 | 86.7 | 73.5 | keep | keep |
| **all (micro)** | 93 | 118 | 60.2 | 76.3 | 67.3 | 78.8 | 95.7 | 86.4 | 0.0 | 2.5 |
