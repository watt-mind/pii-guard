# pii-guard evaluation

- commit: `477196a3427c (dirty)`, pii-guard 0.1.0
- detectors: `rules`, `ner`
- fixtures: `eval/synthetic/dev/de-agent-traffic-dev.jsonl` sha256 `2014c599aa56203c`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `de` | 100 | 577 | 671 | 79.8 | 91.3 | 85.2 | 82.4 | 93.9 | 87.8 | 85.8 | 1.7 | 0.8 | 12.8 | 100.0 | 95.8 | 14.82 | 23.37 |
| **overall** | 100 | 577 | 671 | 79.8 | 91.3 | 85.2 | 82.4 | 93.9 | 87.8 | 85.8 | 1.7 | 0.8 | 12.8 | 100.0 | 95.8 | 14.82 | 23.37 |

## Per entity type: `de`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 180 | 185 | 97.3 | 100.0 | 98.6 | 97.3 | 100.0 | 98.6 | 0.0 | 0.0 |
| `ADDRESS` | 33 | 34 | 97.1 | 100.0 | 98.5 | 97.1 | 100.0 | 98.5 | 0.0 | 0.0 |
| `EMAIL` | 125 | 122 | 96.7 | 94.4 | 95.5 | 100.0 | 96.8 | 98.4 | 3.2 | 2.4 |
| `PHONE` | 92 | 100 | 86.0 | 93.5 | 89.6 | 89.0 | 96.7 | 92.7 | 1.1 | 0.0 |
| `DATE_OF_BIRTH` | 22 | 24 | 91.7 | 100.0 | 95.7 | 91.7 | 100.0 | 95.7 | 0.0 | 0.0 |
| `ID_DOCUMENT` | 47 | 92 | 27.2 | 53.2 | 36.0 | 33.7 | 66.0 | 44.6 | 2.1 | 2.1 |
| `BANK_ACCOUNT` | 67 | 93 | 58.1 | 80.6 | 67.5 | 62.4 | 85.1 | 72.0 | 4.5 | 0.0 |
| `ORGANIZATION` | 11 | 10 | 90.0 | 81.8 | 85.7 | 90.0 | 81.8 | 85.7 | keep | keep |
| **all (micro)** | 577 | 660 | 79.8 | 91.3 | 85.2 | 82.4 | 93.9 | 87.8 | 1.7 | 0.8 |
