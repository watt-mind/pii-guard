# pii-guard evaluation

- commit: `7cde2fd8a061`, pii-guard 0.1.0
- detectors: `rules`, `llm`
- fixtures: `eval/fixtures/hu-smoke.jsonl` sha256 `3766a651708e8749`
- fixtures: `eval/fixtures/en-smoke.jsonl` sha256 `5983d84d8dfc9fe3`
- fixtures: `eval/fixtures/de-smoke.jsonl` sha256 `b623ca3b33af7ef7`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `de` | 10 | 40 | 42 | 95.2 | 100.0 | 97.6 | 95.2 | 100.0 | 97.6 | 98.2 | 0.0 | 0.0 | 5.1 | 100.0 | 100.0 | 1227.52 | 3736.71 |
| `en` | 10 | 34 | 34 | 97.1 | 97.1 | 97.1 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 3.3 | 0.0 | 100.0 | 100.0 | 1609.57 | 5088.67 |
| `hu` | 31 | 120 | 123 | 91.9 | 94.2 | 93.0 | 97.6 | 99.2 | 98.4 | 98.4 | 0.9 | 0.9 | 0.0 | 100.0 | 97.2 | 2006.60 | 4123.79 |
| **overall** | 51 | 194 | 199 | 93.5 | 95.9 | 94.7 | 97.5 | 99.5 | 98.5 | 98.3 | 0.6 | 1.2 | 1.1 | 100.0 | 98.3 | 1743.51 | 4123.79 |

## Per entity type: `de`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 13 | 13 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `ADDRESS` | 5 | 5 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `EMAIL` | 3 | 3 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `PHONE` | 5 | 5 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `DATE_OF_BIRTH` | 3 | 3 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `ID_DOCUMENT` | 6 | 8 | 75.0 | 100.0 | 85.7 | 75.0 | 100.0 | 85.7 | 0.0 | 0.0 |
| `BANK_ACCOUNT` | 2 | 2 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `ORGANIZATION` | 3 | 3 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | keep | keep |
| **all (micro)** | 40 | 42 | 95.2 | 100.0 | 97.6 | 95.2 | 100.0 | 97.6 | 0.0 | 0.0 |

## Per entity type: `en`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 10 | 10 | 90.0 | 90.0 | 90.0 | 100.0 | 100.0 | 100.0 | 0.0 | 10.0 |
| `ADDRESS` | 4 | 4 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `EMAIL` | 3 | 3 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `PHONE` | 4 | 4 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `DATE_OF_BIRTH` | 2 | 2 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `NATIONAL_ID_HU_TAX` | 1 | 1 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `ID_DOCUMENT` | 1 | 1 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `BANK_ACCOUNT` | 4 | 4 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `ORGANIZATION` | 4 | 4 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | keep | keep |
| `VEHICLE_PLATE` | 1 | 1 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| **all (micro)** | 34 | 34 | 97.1 | 97.1 | 97.1 | 100.0 | 100.0 | 100.0 | 0.0 | 3.3 |

## Per entity type: `hu`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 38 | 38 | 92.1 | 92.1 | 92.1 | 97.4 | 97.4 | 97.4 | 2.7 | 2.7 |
| `ADDRESS` | 13 | 13 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `EMAIL` | 6 | 6 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `PHONE` | 7 | 7 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `DATE_OF_BIRTH` | 6 | 7 | 85.7 | 100.0 | 92.3 | 85.7 | 100.0 | 92.3 | 0.0 | 0.0 |
| `NATIONAL_ID_HU_TAX` | 5 | 5 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `NATIONAL_ID_HU_TAJ` | 5 | 5 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `ID_DOCUMENT` | 10 | 11 | 72.7 | 80.0 | 76.2 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `BANK_ACCOUNT` | 6 | 6 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `COMPANY_ID_HU` | 4 | 5 | 80.0 | 100.0 | 88.9 | 80.0 | 100.0 | 88.9 | keep | keep |
| `ORGANIZATION` | 9 | 9 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | keep | keep |
| `PARCEL_NUMBER_HU` | 6 | 6 | 66.7 | 66.7 | 66.7 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `VEHICLE_PLATE` | 5 | 5 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| **all (micro)** | 120 | 123 | 91.9 | 94.2 | 93.0 | 97.6 | 99.2 | 98.4 | 0.9 | 0.9 |

## Per entity type: overall

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 61 | 61 | 93.4 | 93.4 | 93.4 | 98.4 | 98.4 | 98.4 | 1.7 | 3.3 |
| `ADDRESS` | 22 | 22 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `EMAIL` | 12 | 12 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `PHONE` | 16 | 16 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `DATE_OF_BIRTH` | 11 | 12 | 91.7 | 100.0 | 95.7 | 91.7 | 100.0 | 95.7 | 0.0 | 0.0 |
| `NATIONAL_ID_HU_TAX` | 6 | 6 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `NATIONAL_ID_HU_TAJ` | 5 | 5 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `ID_DOCUMENT` | 17 | 20 | 75.0 | 88.2 | 81.1 | 90.0 | 100.0 | 94.7 | 0.0 | 0.0 |
| `BANK_ACCOUNT` | 12 | 12 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `COMPANY_ID_HU` | 4 | 5 | 80.0 | 100.0 | 88.9 | 80.0 | 100.0 | 88.9 | keep | keep |
| `ORGANIZATION` | 16 | 16 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | keep | keep |
| `PARCEL_NUMBER_HU` | 6 | 6 | 66.7 | 66.7 | 66.7 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `VEHICLE_PLATE` | 6 | 6 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| **all (micro)** | 194 | 199 | 93.5 | 95.9 | 94.7 | 97.5 | 99.5 | 98.5 | 0.6 | 1.2 |

