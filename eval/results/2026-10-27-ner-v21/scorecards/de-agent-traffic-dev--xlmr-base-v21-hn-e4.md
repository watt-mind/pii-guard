# pii-guard evaluation

- commit: `477196a3427c (dirty)`, pii-guard 0.1.0
- detectors: `rules`, `ner`
- fixtures: `eval/synthetic/dev/de-agent-traffic-dev.jsonl` sha256 `2014c599aa56203c`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `de` | 100 | 577 | 626 | 82.1 | 87.5 | 84.7 | 85.0 | 89.9 | 87.4 | 72.2 | 6.6 | 0.4 | 9.9 | 100.0 | 91.9 | 13.60 | 19.22 |
| **overall** | 100 | 577 | 626 | 82.1 | 87.5 | 84.7 | 85.0 | 89.9 | 87.4 | 72.2 | 6.6 | 0.4 | 9.9 | 100.0 | 91.9 | 13.60 | 19.22 |

## Per entity type: `de`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 180 | 187 | 96.3 | 100.0 | 98.1 | 96.3 | 100.0 | 98.1 | 0.0 | 0.0 |
| `ADDRESS` | 33 | 33 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `EMAIL` | 125 | 120 | 98.3 | 94.4 | 96.3 | 100.0 | 96.0 | 98.0 | 4.0 | 1.6 |
| `PHONE` | 92 | 103 | 82.5 | 92.4 | 87.2 | 86.4 | 96.7 | 91.3 | 2.2 | 0.0 |
| `DATE_OF_BIRTH` | 22 | 21 | 95.2 | 90.9 | 93.0 | 100.0 | 95.5 | 97.7 | 4.5 | 0.0 |
| `NATIONAL_ID_HU_TAX` | 0 | 5 | 0.0 | — | 0.0 | 0.0 | — | 0.0 | keep | keep |
| `ID_DOCUMENT` | 47 | 45 | 17.8 | 17.0 | 17.4 | 22.2 | 21.3 | 21.7 | 38.3 | 0.0 |
| `BANK_ACCOUNT` | 67 | 84 | 61.9 | 77.6 | 68.9 | 72.6 | 85.1 | 78.4 | 13.4 | 0.0 |
| `ORGANIZATION` | 11 | 17 | 52.9 | 81.8 | 64.3 | 52.9 | 81.8 | 64.3 | keep | keep |
| **all (micro)** | 577 | 615 | 82.1 | 87.5 | 84.7 | 85.0 | 89.9 | 87.4 | 6.6 | 0.4 |
