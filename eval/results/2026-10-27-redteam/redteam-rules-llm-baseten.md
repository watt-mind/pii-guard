# pii-guard evaluation

- commit: `f97eec600803 (dirty)`, pii-guard 0.1.0
- detectors: `rules`, `llm`
- fixtures: `eval/fixtures/hu-smoke.jsonl` sha256 `3766a651708e8749`
- fixtures: `eval/fixtures/en-smoke.jsonl` sha256 `5983d84d8dfc9fe3`
- fixtures: `eval/fixtures/de-smoke.jsonl` sha256 `b623ca3b33af7ef7`
- fixtures: `eval/fixtures/hu-synth-sample.jsonl` sha256 `ed547228ddc329bb`
- fixtures: `eval/fixtures/en-synth-sample.jsonl` sha256 `2c7ab3d12880065d`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `de` | 10 | 40 | 39 | 100.0 | 97.5 | 98.7 | 100.0 | 97.5 | 98.7 | 99.5 | 2.7 | 2.7 | 0.0 | 100.0 | 97.3 | 1567.31 | 2388.08 |
| `en` | 20 | 154 | 151 | 99.3 | 97.4 | 98.4 | 100.0 | 98.1 | 99.0 | 99.8 | 2.7 | 6.4 | 0.0 | 100.0 | 97.3 | 1648.39 | 5013.19 |
| `hu` | 51 | 391 | 394 | 95.7 | 96.4 | 96.1 | 99.0 | 99.5 | 99.2 | 99.4 | 0.4 | 0.4 | 0.0 | 100.0 | 98.9 | 2056.42 | 4006.80 |
| **overall** | 81 | 585 | 584 | 96.9 | 96.8 | 96.8 | 99.3 | 99.0 | 99.1 | 99.4 | 1.2 | 2.1 | 0.0 | 100.0 | 98.4 | 1871.07 | 4006.80 |

## Per entity type: `de`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 13 | 12 | 100.0 | 92.3 | 96.0 | 100.0 | 92.3 | 96.0 | 7.7 | 7.7 |
| `ADDRESS` | 5 | 5 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `EMAIL` | 3 | 3 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `PHONE` | 5 | 5 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `DATE_OF_BIRTH` | 3 | 3 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `ID_DOCUMENT` | 6 | 6 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `BANK_ACCOUNT` | 2 | 2 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `ORGANIZATION` | 3 | 3 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | keep | keep |
| **all (micro)** | 40 | 39 | 100.0 | 97.5 | 98.7 | 100.0 | 97.5 | 98.7 | 2.7 | 2.7 |

## Per entity type: `en`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 69 | 66 | 98.5 | 94.2 | 96.3 | 100.0 | 95.7 | 97.8 | 7.3 | 9.8 |
| `ADDRESS` | 21 | 21 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 14.3 |
| `EMAIL` | 10 | 10 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `PHONE` | 12 | 12 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `DATE_OF_BIRTH` | 8 | 8 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `NATIONAL_ID_HU_TAX` | 1 | 1 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `ID_DOCUMENT` | 4 | 4 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `BANK_ACCOUNT` | 11 | 11 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `ORGANIZATION` | 14 | 14 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | keep | keep |
| `VEHICLE_PLATE` | 4 | 4 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| **all (micro)** | 154 | 151 | 99.3 | 97.4 | 98.4 | 100.0 | 98.1 | 99.0 | 2.7 | 6.4 |

## Per entity type: `hu`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 145 | 146 | 95.9 | 96.6 | 96.2 | 98.6 | 99.3 | 99.0 | 1.1 | 1.1 |
| `ADDRESS` | 52 | 52 | 96.2 | 96.2 | 96.2 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `EMAIL` | 15 | 15 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `PHONE` | 21 | 21 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `DATE_OF_BIRTH` | 23 | 24 | 91.7 | 95.7 | 93.6 | 95.8 | 100.0 | 97.9 | 0.0 | 0.0 |
| `NATIONAL_ID_HU_TAX` | 13 | 13 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `NATIONAL_ID_HU_TAJ` | 10 | 10 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `ID_DOCUMENT` | 18 | 19 | 84.2 | 88.9 | 86.5 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `BANK_ACCOUNT` | 23 | 23 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `COMPANY_ID_HU` | 14 | 15 | 93.3 | 100.0 | 96.6 | 93.3 | 100.0 | 96.6 | keep | keep |
| `ORGANIZATION` | 31 | 30 | 100.0 | 96.8 | 98.4 | 100.0 | 96.8 | 98.4 | keep | keep |
| `PARCEL_NUMBER_HU` | 13 | 13 | 76.9 | 76.9 | 76.9 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `VEHICLE_PLATE` | 13 | 13 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| **all (micro)** | 391 | 394 | 95.7 | 96.4 | 96.1 | 99.0 | 99.5 | 99.2 | 0.4 | 0.4 |

## Per entity type: overall

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 227 | 224 | 96.9 | 95.6 | 96.2 | 99.1 | 97.8 | 98.4 | 3.4 | 4.1 |
| `ADDRESS` | 78 | 78 | 97.4 | 97.4 | 97.4 | 100.0 | 100.0 | 100.0 | 0.0 | 3.8 |
| `EMAIL` | 28 | 28 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `PHONE` | 38 | 38 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `DATE_OF_BIRTH` | 34 | 35 | 94.3 | 97.1 | 95.7 | 97.1 | 100.0 | 98.6 | 0.0 | 0.0 |
| `NATIONAL_ID_HU_TAX` | 14 | 14 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `NATIONAL_ID_HU_TAJ` | 10 | 10 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `ID_DOCUMENT` | 28 | 29 | 89.7 | 92.9 | 91.2 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `BANK_ACCOUNT` | 36 | 36 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `COMPANY_ID_HU` | 14 | 15 | 93.3 | 100.0 | 96.6 | 93.3 | 100.0 | 96.6 | keep | keep |
| `ORGANIZATION` | 48 | 47 | 100.0 | 97.9 | 98.9 | 100.0 | 97.9 | 98.9 | keep | keep |
| `PARCEL_NUMBER_HU` | 13 | 13 | 76.9 | 76.9 | 76.9 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `VEHICLE_PLATE` | 17 | 17 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| **all (micro)** | 585 | 584 | 96.9 | 96.8 | 96.8 | 99.3 | 99.0 | 99.1 | 1.2 | 2.1 |

