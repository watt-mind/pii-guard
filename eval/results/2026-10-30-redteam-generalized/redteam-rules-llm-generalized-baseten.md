# pii-guard evaluation

- commit: `a48a2c8980d4 (dirty)`, pii-guard 0.1.0
- detectors: `rules`, `llm`
- fixtures: `eval/fixtures/hu-smoke.jsonl` sha256 `3766a651708e8749`
- fixtures: `eval/fixtures/en-smoke.jsonl` sha256 `5983d84d8dfc9fe3`
- fixtures: `eval/fixtures/de-smoke.jsonl` sha256 `b623ca3b33af7ef7`
- fixtures: `eval/fixtures/hu-synth-sample.jsonl` sha256 `ed547228ddc329bb`
- fixtures: `eval/fixtures/en-synth-sample.jsonl` sha256 `2c7ab3d12880065d`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `de` | 10 | 40 | 40 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 | 0.0 | 100.0 | 100.0 | 1285.04 | 2370.91 |
| `en` | 20 | 154 | 149 | 98.0 | 94.8 | 96.4 | 98.7 | 95.5 | 97.0 | 98.9 | 4.5 | 8.2 | 0.7 | 100.0 | 95.5 | 1735.12 | 2257.02 |
| `hu` | 51 | 391 | 393 | 96.2 | 96.7 | 96.4 | 99.2 | 99.5 | 99.4 | 99.4 | 0.4 | 0.4 | 0.0 | 100.0 | 98.9 | 1820.39 | 2875.44 |
| **overall** | 81 | 585 | 582 | 96.9 | 96.4 | 96.7 | 99.1 | 98.5 | 98.8 | 99.3 | 1.4 | 2.3 | 0.2 | 100.0 | 98.1 | 1799.54 | 2722.73 |

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
| `PERSON` | 69 | 62 | 98.4 | 88.4 | 93.1 | 100.0 | 89.9 | 94.7 | 12.2 | 14.6 |
| `ADDRESS` | 21 | 22 | 95.5 | 100.0 | 97.7 | 95.5 | 100.0 | 97.7 | 0.0 | 14.3 |
| `EMAIL` | 10 | 10 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `PHONE` | 12 | 12 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `DATE_OF_BIRTH` | 8 | 8 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `NATIONAL_ID_HU_TAX` | 1 | 1 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `ID_DOCUMENT` | 4 | 4 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `BANK_ACCOUNT` | 11 | 11 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `ORGANIZATION` | 14 | 15 | 93.3 | 100.0 | 96.6 | 93.3 | 100.0 | 96.6 | keep | keep |
| `VEHICLE_PLATE` | 4 | 4 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| **all (micro)** | 154 | 149 | 98.0 | 94.8 | 96.4 | 98.7 | 95.5 | 97.0 | 4.5 | 8.2 |

## Per entity type: `hu`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 145 | 145 | 96.6 | 96.6 | 96.6 | 99.3 | 99.3 | 99.3 | 1.1 | 1.1 |
| `ADDRESS` | 52 | 52 | 96.2 | 96.2 | 96.2 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `EMAIL` | 15 | 15 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `PHONE` | 21 | 21 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `DATE_OF_BIRTH` | 23 | 24 | 95.8 | 100.0 | 97.9 | 95.8 | 100.0 | 97.9 | 0.0 | 0.0 |
| `NATIONAL_ID_HU_TAX` | 13 | 13 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `NATIONAL_ID_HU_TAJ` | 10 | 10 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `ID_DOCUMENT` | 18 | 19 | 84.2 | 88.9 | 86.5 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `BANK_ACCOUNT` | 23 | 23 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `COMPANY_ID_HU` | 14 | 15 | 93.3 | 100.0 | 96.6 | 93.3 | 100.0 | 96.6 | keep | keep |
| `ORGANIZATION` | 31 | 30 | 100.0 | 96.8 | 98.4 | 100.0 | 96.8 | 98.4 | keep | keep |
| `PARCEL_NUMBER_HU` | 13 | 13 | 76.9 | 76.9 | 76.9 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `VEHICLE_PLATE` | 13 | 13 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| **all (micro)** | 391 | 393 | 96.2 | 96.7 | 96.4 | 99.2 | 99.5 | 99.4 | 0.4 | 0.4 |

