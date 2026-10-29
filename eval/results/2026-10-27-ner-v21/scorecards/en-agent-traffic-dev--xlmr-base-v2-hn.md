# pii-guard evaluation

- commit: `477196a3427c (dirty)`, pii-guard 0.1.0
- detectors: `rules`, `ner`
- fixtures: `eval/synthetic/dev/en-agent-traffic-dev.jsonl` sha256 `80ddf60dd1550851`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `en` | 100 | 549 | 621 | 84.8 | 94.2 | 89.2 | 86.2 | 95.6 | 90.7 | 71.6 | 2.2 | 0.2 | 11.4 | 100.0 | 95.8 | 14.48 | 22.74 |
| **overall** | 100 | 549 | 621 | 84.8 | 94.2 | 89.2 | 86.2 | 95.6 | 90.7 | 71.6 | 2.2 | 0.2 | 11.4 | 100.0 | 95.8 | 14.48 | 22.74 |

## Per entity type: `en`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 173 | 177 | 97.7 | 100.0 | 98.9 | 97.7 | 100.0 | 98.9 | 0.0 | 0.0 |
| `ADDRESS` | 33 | 35 | 94.3 | 100.0 | 97.1 | 94.3 | 100.0 | 97.1 | 0.0 | 0.0 |
| `EMAIL` | 118 | 115 | 99.1 | 96.6 | 97.9 | 100.0 | 97.5 | 98.7 | 2.5 | 0.8 |
| `PHONE` | 85 | 98 | 84.7 | 97.6 | 90.7 | 86.7 | 98.8 | 92.4 | 1.2 | 0.0 |
| `DATE_OF_BIRTH` | 22 | 22 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `NATIONAL_ID_HU_TAX` | 0 | 2 | 0.0 | — | 0.0 | 0.0 | — | 0.0 | keep | keep |
| `NATIONAL_ID_HU_TAJ` | 0 | 3 | 0.0 | — | 0.0 | 0.0 | — | 0.0 | keep | keep |
| `ID_DOCUMENT` | 40 | 55 | 32.7 | 45.0 | 37.9 | 41.8 | 57.5 | 48.4 | 10.0 | 0.0 |
| `BANK_ACCOUNT` | 67 | 92 | 68.5 | 94.0 | 79.2 | 69.6 | 95.5 | 80.5 | 4.5 | 0.0 |
| `ORGANIZATION` | 11 | 11 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | keep | keep |
| **all (micro)** | 549 | 610 | 84.8 | 94.2 | 89.2 | 86.2 | 95.6 | 90.7 | 2.2 | 0.2 |
