# pii-guard evaluation

- commit: `477196a3427c (dirty)`, pii-guard 0.1.0
- detectors: `rules`, `ner`
- fixtures: `eval/synthetic/dev/en-agent-traffic-dev.jsonl` sha256 `80ddf60dd1550851`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `en` | 100 | 549 | 627 | 82.5 | 92.5 | 87.2 | 83.6 | 93.6 | 88.3 | 70.0 | 2.6 | 0.6 | 13.1 | 100.0 | 96.0 | 13.53 | 19.17 |
| **overall** | 100 | 549 | 627 | 82.5 | 92.5 | 87.2 | 83.6 | 93.6 | 88.3 | 70.0 | 2.6 | 0.6 | 13.1 | 100.0 | 96.0 | 13.53 | 19.17 |

## Per entity type: `en`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 173 | 182 | 95.1 | 100.0 | 97.5 | 95.1 | 100.0 | 97.5 | 0.0 | 0.0 |
| `ADDRESS` | 33 | 33 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `EMAIL` | 118 | 115 | 99.1 | 96.6 | 97.9 | 100.0 | 97.5 | 98.7 | 2.5 | 0.8 |
| `PHONE` | 85 | 93 | 89.2 | 97.6 | 93.3 | 90.3 | 98.8 | 94.4 | 1.2 | 0.0 |
| `DATE_OF_BIRTH` | 22 | 22 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `NATIONAL_ID_HU_TAX` | 0 | 15 | 0.0 | — | 0.0 | 0.0 | — | 0.0 | keep | keep |
| `NATIONAL_ID_HU_TAJ` | 0 | 3 | 0.0 | — | 0.0 | 0.0 | — | 0.0 | keep | keep |
| `ID_DOCUMENT` | 40 | 55 | 21.8 | 30.0 | 25.3 | 23.6 | 32.5 | 27.4 | 20.0 | 2.5 |
| `BANK_ACCOUNT` | 67 | 87 | 69.0 | 89.6 | 77.9 | 73.6 | 94.0 | 82.5 | 1.5 | 1.5 |
| `ORGANIZATION` | 11 | 11 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | keep | keep |
| **all (micro)** | 549 | 616 | 82.5 | 92.5 | 87.2 | 83.6 | 93.6 | 88.3 | 2.6 | 0.6 |
