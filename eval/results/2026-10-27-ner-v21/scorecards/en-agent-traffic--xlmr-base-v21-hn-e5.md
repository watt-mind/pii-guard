# pii-guard evaluation

- commit: `477196a3427c (dirty)`, pii-guard 0.1.0
- detectors: `rules`, `ner`
- fixtures: `eval/synthetic/en-agent-traffic.jsonl` sha256 `0923f7f3ab5f25e1`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `en` | 330 | 1881 | 2138 | 80.1 | 89.5 | 84.5 | 82.9 | 91.9 | 87.2 | 67.8 | 4.6 | 1.0 | 13.2 | 100.0 | 93.5 | 14.69 | 23.38 |
| **overall** | 330 | 1881 | 2138 | 80.1 | 89.5 | 84.5 | 82.9 | 91.9 | 87.2 | 67.8 | 4.6 | 1.0 | 13.2 | 100.0 | 93.5 | 14.69 | 23.38 |

## Per entity type: `en`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 587 | 607 | 96.7 | 100.0 | 98.3 | 96.7 | 100.0 | 98.3 | 0.0 | 0.0 |
| `ADDRESS` | 109 | 109 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `EMAIL` | 407 | 392 | 95.4 | 91.9 | 93.6 | 100.0 | 95.1 | 97.5 | 4.7 | 3.4 |
| `PHONE` | 297 | 331 | 84.0 | 93.6 | 88.5 | 86.4 | 96.0 | 90.9 | 3.0 | 0.0 |
| `DATE_OF_BIRTH` | 73 | 72 | 100.0 | 98.6 | 99.3 | 100.0 | 98.6 | 99.3 | 1.4 | 0.0 |
| `NATIONAL_ID_HU_TAX` | 0 | 15 | 0.0 | — | 0.0 | 0.0 | — | 0.0 | keep | keep |
| `NATIONAL_ID_HU_TAJ` | 0 | 6 | 0.0 | — | 0.0 | 0.0 | — | 0.0 | keep | keep |
| `ID_DOCUMENT` | 151 | 202 | 13.4 | 17.9 | 15.3 | 26.2 | 33.1 | 29.3 | 23.8 | 1.3 |
| `BANK_ACCOUNT` | 220 | 319 | 62.4 | 90.5 | 73.8 | 64.6 | 91.8 | 75.8 | 6.4 | 0.5 |
| `ORGANIZATION` | 37 | 48 | 77.1 | 100.0 | 87.1 | 77.1 | 100.0 | 87.1 | keep | keep |
| **all (micro)** | 1881 | 2101 | 80.1 | 89.5 | 84.5 | 82.9 | 91.9 | 87.2 | 4.6 | 1.0 |
