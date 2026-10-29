# pii-guard evaluation

- commit: `f97eec600803`, pii-guard 0.1.0
- detectors: `rules`
- fixtures: `eval/fixtures/hu-smoke.jsonl` sha256 `3766a651708e8749`
- fixtures: `eval/fixtures/en-smoke.jsonl` sha256 `5983d84d8dfc9fe3`
- fixtures: `eval/fixtures/de-smoke.jsonl` sha256 `b623ca3b33af7ef7`
- fixtures: `eval/fixtures/hu-synth-sample.jsonl` sha256 `ed547228ddc329bb`
- fixtures: `eval/fixtures/en-synth-sample.jsonl` sha256 `2c7ab3d12880065d`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `de` | 10 | 40 | 22 | 90.9 | 50.0 | 64.5 | 100.0 | 52.5 | 68.9 | 62.5 | 43.2 | 8.1 | 0.0 | 100.0 | 54.1 | 0.17 | 0.24 |
| `en` | 20 | 154 | 61 | 68.9 | 27.3 | 39.1 | 100.0 | 39.6 | 56.7 | 69.5 | 46.4 | 21.8 | 0.0 | 100.0 | 53.6 | 0.20 | 2.02 |
| `hu` | 51 | 391 | 192 | 100.0 | 49.1 | 65.9 | 100.0 | 49.1 | 65.9 | 76.9 | 41.2 | 2.2 | 0.0 | 100.0 | 59.0 | 0.24 | 2.25 |
| **overall** | 81 | 585 | 275 | 92.4 | 43.4 | 59.1 | 100.0 | 46.8 | 63.8 | 76.8 | 42.7 | 7.7 | 0.0 | 100.0 | 57.2 | 0.20 | 2.03 |

## Per entity type: `de`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 13 | 0 | - | 0.0 | 0.0 | - | 0.0 | 0.0 | 100.0 | 0.0 |
| `ADDRESS` | 5 | 6 | 66.7 | 80.0 | 72.7 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `EMAIL` | 3 | 3 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 100.0 |
| `PHONE` | 5 | 5 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `DATE_OF_BIRTH` | 3 | 0 | - | 0.0 | 0.0 | - | 0.0 | 0.0 | 100.0 | 0.0 |
| `ID_DOCUMENT` | 6 | 6 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `BANK_ACCOUNT` | 2 | 2 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `ORGANIZATION` | 3 | 0 | - | 0.0 | 0.0 | - | 0.0 | 0.0 | keep | keep |
| **all (micro)** | 40 | 22 | 90.9 | 50.0 | 64.5 | 100.0 | 52.5 | 68.9 | 43.2 | 8.1 |

## Per entity type: `en`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 69 | 0 | - | 0.0 | 0.0 | - | 0.0 | 0.0 | 100.0 | 0.0 |
| `ADDRESS` | 21 | 19 | 0.0 | 0.0 | 0.0 | 100.0 | 90.5 | 95.0 | 9.5 | 90.5 |
| `EMAIL` | 10 | 10 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 55.6 |
| `PHONE` | 12 | 12 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `DATE_OF_BIRTH` | 8 | 0 | - | 0.0 | 0.0 | - | 0.0 | 0.0 | 100.0 | 0.0 |
| `NATIONAL_ID_HU_TAX` | 1 | 1 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `ID_DOCUMENT` | 4 | 4 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `BANK_ACCOUNT` | 11 | 11 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `ORGANIZATION` | 14 | 0 | - | 0.0 | 0.0 | - | 0.0 | 0.0 | keep | keep |
| `VEHICLE_PLATE` | 4 | 4 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| **all (micro)** | 154 | 61 | 68.9 | 27.3 | 39.1 | 100.0 | 39.6 | 56.7 | 46.4 | 21.8 |

## Per entity type: `hu`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 145 | 0 | - | 0.0 | 0.0 | - | 0.0 | 0.0 | 100.0 | 0.0 |
| `ADDRESS` | 52 | 52 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `EMAIL` | 15 | 15 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 38.5 |
| `PHONE` | 21 | 21 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `DATE_OF_BIRTH` | 23 | 0 | - | 0.0 | 0.0 | - | 0.0 | 0.0 | 100.0 | 0.0 |
| `NATIONAL_ID_HU_TAX` | 13 | 13 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `NATIONAL_ID_HU_TAJ` | 10 | 10 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `ID_DOCUMENT` | 18 | 18 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 5.6 |
| `BANK_ACCOUNT` | 23 | 23 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `COMPANY_ID_HU` | 14 | 14 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | keep | keep |
| `ORGANIZATION` | 31 | 0 | - | 0.0 | 0.0 | - | 0.0 | 0.0 | keep | keep |
| `PARCEL_NUMBER_HU` | 13 | 13 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `VEHICLE_PLATE` | 13 | 13 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| **all (micro)** | 391 | 192 | 100.0 | 49.1 | 65.9 | 100.0 | 49.1 | 65.9 | 41.2 | 2.2 |

