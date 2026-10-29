# pii-guard evaluation

- commit: `477196a3427c (dirty)`, pii-guard 0.1.0
- detectors: `rules`, `ner`
- fixtures: `eval/datasets/nemotron-pii/en-nemotron-pii.jsonl` sha256 `2a76e6167d01c82c`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `en` | 300 | 987 | 1395 | 87.0 | 83.6 | 85.3 | 91.8 | 86.8 | 89.2 | 75.4 | 0.7 | 0.4 | 2.4 | 99.7 | 98.3 | 19.03 | 48.70 |
| **overall** | 300 | 987 | 1395 | 87.0 | 83.6 | 85.3 | 91.8 | 86.8 | 89.2 | 75.4 | 0.7 | 0.4 | 2.4 | 99.7 | 98.3 | 19.03 | 48.70 |

## Per entity type: `en`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 312 | 326 | 94.8 | 99.0 | 96.9 | 94.8 | 99.0 | 96.9 | 0.9 | 0.0 |
| `ADDRESS` | 54 | 64 | 57.8 | 68.5 | 62.7 | 90.6 | 96.3 | 93.4 | 2.0 | 4.1 |
| `EMAIL` | 179 | 179 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `PHONE` | 114 | 116 | 98.3 | 100.0 | 99.1 | 98.3 | 100.0 | 99.1 | 0.0 | 0.0 |
| `DATE_OF_BIRTH` | 66 | 64 | 92.2 | 89.4 | 90.8 | 100.0 | 97.0 | 98.5 | 1.6 | 0.0 |
| `ID_DOCUMENT` | 34 | 84 | 40.5 | 100.0 | 57.6 | 40.5 | 100.0 | 57.6 | 0.0 | 0.0 |
| `BANK_ACCOUNT` | 76 | 52 | 90.4 | 61.8 | 73.4 | 98.1 | 63.2 | 76.8 | 0.0 | 1.5 |
| `ORGANIZATION` | 142 | 63 | 73.0 | 32.4 | 44.9 | 96.8 | 40.1 | 56.8 | keep | keep |
| `VEHICLE_PLATE` | 10 | 0 | — | 0.0 | 0.0 | — | 0.0 | 0.0 | 10.0 | 0.0 |
| **all (micro)** | 987 | 948 | 87.0 | 83.6 | 85.3 | 91.8 | 86.8 | 89.2 | 0.7 | 0.4 |
