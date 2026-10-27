# pii-guard evaluation

- commit: `c611f9935cbe (dirty)`, pii-guard 0.1.0
- detectors: `rules`
- fixtures: `eval/generated/distill-s11/hu-distill-dev.jsonl` sha256 `cf04e3fb4e479738`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `hu` | 368 | 3324 | 1385 | 67.9 | 28.3 | 39.9 | 99.9 | 41.6 | 58.8 | 61.5 | 49.1 | 20.6 | 0.0 | 100.0 | 51.6 | 0.67 | 10.54 |
| **overall** | 368 | 3324 | 1385 | 67.9 | 28.3 | 39.9 | 99.9 | 41.6 | 58.8 | 61.5 | 49.1 | 20.6 | 0.0 | 100.0 | 51.6 | 0.67 | 10.54 |

## Per entity type: `hu`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 1487 | 0 | - | 0.0 | 0.0 | - | 0.0 | 0.0 | 100.0 | 0.0 |
| `ADDRESS` | 444 | 444 | 0.0 | 0.0 | 0.0 | 100.0 | 100.0 | 100.0 | 0.0 | 99.0 |
| `EMAIL` | 194 | 194 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 31.0 |
| `PHONE` | 326 | 327 | 99.7 | 100.0 | 99.8 | 99.7 | 100.0 | 99.8 | 0.0 | 0.0 |
| `DATE_OF_BIRTH` | 161 | 0 | - | 0.0 | 0.0 | - | 0.0 | 0.0 | 100.0 | 0.0 |
| `NATIONAL_ID_HU_TAX` | 73 | 73 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `NATIONAL_ID_HU_TAJ` | 88 | 88 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `ID_DOCUMENT` | 70 | 0 | - | 0.0 | 0.0 | - | 0.0 | 0.0 | 100.0 | 0.0 |
| `BANK_ACCOUNT` | 122 | 122 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `COMPANY_ID_HU` | 91 | 90 | 100.0 | 98.9 | 99.4 | 100.0 | 98.9 | 99.4 | keep | keep |
| `ORGANIZATION` | 170 | 0 | - | 0.0 | 0.0 | - | 0.0 | 0.0 | keep | keep |
| `PARCEL_NUMBER_HU` | 51 | 0 | - | 0.0 | 0.0 | - | 0.0 | 0.0 | 100.0 | 0.0 |
| `VEHICLE_PLATE` | 47 | 47 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| **all (micro)** | 3324 | 1385 | 67.9 | 28.3 | 39.9 | 99.9 | 41.6 | 58.8 | 49.1 | 20.6 |