## Per entity type: overall

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 227 | 220 | 97.3 | 94.3 | 95.7 | 99.5 | 96.5 | 98.0 | 4.1 | 4.8 |
| `ADDRESS` | 78 | 79 | 96.2 | 97.4 | 96.8 | 98.7 | 100.0 | 99.4 | 0.0 | 3.8 |
| `EMAIL` | 28 | 28 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `PHONE` | 38 | 38 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `DATE_OF_BIRTH` | 34 | 35 | 97.1 | 100.0 | 98.6 | 97.1 | 100.0 | 98.6 | 0.0 | 0.0 |
| `NATIONAL_ID_HU_TAX` | 14 | 14 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `NATIONAL_ID_HU_TAJ` | 10 | 10 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `ID_DOCUMENT` | 28 | 29 | 89.7 | 92.9 | 91.2 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `BANK_ACCOUNT` | 36 | 36 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `COMPANY_ID_HU` | 14 | 15 | 93.3 | 100.0 | 96.6 | 93.3 | 100.0 | 96.6 | keep | keep |
| `ORGANIZATION` | 48 | 48 | 97.9 | 97.9 | 97.9 | 97.9 | 97.9 | 97.9 | keep | keep |
| `PARCEL_NUMBER_HU` | 13 | 13 | 76.9 | 76.9 | 76.9 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `VEHICLE_PLATE` | 17 | 17 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| **all (micro)** | 585 | 582 | 96.9 | 96.4 | 96.7 | 99.1 | 98.5 | 98.8 | 1.4 | 2.3 |

## Re-identification red team

Attacker `meta-models/muse-spark-open-1026` (reasoning `low`), 4 decoys per candidate list. Re-id = masked values the attacker recovered; exposure = (leaked + recovered) / values.

