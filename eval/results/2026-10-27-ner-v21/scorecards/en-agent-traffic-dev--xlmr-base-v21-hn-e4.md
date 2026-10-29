# pii-guard evaluation

- commit: `477196a3427c (dirty)`, pii-guard 0.1.0
- detectors: `rules`, `ner`
- fixtures: `eval/synthetic/dev/en-agent-traffic-dev.jsonl` sha256 `80ddf60dd1550851`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `en` | 100 | 549 | 610 | 83.0 | 90.5 | 86.6 | 84.3 | 91.6 | 87.8 | 65.8 | 3.4 | 0.4 | 9.9 | 100.0 | 95.2 | 13.63 | 19.20 |
| **overall** | 100 | 549 | 610 | 83.0 | 90.5 | 86.6 | 84.3 | 91.6 | 87.8 | 65.8 | 3.4 | 0.4 | 9.9 | 100.0 | 95.2 | 13.63 | 19.20 |

## Per entity type: `en`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 173 | 181 | 95.6 | 100.0 | 97.7 | 95.6 | 100.0 | 97.7 | 0.0 | 0.0 |
| `ADDRESS` | 33 | 33 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `EMAIL` | 118 | 114 | 100.0 | 96.6 | 98.3 | 100.0 | 96.6 | 98.3 | 2.5 | 0.8 |
| `PHONE` | 85 | 99 | 83.8 | 97.6 | 90.2 | 84.8 | 98.8 | 91.3 | 1.2 | 0.0 |
| `DATE_OF_BIRTH` | 22 | 22 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `NATIONAL_ID_HU_TAX` | 0 | 12 | 0.0 | — | 0.0 | 0.0 | — | 0.0 | keep | keep |
| `NATIONAL_ID_HU_TAJ` | 0 | 3 | 0.0 | — | 0.0 | 0.0 | — | 0.0 | keep | keep |
| `ID_DOCUMENT` | 40 | 26 | 3.8 | 2.5 | 3.0 | 11.5 | 7.5 | 9.1 | 30.0 | 2.5 |
| `BANK_ACCOUNT` | 67 | 93 | 64.5 | 89.6 | 75.0 | 69.9 | 94.0 | 80.2 | 1.5 | 0.0 |
| `ORGANIZATION` | 11 | 16 | 68.8 | 100.0 | 81.5 | 68.8 | 100.0 | 81.5 | keep | keep |
| **all (micro)** | 549 | 599 | 83.0 | 90.5 | 86.6 | 84.3 | 91.6 | 87.8 | 3.4 | 0.4 |
