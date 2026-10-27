# pii-guard evaluation

- commit: `477196a3427c (dirty)`, pii-guard 0.1.0
- detectors: `rules`, `ner`
- fixtures: `eval/synthetic/dev/hu-agent-traffic-dev.jsonl` sha256 `f5a0a0e3de68534f`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `hu` | 100 | 561 | 645 | 82.2 | 92.9 | 87.2 | 86.0 | 97.1 | 91.2 | 83.4 | 1.3 | 1.0 | 11.6 | 100.0 | 96.7 | 20.51 | 39.56 |
| **overall** | 100 | 561 | 645 | 82.2 | 92.9 | 87.2 | 86.0 | 97.1 | 91.2 | 83.4 | 1.3 | 1.0 | 11.6 | 100.0 | 96.7 | 20.51 | 39.56 |

## Per entity type: `hu`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 187 | 196 | 88.8 | 93.0 | 90.9 | 95.4 | 100.0 | 97.7 | 0.0 | 0.6 |
| `ADDRESS` | 22 | 23 | 95.7 | 100.0 | 97.8 | 95.7 | 100.0 | 97.8 | 0.0 | 0.0 |
| `EMAIL` | 121 | 115 | 97.4 | 92.6 | 94.9 | 100.0 | 95.0 | 97.5 | 4.1 | 3.3 |
| `PHONE` | 77 | 83 | 90.4 | 97.4 | 93.8 | 92.8 | 100.0 | 96.2 | 0.0 | 0.0 |
| `DATE_OF_BIRTH` | 22 | 22 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `NATIONAL_ID_HU_TAX` | 54 | 51 | 80.4 | 75.9 | 78.1 | 88.2 | 83.3 | 85.7 | 1.9 | 0.0 |
| `NATIONAL_ID_HU_TAJ` | 11 | 11 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `ID_DOCUMENT` | 0 | 26 | 0.0 | — | 0.0 | 0.0 | — | 0.0 | keep | keep |
| `BANK_ACCOUNT` | 56 | 92 | 57.6 | 94.6 | 71.6 | 59.8 | 98.2 | 74.3 | 1.8 | 0.0 |
| `ORGANIZATION` | 11 | 15 | 73.3 | 100.0 | 84.6 | 73.3 | 100.0 | 84.6 | keep | keep |
| **all (micro)** | 561 | 634 | 82.2 | 92.9 | 87.2 | 86.0 | 97.1 | 91.2 | 1.3 | 1.0 |
