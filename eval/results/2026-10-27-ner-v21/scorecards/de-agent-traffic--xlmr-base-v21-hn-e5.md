# pii-guard evaluation

- commit: `477196a3427c (dirty)`, pii-guard 0.1.0
- detectors: `rules`, `ner`
- fixtures: `eval/synthetic/de-agent-traffic.jsonl` sha256 `627c4b09bcb8d9b7`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `de` | 330 | 1853 | 2180 | 79.8 | 92.3 | 85.6 | 81.7 | 94.1 | 87.5 | 74.5 | 2.9 | 0.2 | 13.5 | 100.0 | 95.1 | 14.93 | 27.85 |
| **overall** | 330 | 1853 | 2180 | 79.8 | 92.3 | 85.6 | 81.7 | 94.1 | 87.5 | 74.5 | 2.9 | 0.2 | 13.5 | 100.0 | 95.1 | 14.93 | 27.85 |

## Per entity type: `de`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 580 | 592 | 98.0 | 100.0 | 99.0 | 98.0 | 100.0 | 99.0 | 0.0 | 0.0 |
| `ADDRESS` | 109 | 109 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `EMAIL` | 400 | 386 | 98.4 | 95.0 | 96.7 | 100.0 | 96.0 | 98.0 | 3.8 | 1.0 |
| `PHONE` | 290 | 334 | 82.3 | 94.8 | 88.1 | 83.2 | 95.5 | 89.0 | 2.8 | 0.0 |
| `DATE_OF_BIRTH` | 73 | 71 | 100.0 | 97.3 | 98.6 | 100.0 | 97.3 | 98.6 | 2.7 | 0.0 |
| `NATIONAL_ID_HU_TAX` | 0 | 4 | 0.0 | — | 0.0 | 0.0 | — | 0.0 | keep | keep |
| `ID_DOCUMENT` | 144 | 277 | 23.8 | 45.8 | 31.4 | 28.2 | 54.2 | 37.1 | 10.4 | 0.0 |
| `BANK_ACCOUNT` | 220 | 298 | 65.4 | 88.6 | 75.3 | 71.1 | 94.1 | 81.0 | 4.1 | 0.0 |
| `ORGANIZATION` | 37 | 72 | 48.6 | 94.6 | 64.2 | 51.4 | 100.0 | 67.9 | keep | keep |
| **all (micro)** | 1853 | 2143 | 79.8 | 92.3 | 85.6 | 81.7 | 94.1 | 87.5 | 2.9 | 0.2 |
