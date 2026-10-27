# pii-guard evaluation

- commit: `477196a3427c (dirty)`, pii-guard 0.1.0
- detectors: `rules`, `ner`
- fixtures: `eval/synthetic/dev/de-agent-traffic-dev.jsonl` sha256 `2014c599aa56203c`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `de` | 100 | 577 | 690 | 75.0 | 88.2 | 81.1 | 78.2 | 90.5 | 83.9 | 69.1 | 3.8 | 0.8 | 14.8 | 100.0 | 94.0 | 14.76 | 23.24 |
| **overall** | 100 | 577 | 690 | 75.0 | 88.2 | 81.1 | 78.2 | 90.5 | 83.9 | 69.1 | 3.8 | 0.8 | 14.8 | 100.0 | 94.0 | 14.76 | 23.24 |

## Per entity type: `de`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 180 | 192 | 93.8 | 100.0 | 96.8 | 93.8 | 100.0 | 96.8 | 0.0 | 0.0 |
| `ADDRESS` | 33 | 41 | 75.6 | 93.9 | 83.8 | 80.5 | 100.0 | 89.2 | 0.0 | 6.1 |
| `EMAIL` | 125 | 129 | 91.5 | 94.4 | 92.9 | 100.0 | 96.8 | 98.4 | 3.2 | 0.8 |
| `PHONE` | 92 | 100 | 85.0 | 92.4 | 88.5 | 88.0 | 95.7 | 91.7 | 2.2 | 0.0 |
| `DATE_OF_BIRTH` | 22 | 22 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `NATIONAL_ID_HU_TAX` | 0 | 3 | 0.0 | — | 0.0 | 0.0 | — | 0.0 | keep | keep |
| `ID_DOCUMENT` | 47 | 49 | 16.3 | 17.0 | 16.7 | 18.4 | 19.1 | 18.7 | 14.9 | 0.0 |
| `BANK_ACCOUNT` | 67 | 120 | 45.0 | 80.6 | 57.8 | 49.2 | 86.6 | 62.7 | 10.4 | 1.5 |
| `ORGANIZATION` | 11 | 23 | 47.8 | 100.0 | 64.7 | 47.8 | 100.0 | 64.7 | keep | keep |
| **all (micro)** | 577 | 679 | 75.0 | 88.2 | 81.1 | 78.2 | 90.5 | 83.9 | 3.8 | 0.8 |