## Re-identification red team

Attacker `muse-spark-1.3` (reasoning `low`), 4 decoys per candidate list. Re-id = masked values the attacker recovered; exposure = (leaked + recovered) / values.

| Context | Slice | Values | Leaked | Masked | Recovered | Re-id % | Partial % | Chance % | Exposure % | Failed |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `masked-only` | **all** | 173 | 1 | 172 | 0 | 0.0 | 2.9 | - | 0.6 | 0 |
| `masked-only` | lang `de` | 37 | 0 | 37 | 0 | 0.0 | 2.7 | - | 0.0 | 0 |
| `masked-only` | lang `en` | 30 | 0 | 30 | 0 | 0.0 | 0.0 | - | 0.0 | 0 |
| `masked-only` | lang `hu` | 106 | 1 | 105 | 0 | 0.0 | 3.8 | - | 0.9 | 0 |
| `masked-only` | `ADDRESS` | 22 | 0 | 22 | 0 | 0.0 | 4.5 | - | 0.0 | 0 |
| `masked-only` | `BANK_ACCOUNT` | 12 | 0 | 12 | 0 | 0.0 | 0.0 | - | 0.0 | 0 |
| `masked-only` | `DATE_OF_BIRTH` | 11 | 0 | 11 | 0 | 0.0 | 0.0 | - | 0.0 | 0 |
| `masked-only` | `EMAIL` | 12 | 0 | 12 | 0 | 0.0 | 0.0 | - | 0.0 | 0 |
| `masked-only` | `ID_DOCUMENT` | 17 | 0 | 17 | 0 | 0.0 | 0.0 | - | 0.0 | 0 |
| `masked-only` | `NATIONAL_ID_HU_TAJ` | 5 | 0 | 5 | 0 | 0.0 | 0.0 | - | 0.0 | 0 |
| `masked-only` | `NATIONAL_ID_HU_TAX` | 6 | 0 | 6 | 0 | 0.0 | 0.0 | - | 0.0 | 0 |
| `masked-only` | `PARCEL_NUMBER_HU` | 6 | 0 | 6 | 0 | 0.0 | 0.0 | - | 0.0 | 0 |
| `masked-only` | `PERSON` | 60 | 1 | 59 | 0 | 0.0 | 5.1 | - | 1.7 | 0 |
| `masked-only` | `PHONE` | 16 | 0 | 16 | 0 | 0.0 | 6.2 | - | 0.0 | 0 |
| `masked-only` | `VEHICLE_PLATE` | 6 | 0 | 6 | 0 | 0.0 | 0.0 | - | 0.0 | 0 |
| `decoys` | **all** | 173 | 1 | 172 | 56 | 41.8 | 4.5 | 20.3 | 42.2 | 38 |
| `decoys` | lang `de` | 37 | 0 | 37 | 15 | 44.1 | 0.0 | 20.0 | 44.1 | 3 |
| `decoys` | lang `en` | 30 | 0 | 30 | 13 | 43.3 | 13.3 | 20.2 | 43.3 | 0 |
| `decoys` | lang `hu` | 106 | 1 | 105 | 28 | 40.0 | 2.9 | 20.4 | 40.8 | 35 |
| `decoys` | `ADDRESS` | 22 | 0 | 22 | 3 | 17.6 | 29.4 | 20.0 | 17.6 | 5 |
| `decoys` | `BANK_ACCOUNT` | 12 | 0 | 12 | 5 | 55.6 | 11.1 | 20.0 | 55.6 | 3 |
| `decoys` | `DATE_OF_BIRTH` | 11 | 0 | 11 | 3 | 37.5 | 0.0 | 20.0 | 37.5 | 3 |
| `decoys` | `EMAIL` | 12 | 0 | 12 | 7 | 63.6 | 0.0 | 20.0 | 63.6 | 1 |
| `decoys` | `ID_DOCUMENT` | 17 | 0 | 17 | 3 | 27.3 | 0.0 | 20.0 | 27.3 | 6 |
| `decoys` | `NATIONAL_ID_HU_TAJ` | 5 | 0 | 5 | 1 | 25.0 | 0.0 | 25.0 | 25.0 | 1 |
| `decoys` | `NATIONAL_ID_HU_TAX` | 6 | 0 | 6 | 0 | 0.0 | 0.0 | 25.0 | 0.0 | 3 |
| `decoys` | `PARCEL_NUMBER_HU` | 6 | 0 | 6 | 3 | 60.0 | 0.0 | 20.0 | 60.0 | 1 |
| `decoys` | `PERSON` | 60 | 1 | 59 | 21 | 44.7 | 0.0 | 20.0 | 45.8 | 12 |
| `decoys` | `PHONE` | 16 | 0 | 16 | 8 | 50.0 | 0.0 | 20.0 | 50.0 | 0 |
| `decoys` | `VEHICLE_PLATE` | 6 | 0 | 6 | 2 | 66.7 | 0.0 | 20.0 | 66.7 | 3 |