## Per entity type: overall

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 227 | 0 | - | 0.0 | 0.0 | - | 0.0 | 0.0 | 100.0 | 0.0 |
| `ADDRESS` | 78 | 77 | 72.7 | 71.8 | 72.3 | 100.0 | 97.4 | 98.7 | 2.6 | 24.4 |
| `EMAIL` | 28 | 28 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 52.0 |
| `PHONE` | 38 | 38 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `DATE_OF_BIRTH` | 34 | 0 | - | 0.0 | 0.0 | - | 0.0 | 0.0 | 100.0 | 0.0 |
| `NATIONAL_ID_HU_TAX` | 14 | 14 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `NATIONAL_ID_HU_TAJ` | 10 | 10 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `ID_DOCUMENT` | 28 | 28 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 3.6 |
| `BANK_ACCOUNT` | 36 | 36 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `COMPANY_ID_HU` | 14 | 14 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | keep | keep |
| `ORGANIZATION` | 48 | 0 | - | 0.0 | 0.0 | - | 0.0 | 0.0 | keep | keep |
| `PARCEL_NUMBER_HU` | 13 | 13 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `VEHICLE_PLATE` | 17 | 17 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| **all (micro)** | 585 | 275 | 92.4 | 43.4 | 59.1 | 100.0 | 46.8 | 63.8 | 42.7 | 7.7 |

## Re-identification red team

Attacker `meta-models/muse-spark-open-1026` (reasoning `low`), 4 decoys per candidate list. Re-id = masked values the attacker recovered; exposure = (leaked + recovered) / values.

| Context | Slice | Values | Leaked | Masked | Recovered | Re-id % | Partial % | Chance % | Exposure % | Failed |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `masked-only` | **all** | 426 | 182 | 244 | 4 | 1.6 | 11.9 | - | 43.7 | 0 |
| `masked-only` | lang `de` | 37 | 16 | 21 | 0 | 0.0 | 14.3 | - | 43.2 | 0 |
| `masked-only` | lang `en` | 110 | 51 | 59 | 0 | 0.0 | 10.2 | - | 46.4 | 0 |
| `masked-only` | lang `hu` | 279 | 115 | 164 | 4 | 2.4 | 12.2 | - | 42.7 | 0 |
| `masked-only` | `ADDRESS` | 78 | 2 | 76 | 0 | 0.0 | 21.1 | - | 2.6 | 0 |
| `masked-only` | `BANK_ACCOUNT` | 31 | 0 | 31 | 0 | 0.0 | 3.2 | - | 0.0 | 0 |
| `masked-only` | `DATE_OF_BIRTH` | 34 | 34 | 0 | 0 | - | - | - | 100.0 | 0 |
| `masked-only` | `EMAIL` | 25 | 0 | 25 | 0 | 0.0 | 44.0 | - | 0.0 | 0 |
| `masked-only` | `ID_DOCUMENT` | 28 | 0 | 28 | 1 | 3.6 | 0.0 | - | 3.6 | 0 |
| `masked-only` | `NATIONAL_ID_HU_TAJ` | 10 | 0 | 10 | 2 | 20.0 | 0.0 | - | 20.0 | 0 |
| `masked-only` | `NATIONAL_ID_HU_TAX` | 14 | 0 | 14 | 1 | 7.1 | 0.0 | - | 7.1 | 0 |
| `masked-only` | `PARCEL_NUMBER_HU` | 13 | 0 | 13 | 0 | 0.0 | 0.0 | - | 0.0 | 0 |
| `masked-only` | `PERSON` | 146 | 146 | 0 | 0 | - | - | - | 100.0 | 0 |
| `masked-only` | `PHONE` | 34 | 0 | 34 | 0 | 0.0 | 2.9 | - | 0.0 | 0 |
| `masked-only` | `VEHICLE_PLATE` | 13 | 0 | 13 | 0 | 0.0 | 0.0 | - | 0.0 | 0 |
| `decoys` | **all** | 426 | 182 | 244 | 103 | 42.2 | 3.3 | 20.0 | 66.9 | 0 |
| `decoys` | lang `de` | 37 | 16 | 21 | 12 | 57.1 | 0.0 | 20.0 | 75.7 | 0 |
| `decoys` | lang `en` | 110 | 51 | 59 | 39 | 66.1 | 1.7 | 20.0 | 81.8 | 0 |
| `decoys` | lang `hu` | 279 | 115 | 164 | 52 | 31.7 | 4.3 | 20.0 | 59.9 | 0 |
| `decoys` | `ADDRESS` | 78 | 2 | 76 | 35 | 46.1 | 9.2 | 20.0 | 47.4 | 0 |
| `decoys` | `BANK_ACCOUNT` | 31 | 0 | 31 | 10 | 32.3 | 0.0 | 20.0 | 32.3 | 0 |
| `decoys` | `DATE_OF_BIRTH` | 34 | 34 | 0 | 0 | - | - | - | 100.0 | 0 |
| `decoys` | `EMAIL` | 25 | 0 | 25 | 23 | 92.0 | 0.0 | 20.0 | 92.0 | 0 |
| `decoys` | `ID_DOCUMENT` | 28 | 0 | 28 | 13 | 46.4 | 0.0 | 20.0 | 46.4 | 0 |
| `decoys` | `NATIONAL_ID_HU_TAJ` | 10 | 0 | 10 | 2 | 20.0 | 0.0 | 20.0 | 20.0 | 0 |
| `decoys` | `NATIONAL_ID_HU_TAX` | 14 | 0 | 14 | 5 | 35.7 | 0.0 | 20.0 | 35.7 | 0 |
| `decoys` | `PARCEL_NUMBER_HU` | 13 | 0 | 13 | 1 | 7.7 | 0.0 | 20.0 | 7.7 | 0 |
| `decoys` | `PERSON` | 146 | 146 | 0 | 0 | - | - | - | 100.0 | 0 |
| `decoys` | `PHONE` | 34 | 0 | 34 | 11 | 32.4 | 2.9 | 20.0 | 32.4 | 0 |
| `decoys` | `VEHICLE_PLATE` | 13 | 0 | 13 | 3 | 23.1 | 0.0 | 20.0 | 23.1 | 0 |
