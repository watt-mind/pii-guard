# pii-guard evaluation

- commit: `c611f9935cbe (dirty)`, pii-guard 0.1.0
- detectors: `rules`, `ner`
- fixtures: `eval/generated/distill-s11/hu-distill-dev.jsonl` sha256 `cf04e3fb4e479738`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `hu` | 368 | 3324 | 3229 | 97.9 | 95.1 | 96.4 | 99.1 | 96.3 | 97.7 | 84.3 | 5.2 | 0.0 | 0.5 | 100.0 | 94.6 | 47.63 | 119.44 |
| **overall** | 368 | 3324 | 3229 | 97.9 | 95.1 | 96.4 | 99.1 | 96.3 | 97.7 | 84.3 | 5.2 | 0.0 | 0.5 | 100.0 | 94.6 | 47.63 | 119.44 |

## Per entity type: `hu`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 1487 | 1501 | 96.3 | 97.2 | 96.8 | 98.9 | 100.0 | 99.5 | 0.0 | 0.0 |
| `ADDRESS` | 444 | 444 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `EMAIL` | 194 | 194 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `PHONE` | 326 | 327 | 99.7 | 100.0 | 99.8 | 99.7 | 100.0 | 99.8 | 0.0 | 0.0 |
| `DATE_OF_BIRTH` | 161 | 161 | 99.4 | 99.4 | 99.4 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `NATIONAL_ID_HU_TAX` | 73 | 73 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `NATIONAL_ID_HU_TAJ` | 88 | 88 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `ID_DOCUMENT` | 70 | 0 | - | 0.0 | 0.0 | - | 0.0 | 0.0 | 100.0 | 0.0 |
| `BANK_ACCOUNT` | 122 | 122 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `COMPANY_ID_HU` | 91 | 90 | 100.0 | 98.9 | 99.4 | 100.0 | 98.9 | 99.4 | keep | keep |
| `ORGANIZATION` | 170 | 182 | 93.4 | 100.0 | 96.6 | 93.4 | 100.0 | 96.6 | keep | keep |
| `PARCEL_NUMBER_HU` | 51 | 0 | - | 0.0 | 0.0 | - | 0.0 | 0.0 | 100.0 | 0.0 |
| `VEHICLE_PLATE` | 47 | 47 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| **all (micro)** | 3324 | 3229 | 97.9 | 95.1 | 96.4 | 99.1 | 96.3 | 97.7 | 5.2 | 0.0 |
