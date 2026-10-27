# pii-guard evaluation

- commit: `477196a3427c (dirty)`, pii-guard 0.1.0
- detectors: `rules`, `ner`
- fixtures: `eval/synthetic/dev/de-agent-traffic-dev.jsonl` sha256 `2014c599aa56203c`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `de` | 100 | 577 | 673 | 78.4 | 89.9 | 83.8 | 81.7 | 93.2 | 87.1 | 75.8 | 3.2 | 0.4 | 12.8 | 100.0 | 94.3 | 15.38 | 35.36 |
| **overall** | 100 | 577 | 673 | 78.4 | 89.9 | 83.8 | 81.7 | 93.2 | 87.1 | 75.8 | 3.2 | 0.4 | 12.8 | 100.0 | 94.3 | 15.38 | 35.36 |

## Per entity type: `de`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 180 | 187 | 96.3 | 100.0 | 98.1 | 96.3 | 100.0 | 98.1 | 0.0 | 0.0 |
| `ADDRESS` | 33 | 33 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `EMAIL` | 125 | 121 | 97.5 | 94.4 | 95.9 | 100.0 | 96.0 | 98.0 | 4.0 | 1.6 |
| `PHONE` | 92 | 106 | 81.1 | 93.5 | 86.9 | 84.0 | 96.7 | 89.9 | 2.2 | 0.0 |
| `DATE_OF_BIRTH` | 22 | 22 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `NATIONAL_ID_HU_TAX` | 0 | 4 | 0.0 | — | 0.0 | 0.0 | — | 0.0 | keep | keep |
| `ID_DOCUMENT` | 47 | 89 | 19.1 | 36.2 | 25.0 | 28.1 | 53.2 | 36.8 | 12.8 | 0.0 |
| `BANK_ACCOUNT` | 67 | 84 | 64.3 | 80.6 | 71.5 | 71.4 | 86.6 | 78.3 | 6.0 | 0.0 |
| `ORGANIZATION` | 11 | 16 | 56.2 | 81.8 | 66.7 | 68.8 | 100.0 | 81.5 | keep | keep |
| **all (micro)** | 577 | 662 | 78.4 | 89.9 | 83.8 | 81.7 | 93.2 | 87.1 | 3.2 | 0.4 |
