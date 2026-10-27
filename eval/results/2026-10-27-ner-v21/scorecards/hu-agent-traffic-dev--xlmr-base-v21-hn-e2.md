# pii-guard evaluation

- commit: `477196a3427c (dirty)`, pii-guard 0.1.0
- detectors: `rules`, `ner`
- fixtures: `eval/synthetic/dev/hu-agent-traffic-dev.jsonl` sha256 `f5a0a0e3de68534f`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `hu` | 100 | 561 | 655 | 78.9 | 90.6 | 84.3 | 82.8 | 95.0 | 88.5 | 75.2 | 2.9 | 0.4 | 13.4 | 100.0 | 96.0 | 19.25 | 34.28 |
| **overall** | 100 | 561 | 655 | 78.9 | 90.6 | 84.3 | 82.8 | 95.0 | 88.5 | 75.2 | 2.9 | 0.4 | 13.4 | 100.0 | 96.0 | 19.25 | 34.28 |

## Per entity type: `hu`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 187 | 195 | 87.2 | 90.9 | 89.0 | 95.9 | 100.0 | 97.9 | 0.0 | 0.0 |
| `ADDRESS` | 22 | 22 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `EMAIL` | 121 | 114 | 98.2 | 92.6 | 95.3 | 100.0 | 94.2 | 97.0 | 5.8 | 1.7 |
| `PHONE` | 77 | 86 | 88.4 | 98.7 | 93.3 | 88.4 | 98.7 | 93.3 | 1.3 | 0.0 |
| `DATE_OF_BIRTH` | 22 | 22 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `NATIONAL_ID_HU_TAX` | 54 | 44 | 72.7 | 59.3 | 65.3 | 81.8 | 66.7 | 73.5 | 11.1 | 0.0 |
| `NATIONAL_ID_HU_TAJ` | 11 | 34 | 32.4 | 100.0 | 48.9 | 32.4 | 100.0 | 48.9 | 0.0 | 0.0 |
| `ID_DOCUMENT` | 0 | 21 | 0.0 | — | 0.0 | 0.0 | — | 0.0 | keep | keep |
| `BANK_ACCOUNT` | 56 | 82 | 63.4 | 92.9 | 75.4 | 65.9 | 96.4 | 78.3 | 1.8 | 0.0 |
| `ORGANIZATION` | 11 | 24 | 45.8 | 100.0 | 62.9 | 45.8 | 100.0 | 62.9 | keep | keep |
| **all (micro)** | 561 | 644 | 78.9 | 90.6 | 84.3 | 82.8 | 95.0 | 88.5 | 2.9 | 0.4 |
