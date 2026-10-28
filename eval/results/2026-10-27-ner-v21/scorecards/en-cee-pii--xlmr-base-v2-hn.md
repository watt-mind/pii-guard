# pii-guard evaluation

- commit: `477196a3427c (dirty)`, pii-guard 0.1.0
- detectors: `rules`, `ner`
- fixtures: `eval/datasets/cee-pii/en-cee-pii.jsonl` sha256 `a664e2a255f384ff`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `en` | 200 | 196 | 440 | 52.3 | 91.8 | 66.7 | 54.4 | 93.9 | 68.9 | 49.7 | 0.0 | 0.0 | 42.2 | 100.0 | 98.5 | 13.00 | 19.16 |
| **overall** | 200 | 196 | 440 | 52.3 | 91.8 | 66.7 | 54.4 | 93.9 | 68.9 | 49.7 | 0.0 | 0.0 | 42.2 | 100.0 | 98.5 | 13.00 | 19.16 |

## Per entity type: `en`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 13 | 20 | 60.0 | 92.3 | 72.7 | 65.0 | 100.0 | 78.8 | 0.0 | 0.0 |
| `ADDRESS` | 73 | 84 | 83.3 | 95.9 | 89.2 | 90.5 | 100.0 | 95.0 | 0.0 | 0.0 |
| `PHONE` | 0 | 9 | 0.0 | — | 0.0 | 0.0 | — | 0.0 | keep | keep |
| `DATE_OF_BIRTH` | 35 | 35 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `NATIONAL_ID_HU_TAX` | 0 | 6 | 0.0 | — | 0.0 | 0.0 | — | 0.0 | keep | keep |
| `NATIONAL_ID_HU_TAJ` | 0 | 1 | 0.0 | — | 0.0 | 0.0 | — | 0.0 | keep | keep |
| `ID_DOCUMENT` | 40 | 83 | 33.7 | 70.0 | 45.5 | 33.7 | 70.0 | 45.5 | 0.0 | 0.0 |
| `BANK_ACCOUNT` | 14 | 85 | 16.5 | 100.0 | 28.3 | 16.5 | 100.0 | 28.3 | 0.0 | 0.0 |
| `VEHICLE_PLATE` | 21 | 21 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| **all (micro)** | 196 | 344 | 52.3 | 91.8 | 66.7 | 54.4 | 93.9 | 68.9 | 0.0 | 0.0 |
