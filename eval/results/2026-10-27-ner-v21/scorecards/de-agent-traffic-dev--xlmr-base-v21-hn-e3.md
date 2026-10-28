# pii-guard evaluation

- commit: `477196a3427c (dirty)`, pii-guard 0.1.0
- detectors: `rules`, `ner`
- fixtures: `eval/synthetic/dev/de-agent-traffic-dev.jsonl` sha256 `2014c599aa56203c`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `de` | 100 | 577 | 671 | 78.8 | 90.1 | 84.1 | 82.6 | 93.4 | 87.7 | 76.1 | 4.0 | 1.3 | 14.2 | 100.0 | 94.0 | 14.98 | 23.72 |
| **overall** | 100 | 577 | 671 | 78.8 | 90.1 | 84.1 | 82.6 | 93.4 | 87.7 | 76.1 | 4.0 | 1.3 | 14.2 | 100.0 | 94.0 | 14.98 | 23.72 |

## Per entity type: `de`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 180 | 197 | 91.4 | 100.0 | 95.5 | 91.4 | 100.0 | 95.5 | 0.0 | 0.0 |
| `ADDRESS` | 33 | 33 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `EMAIL` | 125 | 120 | 98.3 | 94.4 | 96.3 | 100.0 | 96.0 | 98.0 | 4.0 | 1.6 |
| `PHONE` | 92 | 101 | 85.1 | 93.5 | 89.1 | 88.1 | 96.7 | 92.2 | 3.3 | 0.0 |
| `DATE_OF_BIRTH` | 22 | 17 | 94.1 | 72.7 | 82.1 | 100.0 | 77.3 | 87.2 | 22.7 | 0.0 |
| `NATIONAL_ID_HU_TAX` | 0 | 2 | 0.0 | — | 0.0 | 0.0 | — | 0.0 | keep | keep |
| `ID_DOCUMENT` | 47 | 89 | 30.3 | 57.4 | 39.7 | 37.1 | 70.2 | 48.5 | 8.5 | 0.0 |
| `BANK_ACCOUNT` | 67 | 91 | 56.0 | 76.1 | 64.6 | 70.3 | 86.6 | 77.6 | 6.0 | 7.5 |
| `ORGANIZATION` | 11 | 10 | 90.0 | 81.8 | 85.7 | 90.0 | 81.8 | 85.7 | keep | keep |
| **all (micro)** | 577 | 660 | 78.8 | 90.1 | 84.1 | 82.6 | 93.4 | 87.7 | 4.0 | 1.3 |
