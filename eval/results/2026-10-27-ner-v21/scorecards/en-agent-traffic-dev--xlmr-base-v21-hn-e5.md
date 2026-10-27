# pii-guard evaluation

- commit: `477196a3427c (dirty)`, pii-guard 0.1.0
- detectors: `rules`, `ner`
- fixtures: `eval/synthetic/dev/en-agent-traffic-dev.jsonl` sha256 `80ddf60dd1550851`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `en` | 100 | 549 | 621 | 82.8 | 92.0 | 87.1 | 84.4 | 93.6 | 88.8 | 68.9 | 2.0 | 0.4 | 10.7 | 100.0 | 96.4 | 23.42 | 43.59 |
| **overall** | 100 | 549 | 621 | 82.8 | 92.0 | 87.1 | 84.4 | 93.6 | 88.8 | 68.9 | 2.0 | 0.4 | 10.7 | 100.0 | 96.4 | 23.42 | 43.59 |

## Per entity type: `en`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 173 | 181 | 95.6 | 100.0 | 97.7 | 95.6 | 100.0 | 97.7 | 0.0 | 0.0 |
| `ADDRESS` | 33 | 33 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `EMAIL` | 118 | 114 | 100.0 | 96.6 | 98.3 | 100.0 | 96.6 | 98.3 | 2.5 | 0.8 |
| `PHONE` | 85 | 98 | 84.7 | 97.6 | 90.7 | 85.7 | 98.8 | 91.8 | 1.2 | 0.0 |
| `DATE_OF_BIRTH` | 22 | 22 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `NATIONAL_ID_HU_TAX` | 0 | 7 | 0.0 | — | 0.0 | 0.0 | — | 0.0 | keep | keep |
| `NATIONAL_ID_HU_TAJ` | 0 | 3 | 0.0 | — | 0.0 | 0.0 | — | 0.0 | keep | keep |
| `ID_DOCUMENT` | 40 | 50 | 16.0 | 20.0 | 17.8 | 30.0 | 35.0 | 32.3 | 12.5 | 2.5 |
| `BANK_ACCOUNT` | 67 | 88 | 69.3 | 91.0 | 78.7 | 71.6 | 94.0 | 81.3 | 1.5 | 0.0 |
| `ORGANIZATION` | 11 | 14 | 78.6 | 100.0 | 88.0 | 78.6 | 100.0 | 88.0 | keep | keep |
| **all (micro)** | 549 | 610 | 82.8 | 92.0 | 87.1 | 84.4 | 93.6 | 88.8 | 2.0 | 0.4 |
