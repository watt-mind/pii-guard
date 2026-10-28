# pii-guard evaluation

- commit: `477196a3427c (dirty)`, pii-guard 0.1.0
- detectors: `rules`, `ner`
- fixtures: `eval/datasets/nemotron-pii/en-nemotron-pii.jsonl` sha256 `2a76e6167d01c82c`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `en` | 300 | 987 | 1395 | 86.2 | 84.3 | 85.2 | 90.8 | 87.9 | 89.3 | 68.8 | 0.7 | 0.6 | 1.6 | 100.0 | 97.8 | 26.51 | 78.16 |
| **overall** | 300 | 987 | 1395 | 86.2 | 84.3 | 85.2 | 90.8 | 87.9 | 89.3 | 68.8 | 0.7 | 0.6 | 1.6 | 100.0 | 97.8 | 26.51 | 78.16 |

## Per entity type: `en`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 312 | 338 | 91.4 | 99.0 | 95.1 | 91.4 | 99.0 | 95.1 | 0.9 | 0.0 |
| `ADDRESS` | 54 | 69 | 53.6 | 68.5 | 60.2 | 84.1 | 98.1 | 90.6 | 0.0 | 6.1 |
| `EMAIL` | 179 | 179 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `PHONE` | 114 | 116 | 97.4 | 99.1 | 98.3 | 98.3 | 100.0 | 99.1 | 0.0 | 0.0 |
| `DATE_OF_BIRTH` | 66 | 66 | 92.4 | 92.4 | 92.4 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `NATIONAL_ID_HU_TAJ` | 0 | 2 | 0.0 | — | 0.0 | 0.0 | — | 0.0 | keep | keep |
| `ID_DOCUMENT` | 34 | 68 | 48.5 | 97.1 | 64.7 | 48.5 | 97.1 | 64.7 | 0.0 | 0.0 |
| `BANK_ACCOUNT` | 76 | 51 | 92.2 | 61.8 | 74.0 | 98.0 | 64.5 | 77.8 | 3.0 | 1.5 |
| `ORGANIZATION` | 142 | 76 | 69.7 | 37.3 | 48.6 | 88.2 | 45.8 | 60.3 | keep | keep |
| `VEHICLE_PLATE` | 10 | 0 | — | 0.0 | 0.0 | — | 0.0 | 0.0 | 10.0 | 0.0 |
| **all (micro)** | 987 | 965 | 86.2 | 84.3 | 85.2 | 90.8 | 87.9 | 89.3 | 0.7 | 0.6 |
