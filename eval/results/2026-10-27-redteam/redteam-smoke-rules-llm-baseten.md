# pii-guard evaluation

- commit: `7cde2fd8a061`, pii-guard 0.1.0
- detectors: `rules`, `llm`
- fixtures: `eval/fixtures/hu-smoke.jsonl` sha256 `3766a651708e8749`
- fixtures: `eval/fixtures/en-smoke.jsonl` sha256 `5983d84d8dfc9fe3`
- fixtures: `eval/fixtures/de-smoke.jsonl` sha256 `b623ca3b33af7ef7`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `de` | 10 | 40 | 40 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 | 0.0 | 100.0 | 100.0 | 1242.45 | 3227.84 |
| `en` | 10 | 34 | 34 | 97.1 | 97.1 | 97.1 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 3.3 | 0.0 | 100.0 | 100.0 | 1405.53 | 4855.98 |
| `hu` | 31 | 120 | 123 | 91.9 | 94.2 | 93.0 | 97.6 | 99.2 | 98.4 | 98.4 | 0.9 | 0.9 | 0.0 | 100.0 | 97.2 | 1934.16 | 3473.04 |
| **overall** | 51 | 194 | 197 | 94.4 | 95.9 | 95.1 | 98.5 | 99.5 | 99.0 | 98.7 | 0.6 | 1.2 | 0.0 | 100.0 | 98.3 | 1788.97 | 3691.94 |

## Per entity type: `de`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 13 | 13 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `ADDRESS` | 5 | 5 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `EMAIL` | 3 | 3 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `PHONE` | 5 | 5 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `DATE_OF_BIRTH` | 3 | 3 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `ID_DOCUMENT` | 6 | 6 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `BANK_ACCOUNT` | 2 | 2 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `ORGANIZATION` | 3 | 3 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | keep | keep |
| **all (micro)** | 40 | 40 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |

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
| `ID_DOCUMENT` | 17 | 18 | 83.3 | 88.2 | 85.7 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `BANK_ACCOUNT` | 12 | 12 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `COMPANY_ID_HU` | 4 | 5 | 80.0 | 100.0 | 88.9 | 80.0 | 100.0 | 88.9 | keep | keep |
| `ORGANIZATION` | 16 | 16 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | keep | keep |
| `PARCEL_NUMBER_HU` | 6 | 6 | 66.7 | 66.7 | 66.7 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `VEHICLE_PLATE` | 6 | 6 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| **all (micro)** | 194 | 197 | 94.4 | 95.9 | 95.1 | 98.5 | 99.5 | 99.0 | 0.6 | 1.2 |

## Re-identification red team

Attacker `meta-models/muse-spark-open-1026` (reasoning `low`), 4 decoys per candidate list. Re-id = masked values the attacker recovered; exposure = (leaked + recovered) / values.

| Context | Slice | Values | Leaked | Masked | Recovered | Re-id % | Partial % | Chance % | Exposure % | Failed |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `masked-only` | **all** | 173 | 1 | 172 | 2 | 1.2 | 2.3 | - | 1.7 | 0 |
| `masked-only` | lang `de` | 37 | 0 | 37 | 0 | 0.0 | 0.0 | - | 0.0 | 0 |
| `masked-only` | lang `en` | 30 | 0 | 30 | 0 | 0.0 | 0.0 | - | 0.0 | 0 |
| `masked-only` | lang `hu` | 106 | 1 | 105 | 2 | 1.9 | 3.8 | - | 2.8 | 0 |
| `masked-only` | `ADDRESS` | 22 | 0 | 22 | 0 | 0.0 | 4.5 | - | 0.0 | 0 |
| `masked-only` | `BANK_ACCOUNT` | 12 | 0 | 12 | 0 | 0.0 | 0.0 | - | 0.0 | 0 |
| `masked-only` | `DATE_OF_BIRTH` | 11 | 0 | 11 | 0 | 0.0 | 0.0 | - | 0.0 | 0 |
| `masked-only` | `EMAIL` | 12 | 0 | 12 | 0 | 0.0 | 0.0 | - | 0.0 | 0 |
| `masked-only` | `ID_DOCUMENT` | 17 | 0 | 17 | 1 | 5.9 | 0.0 | - | 5.9 | 0 |
| `masked-only` | `NATIONAL_ID_HU_TAJ` | 5 | 0 | 5 | 0 | 0.0 | 0.0 | - | 0.0 | 0 |
| `masked-only` | `NATIONAL_ID_HU_TAX` | 6 | 0 | 6 | 0 | 0.0 | 0.0 | - | 0.0 | 0 |
| `masked-only` | `PARCEL_NUMBER_HU` | 6 | 0 | 6 | 0 | 0.0 | 0.0 | - | 0.0 | 0 |
| `masked-only` | `PERSON` | 60 | 1 | 59 | 0 | 0.0 | 5.1 | - | 1.7 | 0 |
| `masked-only` | `PHONE` | 16 | 0 | 16 | 1 | 6.2 | 0.0 | - | 6.2 | 0 |
| `masked-only` | `VEHICLE_PLATE` | 6 | 0 | 6 | 0 | 0.0 | 0.0 | - | 0.0 | 0 |
| `decoys` | **all** | 173 | 1 | 172 | 69 | 40.1 | 4.7 | 20.3 | 40.5 | 0 |
| `decoys` | lang `de` | 37 | 0 | 37 | 19 | 51.4 | 0.0 | 20.0 | 51.4 | 0 |
| `decoys` | lang `en` | 30 | 0 | 30 | 11 | 36.7 | 10.0 | 20.2 | 36.7 | 0 |
| `decoys` | lang `hu` | 106 | 1 | 105 | 39 | 37.1 | 4.8 | 20.5 | 37.7 | 0 |
| `decoys` | `ADDRESS` | 22 | 0 | 22 | 5 | 22.7 | 18.2 | 20.0 | 22.7 | 0 |
| `decoys` | `BANK_ACCOUNT` | 12 | 0 | 12 | 4 | 33.3 | 16.7 | 20.0 | 33.3 | 0 |
| `decoys` | `DATE_OF_BIRTH` | 11 | 0 | 11 | 6 | 54.5 | 0.0 | 20.0 | 54.5 | 0 |
| `decoys` | `EMAIL` | 12 | 0 | 12 | 6 | 50.0 | 0.0 | 20.0 | 50.0 | 0 |
| `decoys` | `ID_DOCUMENT` | 17 | 0 | 17 | 9 | 52.9 | 0.0 | 20.0 | 52.9 | 0 |
| `decoys` | `NATIONAL_ID_HU_TAJ` | 5 | 0 | 5 | 3 | 60.0 | 0.0 | 25.0 | 60.0 | 0 |
| `decoys` | `NATIONAL_ID_HU_TAX` | 6 | 0 | 6 | 1 | 16.7 | 0.0 | 25.0 | 16.7 | 0 |
| `decoys` | `PARCEL_NUMBER_HU` | 6 | 0 | 6 | 2 | 33.3 | 0.0 | 20.0 | 33.3 | 0 |
| `decoys` | `PERSON` | 60 | 1 | 59 | 22 | 37.3 | 3.4 | 20.0 | 38.3 | 0 |
| `decoys` | `PHONE` | 16 | 0 | 16 | 8 | 50.0 | 0.0 | 20.0 | 50.0 | 0 |
| `decoys` | `VEHICLE_PLATE` | 6 | 0 | 6 | 3 | 50.0 | 0.0 | 20.0 | 50.0 | 0 |
