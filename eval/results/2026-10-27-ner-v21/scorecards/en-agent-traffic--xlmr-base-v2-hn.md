# pii-guard evaluation

- commit: `477196a3427c (dirty)`, pii-guard 0.1.0
- detectors: `rules`, `ner`
- fixtures: `eval/synthetic/en-agent-traffic.jsonl` sha256 `0923f7f3ab5f25e1`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `en` | 330 | 1881 | 2122 | 81.6 | 90.4 | 85.8 | 84.5 | 93.7 | 88.9 | 70.5 | 3.8 | 1.2 | 12.5 | 100.0 | 94.1 | 14.96 | 23.03 |
| **overall** | 330 | 1881 | 2122 | 81.6 | 90.4 | 85.8 | 84.5 | 93.7 | 88.9 | 70.5 | 3.8 | 1.2 | 12.5 | 100.0 | 94.1 | 14.96 | 23.03 |

## Per entity type: `en`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 587 | 600 | 97.8 | 100.0 | 98.9 | 97.8 | 100.0 | 98.9 | 0.0 | 0.0 |
| `ADDRESS` | 109 | 114 | 95.6 | 100.0 | 97.8 | 95.6 | 100.0 | 97.8 | 0.0 | 0.0 |
| `EMAIL` | 407 | 389 | 96.1 | 91.9 | 94.0 | 100.0 | 95.6 | 97.7 | 3.2 | 4.9 |
| `PHONE` | 297 | 328 | 85.7 | 94.6 | 89.9 | 87.2 | 96.3 | 91.5 | 3.0 | 0.0 |
| `DATE_OF_BIRTH` | 73 | 73 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `NATIONAL_ID_HU_TAX` | 0 | 8 | 0.0 | — | 0.0 | 0.0 | — | 0.0 | keep | keep |
| `NATIONAL_ID_HU_TAJ` | 0 | 8 | 0.0 | — | 0.0 | 0.0 | — | 0.0 | keep | keep |
| `ID_DOCUMENT` | 151 | 182 | 22.5 | 27.2 | 24.6 | 44.5 | 53.6 | 48.6 | 16.6 | 0.0 |
| `BANK_ACCOUNT` | 220 | 346 | 57.5 | 90.5 | 70.3 | 57.8 | 90.9 | 70.7 | 8.6 | 0.0 |
| `ORGANIZATION` | 37 | 37 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | keep | keep |
| **all (micro)** | 1881 | 2085 | 81.6 | 90.4 | 85.8 | 84.5 | 93.7 | 88.9 | 3.8 | 1.2 |
