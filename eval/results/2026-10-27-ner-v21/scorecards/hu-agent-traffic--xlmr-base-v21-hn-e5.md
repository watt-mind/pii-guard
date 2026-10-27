# pii-guard evaluation

- commit: `477196a3427c (dirty)`, pii-guard 0.1.0
- detectors: `rules`, `ner`
- fixtures: `eval/synthetic/hu-agent-traffic.jsonl` sha256 `8fd6d0fa8a4313b9`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `hu` | 330 | 1853 | 2140 | 78.9 | 89.6 | 83.9 | 82.6 | 93.5 | 87.7 | 77.7 | 2.7 | 0.4 | 10.6 | 100.0 | 95.8 | 15.50 | 24.78 |
| **overall** | 330 | 1853 | 2140 | 78.9 | 89.6 | 83.9 | 82.6 | 93.5 | 87.7 | 77.7 | 2.7 | 0.4 | 10.6 | 100.0 | 95.8 | 15.50 | 24.78 |

## Per entity type: `hu`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 616 | 636 | 89.5 | 92.4 | 90.9 | 96.9 | 100.0 | 98.4 | 0.0 | 0.0 |
| `ADDRESS` | 73 | 73 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `EMAIL` | 400 | 389 | 97.4 | 94.8 | 96.1 | 100.0 | 96.5 | 98.2 | 3.5 | 1.8 |
| `PHONE` | 254 | 309 | 76.1 | 92.5 | 83.5 | 79.0 | 95.3 | 86.4 | 4.7 | 0.0 |
| `DATE_OF_BIRTH` | 73 | 72 | 100.0 | 98.6 | 99.3 | 100.0 | 98.6 | 99.3 | 1.4 | 0.0 |
| `NATIONAL_ID_HU_TAX` | 180 | 117 | 75.2 | 48.9 | 59.3 | 83.8 | 54.4 | 66.0 | 5.0 | 0.0 |
| `NATIONAL_ID_HU_TAJ` | 36 | 37 | 97.3 | 100.0 | 98.6 | 97.3 | 100.0 | 98.6 | 0.0 | 0.0 |
| `ID_DOCUMENT` | 0 | 97 | 0.0 | — | 0.0 | 0.0 | — | 0.0 | keep | keep |
| `BANK_ACCOUNT` | 184 | 275 | 62.2 | 92.9 | 74.5 | 62.9 | 94.0 | 75.4 | 5.4 | 0.0 |
| `ORGANIZATION` | 37 | 98 | 37.8 | 100.0 | 54.8 | 37.8 | 100.0 | 54.8 | keep | keep |
| **all (micro)** | 1853 | 2103 | 78.9 | 89.6 | 83.9 | 82.6 | 93.5 | 87.7 | 2.7 | 0.4 |
