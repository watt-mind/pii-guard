# pii-guard evaluation

- commit: `477196a3427c (dirty)`, pii-guard 0.1.0
- detectors: `rules`, `ner`
- fixtures: `eval/fixtures/hu-synth-sample.jsonl` sha256 `ed547228ddc329bb`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `hu` | 20 | 271 | 273 | 93.4 | 94.1 | 93.8 | 93.8 | 94.5 | 94.1 | 83.8 | 0.0 | 0.0 | 0.8 | 100.0 | 100.0 | 23.83 | 54.18 |
| **overall** | 20 | 271 | 273 | 93.4 | 94.1 | 93.8 | 93.8 | 94.5 | 94.1 | 83.8 | 0.0 | 0.0 | 0.8 | 100.0 | 100.0 | 23.83 | 54.18 |

## Per entity type: `hu`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 107 | 107 | 99.1 | 99.1 | 99.1 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `ADDRESS` | 39 | 45 | 86.7 | 100.0 | 92.9 | 86.7 | 100.0 | 92.9 | 0.0 | 0.0 |
| `EMAIL` | 9 | 9 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `PHONE` | 14 | 14 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `DATE_OF_BIRTH` | 17 | 17 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `NATIONAL_ID_HU_TAX` | 8 | 18 | 44.4 | 100.0 | 61.5 | 44.4 | 100.0 | 61.5 | 0.0 | 0.0 |
| `NATIONAL_ID_HU_TAJ` | 5 | 6 | 83.3 | 100.0 | 90.9 | 83.3 | 100.0 | 90.9 | 0.0 | 0.0 |
| `ID_DOCUMENT` | 8 | 8 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `BANK_ACCOUNT` | 17 | 17 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `COMPANY_ID_HU` | 10 | 0 | — | 0.0 | 0.0 | — | 0.0 | 0.0 | keep | keep |
| `ORGANIZATION` | 22 | 22 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | keep | keep |
| `PARCEL_NUMBER_HU` | 7 | 2 | 100.0 | 28.6 | 44.4 | 100.0 | 28.6 | 44.4 | 0.0 | 0.0 |
| `VEHICLE_PLATE` | 8 | 8 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| **all (micro)** | 271 | 273 | 93.4 | 94.1 | 93.8 | 93.8 | 94.5 | 94.1 | 0.0 | 0.0 |
