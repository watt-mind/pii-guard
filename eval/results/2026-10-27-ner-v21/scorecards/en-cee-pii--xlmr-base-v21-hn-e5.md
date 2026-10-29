# pii-guard evaluation

- commit: `477196a3427c (dirty)`, pii-guard 0.1.0
- detectors: `rules`, `ner`
- fixtures: `eval/datasets/cee-pii/en-cee-pii.jsonl` sha256 `a664e2a255f384ff`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `en` | 200 | 196 | 383 | 56.5 | 90.3 | 69.5 | 62.0 | 95.4 | 75.1 | 47.9 | 0.5 | 0.0 | 30.7 | 100.0 | 94.9 | 13.44 | 18.81 |
| **overall** | 200 | 196 | 383 | 56.5 | 90.3 | 69.5 | 62.0 | 95.4 | 75.1 | 47.9 | 0.5 | 0.0 | 30.7 | 100.0 | 94.9 | 13.44 | 18.81 |

## Per entity type: `en`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 13 | 18 | 66.7 | 92.3 | 77.4 | 72.2 | 100.0 | 83.9 | 0.0 | 0.0 |
| `ADDRESS` | 73 | 80 | 82.5 | 90.4 | 86.3 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `PHONE` | 0 | 11 | 0.0 | — | 0.0 | 0.0 | — | 0.0 | keep | keep |
| `DATE_OF_BIRTH` | 35 | 35 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `NATIONAL_ID_HU_TAX` | 0 | 1 | 0.0 | — | 0.0 | 0.0 | — | 0.0 | keep | keep |
| `NATIONAL_ID_HU_TAJ` | 0 | 1 | 0.0 | — | 0.0 | 0.0 | — | 0.0 | keep | keep |
| `ID_DOCUMENT` | 40 | 65 | 44.6 | 72.5 | 55.2 | 47.7 | 77.5 | 59.0 | 2.5 | 0.0 |
| `BANK_ACCOUNT` | 14 | 64 | 21.9 | 100.0 | 35.9 | 21.9 | 100.0 | 35.9 | 0.0 | 0.0 |
| `ORGANIZATION` | 0 | 17 | 0.0 | — | 0.0 | 0.0 | — | 0.0 | keep | keep |
| `VEHICLE_PLATE` | 21 | 21 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| **all (micro)** | 196 | 313 | 56.5 | 90.3 | 69.5 | 62.0 | 95.4 | 75.1 | 0.5 | 0.0 |