| Context | Slice | Values | Leaked | Masked | Recovered | Re-id % | Partial % | Chance % | Exposure % | Failed |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `decoys` | **all** | 426 | 6 | 420 | 165 | 39.3 | 5.0 | 20.0 | 40.1 | 0 |
| `decoys` | lang `de` | 37 | 0 | 37 | 15 | 40.5 | 0.0 | 20.0 | 40.5 | 0 |
| `decoys` | lang `en` | 110 | 5 | 105 | 49 | 46.7 | 5.7 | 20.0 | 49.1 | 0 |
| `decoys` | lang `hu` | 279 | 1 | 278 | 101 | 36.3 | 5.4 | 20.0 | 36.6 | 0 |
| `decoys` | `ADDRESS` | 78 | 0 | 78 | 20 | 25.6 | 17.9 | 20.0 | 25.6 | 0 |
| `decoys` | `BANK_ACCOUNT` | 31 | 0 | 31 | 11 | 35.5 | 0.0 | 20.0 | 35.5 | 0 |
| `decoys` | `DATE_OF_BIRTH` | 34 | 0 | 34 | 11 | 32.4 | 2.9 | 20.0 | 32.4 | 0 |
| `decoys` | `EMAIL` | 25 | 0 | 25 | 19 | 76.0 | 0.0 | 20.0 | 76.0 | 0 |
| `decoys` | `ID_DOCUMENT` | 28 | 0 | 28 | 13 | 46.4 | 0.0 | 20.0 | 46.4 | 0 |
| `decoys` | `NATIONAL_ID_HU_TAJ` | 10 | 0 | 10 | 1 | 10.0 | 0.0 | 20.0 | 10.0 | 0 |
| `decoys` | `NATIONAL_ID_HU_TAX` | 14 | 0 | 14 | 4 | 28.6 | 0.0 | 20.0 | 28.6 | 0 |
| `decoys` | `PARCEL_NUMBER_HU` | 13 | 0 | 13 | 3 | 23.1 | 0.0 | 20.0 | 23.1 | 0 |
| `decoys` | `PERSON` | 146 | 6 | 140 | 67 | 47.9 | 2.9 | 20.0 | 50.0 | 0 |
| `decoys` | `PHONE` | 34 | 0 | 34 | 13 | 38.2 | 5.9 | 20.0 | 38.2 | 0 |
| `decoys` | `VEHICLE_PLATE` | 13 | 0 | 13 | 3 | 23.1 | 0.0 | 20.0 | 23.1 | 0 |
| `decoys+generalized` | **all** | 426 | 6 | 420 | 152 | 36.5 | 4.3 | 20.0 | 37.4 | 4 |
| `decoys+generalized` | lang `de` | 37 | 0 | 37 | 12 | 32.4 | 0.0 | 20.0 | 32.4 | 0 |
| `decoys+generalized` | lang `en` | 110 | 5 | 105 | 49 | 46.7 | 4.8 | 20.0 | 49.1 | 0 |
| `decoys+generalized` | lang `hu` | 279 | 1 | 278 | 91 | 33.2 | 4.7 | 20.0 | 33.5 | 4 |
| `decoys+generalized` | `ADDRESS` | 78 | 0 | 78 | 26 | 33.3 | 16.7 | 20.0 | 33.3 | 0 |
| `decoys+generalized` | `BANK_ACCOUNT` | 31 | 0 | 31 | 12 | 38.7 | 0.0 | 20.0 | 38.7 | 0 |
| `decoys+generalized` | `DATE_OF_BIRTH` | 34 | 0 | 34 | 8 | 23.5 | 2.9 | 20.0 | 23.5 | 0 |
| `decoys+generalized` | `EMAIL` | 25 | 0 | 25 | 19 | 76.0 | 0.0 | 20.0 | 76.0 | 0 |
| `decoys+generalized` | `ID_DOCUMENT` | 28 | 0 | 28 | 9 | 36.0 | 0.0 | 20.0 | 36.0 | 3 |
| `decoys+generalized` | `NATIONAL_ID_HU_TAJ` | 10 | 0 | 10 | 1 | 10.0 | 0.0 | 20.0 | 10.0 | 0 |
| `decoys+generalized` | `NATIONAL_ID_HU_TAX` | 14 | 0 | 14 | 3 | 21.4 | 0.0 | 20.0 | 21.4 | 0 |
| `decoys+generalized` | `PARCEL_NUMBER_HU` | 13 | 0 | 13 | 1 | 7.7 | 0.0 | 20.0 | 7.7 | 0 |
| `decoys+generalized` | `PERSON` | 146 | 6 | 140 | 60 | 43.2 | 2.2 | 20.0 | 45.5 | 1 |
| `decoys+generalized` | `PHONE` | 34 | 0 | 34 | 11 | 32.4 | 2.9 | 20.0 | 32.4 | 0 |
| `decoys+generalized` | `VEHICLE_PLATE` | 13 | 0 | 13 | 2 | 15.4 | 0.0 | 20.0 | 15.4 | 0 |
| `decoys-isolated` | **all** | 426 | 6 | 420 | 152 | 36.2 | 5.0 | 20.0 | 37.1 | 0 |
| `decoys-isolated` | lang `de` | 37 | 0 | 37 | 13 | 35.1 | 0.0 | 20.0 | 35.1 | 0 |
| `decoys-isolated` | lang `en` | 110 | 5 | 105 | 48 | 45.7 | 5.7 | 20.0 | 48.2 | 0 |
| `decoys-isolated` | lang `hu` | 279 | 1 | 278 | 91 | 32.7 | 5.4 | 20.0 | 33.0 | 0 |
| `decoys-isolated` | `ADDRESS` | 78 | 0 | 78 | 21 | 26.9 | 16.7 | 20.0 | 26.9 | 0 |
| `decoys-isolated` | `BANK_ACCOUNT` | 31 | 0 | 31 | 11 | 35.5 | 0.0 | 20.0 | 35.5 | 0 |
| `decoys-isolated` | `DATE_OF_BIRTH` | 34 | 0 | 34 | 8 | 23.5 | 2.9 | 20.0 | 23.5 | 0 |
| `decoys-isolated` | `EMAIL` | 25 | 0 | 25 | 16 | 64.0 | 0.0 | 20.0 | 64.0 | 0 |
| `decoys-isolated` | `ID_DOCUMENT` | 28 | 0 | 28 | 10 | 35.7 | 3.6 | 20.0 | 35.7 | 0 |
| `decoys-isolated` | `NATIONAL_ID_HU_TAJ` | 10 | 0 | 10 | 0 | 0.0 | 0.0 | 20.0 | 0.0 | 0 |
| `decoys-isolated` | `NATIONAL_ID_HU_TAX` | 14 | 0 | 14 | 3 | 21.4 | 0.0 | 20.0 | 21.4 | 0 |
| `decoys-isolated` | `PARCEL_NUMBER_HU` | 13 | 0 | 13 | 1 | 7.7 | 0.0 | 20.0 | 7.7 | 0 |
| `decoys-isolated` | `PERSON` | 146 | 6 | 140 | 69 | 49.3 | 3.6 | 20.0 | 51.4 | 0 |
| `decoys-isolated` | `PHONE` | 34 | 0 | 34 | 10 | 29.4 | 2.9 | 20.0 | 29.4 | 0 |
| `decoys-isolated` | `VEHICLE_PLATE` | 13 | 0 | 13 | 3 | 23.1 | 0.0 | 20.0 | 23.1 | 0 |
