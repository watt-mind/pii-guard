# pii-guard evaluation

- commit: `477196a3427c (dirty)`, pii-guard 0.1.0
- detectors: `rules`, `ner`
- fixtures: `eval/synthetic/dev/en-agent-traffic-dev.jsonl` sha256 `80ddf60dd1550851`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `en` | 100 | 549 | 683 | 74.7 | 91.4 | 82.2 | 76.6 | 92.7 | 83.9 | 63.0 | 1.8 | 0.6 | 17.3 | 100.0 | 96.0 | 14.46 | 22.31 |
| **overall** | 100 | 549 | 683 | 74.7 | 91.4 | 82.2 | 76.6 | 92.7 | 83.9 | 63.0 | 1.8 | 0.6 | 17.3 | 100.0 | 96.0 | 14.46 | 22.31 |

## Per entity type: `en`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 173 | 185 | 93.5 | 100.0 | 96.6 | 93.5 | 100.0 | 96.6 | 0.0 | 0.0 |
| `ADDRESS` | 33 | 40 | 82.5 | 100.0 | 90.4 | 82.5 | 100.0 | 90.4 | 0.0 | 0.0 |
| `EMAIL` | 118 | 122 | 93.4 | 96.6 | 95.0 | 100.0 | 98.3 | 99.1 | 1.7 | 1.7 |
| `PHONE` | 85 | 98 | 84.7 | 97.6 | 90.7 | 86.7 | 100.0 | 92.9 | 0.0 | 0.0 |
| `DATE_OF_BIRTH` | 22 | 22 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `NATIONAL_ID_HU_TAX` | 0 | 12 | 0.0 | — | 0.0 | 0.0 | — | 0.0 | keep | keep |
| `NATIONAL_ID_HU_TAJ` | 0 | 4 | 0.0 | — | 0.0 | 0.0 | — | 0.0 | keep | keep |
| `ID_DOCUMENT` | 40 | 48 | 8.3 | 10.0 | 9.1 | 10.4 | 12.5 | 11.4 | 17.5 | 2.5 |
| `BANK_ACCOUNT` | 67 | 121 | 51.2 | 92.5 | 66.0 | 52.9 | 95.5 | 68.1 | 0.0 | 0.0 |
| `ORGANIZATION` | 11 | 20 | 55.0 | 100.0 | 71.0 | 55.0 | 100.0 | 71.0 | keep | keep |
| **all (micro)** | 549 | 672 | 74.7 | 91.4 | 82.2 | 76.6 | 92.7 | 83.9 | 1.8 | 0.6 |
