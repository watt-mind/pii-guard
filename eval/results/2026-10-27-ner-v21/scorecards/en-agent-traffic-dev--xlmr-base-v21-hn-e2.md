# pii-guard evaluation

- commit: `477196a3427c (dirty)`, pii-guard 0.1.0
- detectors: `rules`, `ner`
- fixtures: `eval/synthetic/dev/en-agent-traffic-dev.jsonl` sha256 `80ddf60dd1550851`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `en` | 100 | 549 | 616 | 82.0 | 90.3 | 86.0 | 82.6 | 91.1 | 86.7 | 66.9 | 4.4 | 0.0 | 12.8 | 100.0 | 94.6 | 14.57 | 23.54 |
| **overall** | 100 | 549 | 616 | 82.0 | 90.3 | 86.0 | 82.6 | 91.1 | 86.7 | 66.9 | 4.4 | 0.0 | 12.8 | 100.0 | 94.6 | 14.57 | 23.54 |

## Per entity type: `en`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 173 | 183 | 94.5 | 100.0 | 97.2 | 94.5 | 100.0 | 97.2 | 0.0 | 0.0 |
| `ADDRESS` | 33 | 33 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `EMAIL` | 118 | 114 | 100.0 | 96.6 | 98.3 | 100.0 | 96.6 | 98.3 | 3.4 | 0.0 |
| `PHONE` | 85 | 96 | 86.5 | 97.6 | 91.7 | 86.5 | 97.6 | 91.7 | 2.4 | 0.0 |
| `DATE_OF_BIRTH` | 22 | 22 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `NATIONAL_ID_HU_TAX` | 0 | 18 | 0.0 | — | 0.0 | 0.0 | — | 0.0 | keep | keep |
| `NATIONAL_ID_HU_TAJ` | 0 | 3 | 0.0 | — | 0.0 | 0.0 | — | 0.0 | keep | keep |
| `ID_DOCUMENT` | 40 | 40 | 0.0 | 0.0 | 0.0 | 2.5 | 2.5 | 2.5 | 37.5 | 0.0 |
| `BANK_ACCOUNT` | 67 | 84 | 72.6 | 91.0 | 80.8 | 75.0 | 94.0 | 83.4 | 1.5 | 0.0 |
| `ORGANIZATION` | 11 | 12 | 83.3 | 90.9 | 87.0 | 91.7 | 100.0 | 95.7 | keep | keep |
| **all (micro)** | 549 | 605 | 82.0 | 90.3 | 86.0 | 82.6 | 91.1 | 86.7 | 4.4 | 0.0 |
