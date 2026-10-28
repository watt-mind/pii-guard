# pii-guard evaluation

- commit: `477196a3427c (dirty)`, pii-guard 0.1.0
- detectors: `rules`, `ner`
- fixtures: `eval/synthetic/dev/hu-agent-traffic-dev.jsonl` sha256 `f5a0a0e3de68534f`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `hu` | 100 | 561 | 719 | 70.9 | 89.5 | 79.1 | 74.7 | 93.0 | 82.9 | 70.4 | 1.9 | 0.8 | 17.7 | 100.0 | 95.0 | 15.70 | 24.18 |
| **overall** | 100 | 561 | 719 | 70.9 | 89.5 | 79.1 | 74.7 | 93.0 | 82.9 | 70.4 | 1.9 | 0.8 | 17.7 | 100.0 | 95.0 | 15.70 | 24.18 |

## Per entity type: `hu`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 187 | 197 | 88.8 | 93.6 | 91.1 | 95.4 | 100.0 | 97.7 | 0.0 | 0.6 |
| `ADDRESS` | 22 | 35 | 62.9 | 100.0 | 77.2 | 62.9 | 100.0 | 77.2 | 0.0 | 0.0 |
| `EMAIL` | 121 | 123 | 91.9 | 93.4 | 92.6 | 100.0 | 96.7 | 98.3 | 3.3 | 2.5 |
| `PHONE` | 77 | 94 | 79.8 | 97.4 | 87.7 | 80.9 | 98.7 | 88.9 | 1.3 | 0.0 |
| `DATE_OF_BIRTH` | 22 | 22 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `NATIONAL_ID_HU_TAX` | 54 | 28 | 78.6 | 40.7 | 53.7 | 82.1 | 42.6 | 56.1 | 7.4 | 0.0 |
| `NATIONAL_ID_HU_TAJ` | 11 | 18 | 61.1 | 100.0 | 75.9 | 61.1 | 100.0 | 75.9 | 0.0 | 0.0 |
| `ID_DOCUMENT` | 0 | 39 | 0.0 | — | 0.0 | 0.0 | — | 0.0 | keep | keep |
| `BANK_ACCOUNT` | 56 | 118 | 43.2 | 91.1 | 58.6 | 44.9 | 94.6 | 60.9 | 1.8 | 0.0 |
| `ORGANIZATION` | 11 | 34 | 32.4 | 100.0 | 48.9 | 32.4 | 100.0 | 48.9 | keep | keep |
| **all (micro)** | 561 | 708 | 70.9 | 89.5 | 79.1 | 74.7 | 93.0 | 82.9 | 1.9 | 0.8 |