## Re-identification red team

Attacker `meta-models/muse-spark-open-1026` (reasoning `low`), 4 decoys per candidate list. Re-id = masked values the attacker recovered; exposure = (leaked + recovered) / values.

| Context | Slice | Values | Leaked | Masked | Recovered | Re-id % | Partial % | Chance % | Exposure % | Failed |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `masked-only` | **all** | 426 | 5 | 421 | 1 | 0.2 | 3.8 | - | 1.4 | 0 |
| `masked-only` | lang `de` | 37 | 1 | 36 | 0 | 0.0 | 0.0 | - | 2.7 | 0 |
| `masked-only` | lang `en` | 110 | 3 | 107 | 0 | 0.0 | 4.7 | - | 2.7 | 0 |
| `masked-only` | lang `hu` | 279 | 1 | 278 | 1 | 0.4 | 4.0 | - | 0.7 | 0 |
| `masked-only` | `ADDRESS` | 78 | 0 | 78 | 0 | 0.0 | 12.8 | - | 0.0 | 0 |
| `masked-only` | `BANK_ACCOUNT` | 31 | 0 | 31 | 0 | 0.0 | 0.0 | - | 0.0 | 0 |
| `masked-only` | `DATE_OF_BIRTH` | 34 | 0 | 34 | 0 | 0.0 | 2.9 | - | 0.0 | 0 |
| `masked-only` | `EMAIL` | 25 | 0 | 25 | 0 | 0.0 | 4.0 | - | 0.0 | 0 |
| `masked-only` | `ID_DOCUMENT` | 28 | 0 | 28 | 0 | 0.0 | 0.0 | - | 0.0 | 0 |
| `masked-only` | `NATIONAL_ID_HU_TAJ` | 10 | 0 | 10 | 1 | 10.0 | 0.0 | - | 10.0 | 0 |
| `masked-only` | `NATIONAL_ID_HU_TAX` | 14 | 0 | 14 | 0 | 0.0 | 0.0 | - | 0.0 | 0 |
| `masked-only` | `PARCEL_NUMBER_HU` | 13 | 0 | 13 | 0 | 0.0 | 0.0 | - | 0.0 | 0 |
| `masked-only` | `PERSON` | 146 | 5 | 141 | 0 | 0.0 | 2.1 | - | 3.4 | 0 |
| `masked-only` | `PHONE` | 34 | 0 | 34 | 0 | 0.0 | 2.9 | - | 0.0 | 0 |
| `masked-only` | `VEHICLE_PLATE` | 13 | 0 | 13 | 0 | 0.0 | 0.0 | - | 0.0 | 0 |
| `decoys` | **all** | 426 | 5 | 421 | 165 | 39.2 | 3.6 | 20.0 | 39.9 | 0 |
| `decoys` | lang `de` | 37 | 1 | 36 | 14 | 38.9 | 0.0 | 20.0 | 40.5 | 0 |
| `decoys` | lang `en` | 110 | 3 | 107 | 56 | 52.3 | 4.7 | 20.0 | 53.6 | 0 |
| `decoys` | lang `hu` | 279 | 1 | 278 | 95 | 34.2 | 3.6 | 20.0 | 34.4 | 0 |
| `decoys` | `ADDRESS` | 78 | 0 | 78 | 21 | 26.9 | 14.1 | 20.0 | 26.9 | 0 |
| `decoys` | `BANK_ACCOUNT` | 31 | 0 | 31 | 12 | 38.7 | 0.0 | 20.0 | 38.7 | 0 |
| `decoys` | `DATE_OF_BIRTH` | 34 | 0 | 34 | 11 | 32.4 | 0.0 | 20.0 | 32.4 | 0 |
| `decoys` | `EMAIL` | 25 | 0 | 25 | 19 | 76.0 | 0.0 | 20.0 | 76.0 | 0 |
| `decoys` | `ID_DOCUMENT` | 28 | 0 | 28 | 10 | 35.7 | 0.0 | 20.0 | 35.7 | 0 |
| `decoys` | `NATIONAL_ID_HU_TAJ` | 10 | 0 | 10 | 1 | 10.0 | 0.0 | 20.0 | 10.0 | 0 |
| `decoys` | `NATIONAL_ID_HU_TAX` | 14 | 0 | 14 | 3 | 21.4 | 0.0 | 20.0 | 21.4 | 0 |
| `decoys` | `PARCEL_NUMBER_HU` | 13 | 0 | 13 | 2 | 15.4 | 0.0 | 20.0 | 15.4 | 0 |
| `decoys` | `PERSON` | 146 | 5 | 141 | 72 | 51.1 | 2.1 | 20.0 | 52.7 | 0 |
| `decoys` | `PHONE` | 34 | 0 | 34 | 12 | 35.3 | 2.9 | 20.0 | 35.3 | 0 |
| `decoys` | `VEHICLE_PLATE` | 13 | 0 | 13 | 2 | 15.4 | 0.0 | 20.0 | 15.4 | 0 |
