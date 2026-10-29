# pii-guard evaluation

- commit: `477196a3427c (dirty)`, pii-guard 0.1.0
- detectors: `rules`, `ner`
- fixtures: `eval/synthetic/de-agent-traffic.jsonl` sha256 `627c4b09bcb8d9b7`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `de` | 330 | 1853 | 2240 | 77.9 | 92.6 | 84.6 | 80.7 | 95.3 | 87.4 | 76.2 | 2.4 | 0.5 | 16.0 | 100.0 | 95.4 | 20.00 | 41.07 |
| **overall** | 330 | 1853 | 2240 | 77.9 | 92.6 | 84.6 | 80.7 | 95.3 | 87.4 | 76.2 | 2.4 | 0.5 | 16.0 | 100.0 | 95.4 | 20.00 | 41.07 |

## Per entity type: `de`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 580 | 592 | 98.0 | 100.0 | 99.0 | 98.0 | 100.0 | 99.0 | 0.0 | 0.0 |
| `ADDRESS` | 109 | 115 | 94.8 | 100.0 | 97.3 | 94.8 | 100.0 | 97.3 | 0.0 | 0.0 |
| `EMAIL` | 400 | 389 | 97.7 | 95.0 | 96.3 | 100.0 | 96.2 | 98.1 | 3.0 | 2.0 |
| `PHONE` | 290 | 318 | 86.5 | 94.8 | 90.5 | 88.1 | 96.6 | 92.1 | 2.8 | 0.0 |
| `DATE_OF_BIRTH` | 73 | 75 | 97.3 | 100.0 | 98.6 | 97.3 | 100.0 | 98.6 | 0.0 | 0.0 |
| `NATIONAL_ID_HU_TAX` | 0 | 2 | 0.0 | — | 0.0 | 0.0 | — | 0.0 | keep | keep |
| `ID_DOCUMENT` | 144 | 314 | 23.9 | 52.1 | 32.8 | 33.1 | 70.1 | 45.0 | 6.9 | 0.0 |
| `BANK_ACCOUNT` | 220 | 359 | 53.5 | 87.3 | 66.3 | 58.5 | 93.2 | 71.9 | 5.0 | 0.5 |
| `ORGANIZATION` | 37 | 39 | 82.1 | 86.5 | 84.2 | 82.1 | 86.5 | 84.2 | keep | keep |
| **all (micro)** | 1853 | 2203 | 77.9 | 92.6 | 84.6 | 80.7 | 95.3 | 87.4 | 2.4 | 0.5 |
