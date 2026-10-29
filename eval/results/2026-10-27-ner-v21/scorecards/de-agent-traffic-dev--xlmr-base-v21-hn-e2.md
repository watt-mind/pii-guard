# pii-guard evaluation

- commit: `477196a3427c (dirty)`, pii-guard 0.1.0
- detectors: `rules`, `ner`
- fixtures: `eval/synthetic/dev/de-agent-traffic-dev.jsonl` sha256 `2014c599aa56203c`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `de` | 100 | 577 | 662 | 78.2 | 88.2 | 82.9 | 79.9 | 89.9 | 84.6 | 73.0 | 7.2 | 0.4 | 16.4 | 100.0 | 91.9 | 14.40 | 21.79 |
| **overall** | 100 | 577 | 662 | 78.2 | 88.2 | 82.9 | 79.9 | 89.9 | 84.6 | 73.0 | 7.2 | 0.4 | 16.4 | 100.0 | 91.9 | 14.40 | 21.79 |

## Per entity type: `de`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 180 | 193 | 93.3 | 100.0 | 96.5 | 93.3 | 100.0 | 96.5 | 0.0 | 0.0 |
| `ADDRESS` | 33 | 33 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `EMAIL` | 125 | 120 | 98.3 | 94.4 | 96.3 | 100.0 | 96.0 | 98.0 | 4.0 | 1.6 |
| `PHONE` | 92 | 102 | 84.3 | 93.5 | 88.7 | 87.3 | 96.7 | 91.8 | 2.2 | 0.0 |
| `DATE_OF_BIRTH` | 22 | 22 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `NATIONAL_ID_HU_TAX` | 0 | 5 | 0.0 | — | 0.0 | 0.0 | — | 0.0 | keep | keep |
| `ID_DOCUMENT` | 47 | 85 | 9.4 | 17.0 | 12.1 | 9.4 | 17.0 | 12.1 | 48.9 | 0.0 |
| `BANK_ACCOUNT` | 67 | 79 | 69.6 | 82.1 | 75.3 | 74.7 | 86.6 | 80.2 | 11.9 | 0.0 |
| `ORGANIZATION` | 11 | 12 | 58.3 | 63.6 | 60.9 | 75.0 | 81.8 | 78.3 | keep | keep |
| **all (micro)** | 577 | 651 | 78.2 | 88.2 | 82.9 | 79.9 | 89.9 | 84.6 | 7.2 | 0.4 |
