# pii-guard evaluation

- commit: `477196a3427c (dirty)`, pii-guard 0.1.0
- detectors: `rules`, `ner`
- fixtures: `eval/synthetic/dev/hu-agent-traffic-dev.jsonl` sha256 `f5a0a0e3de68534f`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `hu` | 100 | 561 | 662 | 77.7 | 90.2 | 83.5 | 82.6 | 95.0 | 88.4 | 78.0 | 1.9 | 0.2 | 10.0 | 100.0 | 94.5 | 15.40 | 26.95 |
| **overall** | 100 | 561 | 662 | 77.7 | 90.2 | 83.5 | 82.6 | 95.0 | 88.4 | 78.0 | 1.9 | 0.2 | 10.0 | 100.0 | 94.5 | 15.40 | 26.95 |

## Per entity type: `hu`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 187 | 195 | 89.2 | 93.0 | 91.1 | 96.4 | 100.0 | 98.2 | 0.0 | 0.0 |
| `ADDRESS` | 22 | 22 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `EMAIL` | 121 | 116 | 96.6 | 92.6 | 94.5 | 100.0 | 94.2 | 97.0 | 5.8 | 0.8 |
| `PHONE` | 77 | 93 | 81.7 | 98.7 | 89.4 | 81.7 | 98.7 | 89.4 | 1.3 | 0.0 |
| `DATE_OF_BIRTH` | 22 | 22 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `NATIONAL_ID_HU_TAX` | 54 | 43 | 62.8 | 50.0 | 55.7 | 86.0 | 66.7 | 75.1 | 1.9 | 0.0 |
| `NATIONAL_ID_HU_TAJ` | 11 | 13 | 84.6 | 100.0 | 91.7 | 84.6 | 100.0 | 91.7 | 0.0 | 0.0 |
| `ID_DOCUMENT` | 0 | 30 | 0.0 | — | 0.0 | 0.0 | — | 0.0 | keep | keep |
| `BANK_ACCOUNT` | 56 | 85 | 60.0 | 91.1 | 72.3 | 64.7 | 96.4 | 77.4 | 1.8 | 0.0 |
| `ORGANIZATION` | 11 | 32 | 34.4 | 100.0 | 51.2 | 34.4 | 100.0 | 51.2 | keep | keep |
| **all (micro)** | 561 | 651 | 77.7 | 90.2 | 83.5 | 82.6 | 95.0 | 88.4 | 1.9 | 0.2 |
