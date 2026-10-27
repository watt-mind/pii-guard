# pii-guard evaluation

- commit: `477196a3427c (dirty)`, pii-guard 0.1.0
- detectors: `rules`, `ner`
- fixtures: `eval/synthetic/hu-agent-traffic.jsonl` sha256 `8fd6d0fa8a4313b9`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `hu` | 330 | 1853 | 2178 | 79.1 | 91.4 | 84.8 | 82.8 | 95.5 | 88.7 | 81.3 | 1.7 | 0.7 | 13.4 | 100.0 | 96.5 | 17.17 | 36.49 |
| **overall** | 330 | 1853 | 2178 | 79.1 | 91.4 | 84.8 | 82.8 | 95.5 | 88.7 | 81.3 | 1.7 | 0.7 | 13.4 | 100.0 | 96.5 | 17.17 | 36.49 |

## Per entity type: `hu`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 616 | 643 | 88.6 | 92.5 | 90.5 | 95.8 | 100.0 | 97.9 | 0.0 | 0.2 |
| `ADDRESS` | 73 | 73 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `EMAIL` | 400 | 389 | 97.2 | 94.5 | 95.8 | 100.0 | 97.2 | 98.6 | 2.8 | 2.8 |
| `PHONE` | 254 | 284 | 83.5 | 93.3 | 88.1 | 85.9 | 95.7 | 90.5 | 2.4 | 0.0 |
| `DATE_OF_BIRTH` | 73 | 73 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `NATIONAL_ID_HU_TAX` | 180 | 148 | 78.4 | 64.4 | 70.7 | 86.5 | 70.6 | 77.7 | 1.7 | 0.0 |
| `NATIONAL_ID_HU_TAJ` | 36 | 38 | 94.7 | 100.0 | 97.3 | 94.7 | 100.0 | 97.3 | 0.0 | 0.0 |
| `ID_DOCUMENT` | 0 | 117 | 0.0 | — | 0.0 | 0.0 | — | 0.0 | keep | keep |
| `BANK_ACCOUNT` | 184 | 322 | 53.7 | 94.0 | 68.4 | 54.7 | 95.1 | 69.4 | 4.9 | 0.0 |
| `ORGANIZATION` | 37 | 54 | 68.5 | 100.0 | 81.3 | 68.5 | 100.0 | 81.3 | keep | keep |
| **all (micro)** | 1853 | 2141 | 79.1 | 91.4 | 84.8 | 82.8 | 95.5 | 88.7 | 1.7 | 0.7 |
