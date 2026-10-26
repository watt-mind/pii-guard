# pii-guard evaluation

- commit: `62b64fc65593`, pii-guard 0.1.0
- detectors: `rules`
- fixtures: `eval/fixtures/hu-smoke.jsonl` sha256 `292c687941f295cb`
- fixtures: `eval/fixtures/en-smoke.jsonl` sha256 `5983d84d8dfc9fe3`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `en` | 10 | 34 | 16 | 87.5 | 41.2 | 56.0 | 100.0 | 47.1 | 64.0 | 66.7 | 46.7 | 13.3 | 0.0 | 100.0 | 0.11 | 0.18 |
| `hu` | 28 | 111 | 50 | 76.0 | 34.2 | 47.2 | 100.0 | 45.0 | 62.1 | 61.2 | 52.6 | 15.5 | 0.0 | 100.0 | 0.10 | 0.22 |
| **overall** | 38 | 145 | 66 | 78.8 | 35.9 | 49.3 | 100.0 | 45.5 | 62.6 | 63.0 | 51.2 | 15.0 | 0.0 | 100.0 | 0.11 | 0.22 |

## Per entity type: `en`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 10 | 0 | - | 0.0 | 0.0 | - | 0.0 | 0.0 | 100.0 | 0.0 |
| `ADDRESS` | 4 | 2 | 0.0 | 0.0 | 0.0 | 100.0 | 50.0 | 66.7 | 50.0 | 50.0 |
| `EMAIL` | 3 | 3 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 66.7 |
| `PHONE` | 4 | 4 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `DATE_OF_BIRTH` | 2 | 0 | - | 0.0 | 0.0 | - | 0.0 | 0.0 | 100.0 | 0.0 |
| `NATIONAL_ID_HU_TAX` | 1 | 1 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `ID_DOCUMENT` | 1 | 1 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `BANK_ACCOUNT` | 4 | 4 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `ORGANIZATION` | 4 | 0 | - | 0.0 | 0.0 | - | 0.0 | 0.0 | keep | keep |
| `VEHICLE_PLATE` | 1 | 1 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| **all (micro)** | 34 | 16 | 87.5 | 41.2 | 56.0 | 100.0 | 47.1 | 64.0 | 46.7 | 13.3 |

## Per entity type: `hu`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 36 | 0 | - | 0.0 | 0.0 | - | 0.0 | 0.0 | 100.0 | 0.0 |
| `ADDRESS` | 13 | 12 | 0.0 | 0.0 | 0.0 | 100.0 | 92.3 | 96.0 | 7.7 | 92.3 |
| `EMAIL` | 6 | 6 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 50.0 |
| `PHONE` | 7 | 7 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `DATE_OF_BIRTH` | 6 | 0 | - | 0.0 | 0.0 | - | 0.0 | 0.0 | 100.0 | 0.0 |
| `NATIONAL_ID_HU_TAX` | 5 | 5 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `NATIONAL_ID_HU_TAJ` | 5 | 5 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `ID_DOCUMENT` | 5 | 0 | - | 0.0 | 0.0 | - | 0.0 | 0.0 | 100.0 | 0.0 |
| `BANK_ACCOUNT` | 6 | 6 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `COMPANY_ID_HU` | 4 | 4 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | keep | keep |
| `ORGANIZATION` | 9 | 0 | - | 0.0 | 0.0 | - | 0.0 | 0.0 | keep | keep |
| `PARCEL_NUMBER_HU` | 4 | 0 | - | 0.0 | 0.0 | - | 0.0 | 0.0 | 100.0 | 0.0 |
| `VEHICLE_PLATE` | 5 | 5 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| **all (micro)** | 111 | 50 | 76.0 | 34.2 | 47.2 | 100.0 | 45.0 | 62.1 | 52.6 | 15.5 |

## Per entity type: overall

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 46 | 0 | - | 0.0 | 0.0 | - | 0.0 | 0.0 | 100.0 | 0.0 |
| `ADDRESS` | 17 | 14 | 0.0 | 0.0 | 0.0 | 100.0 | 82.4 | 90.3 | 17.6 | 82.4 |
| `EMAIL` | 9 | 9 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 55.6 |
| `PHONE` | 11 | 11 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `DATE_OF_BIRTH` | 8 | 0 | - | 0.0 | 0.0 | - | 0.0 | 0.0 | 100.0 | 0.0 |
| `NATIONAL_ID_HU_TAX` | 6 | 6 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `NATIONAL_ID_HU_TAJ` | 5 | 5 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `ID_DOCUMENT` | 6 | 1 | 100.0 | 16.7 | 28.6 | 100.0 | 16.7 | 28.6 | 83.3 | 0.0 |
| `BANK_ACCOUNT` | 10 | 10 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `COMPANY_ID_HU` | 4 | 4 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | keep | keep |
| `ORGANIZATION` | 13 | 0 | - | 0.0 | 0.0 | - | 0.0 | 0.0 | keep | keep |
| `PARCEL_NUMBER_HU` | 4 | 0 | - | 0.0 | 0.0 | - | 0.0 | 0.0 | 100.0 | 0.0 |
| `VEHICLE_PLATE` | 6 | 6 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| **all (micro)** | 145 | 66 | 78.8 | 35.9 | 49.3 | 100.0 | 45.5 | 62.6 | 51.2 | 15.0 |

# pii-guard vs open-source baselines

All ratios in %. P/R/F1 are span-level micro averages over pii-guard's entity types (tool labels mapped as in docs/evaluation.md). Leak = labelled values of mask-policy types surviving the text each system would send upstream (its own masking). Latency is detection only.

## Fixtures: `hu-smoke.jsonl`, `en-smoke.jsonl`

- fixture sha256: `hu-smoke.jsonl` `292c687941f295cb`, `en-smoke.jsonl` `5983d84d8dfc9fe3`
- commit: `62b64fc65593`

### `en`

| System | Docs | P overlap | R overlap | F1 overlap | F1 exact | Leak | Partial leak | Over-masking | Round trip | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| pii-guard rules | 10 | 100.0 | 47.1 | 64.0 | 56.0 | 46.7 | 13.3 | 0.0 | 100.0 | 0.1 | 0.2 |
| presidio | 10 | 61.9 | 76.5 | 68.4 | 65.8 | 10.0 | 13.3 | 26.2 | n/a | 7.5 | 12.1 |
| llm-guard | 10 | 100.0 | 61.8 | 76.4 | 31.7 | 30.0 | 13.3 | 0.0 | 100.0 | 50.7 | 68.2 |
| privaite | 10 | 70.7 | 79.4 | 74.8 | 61.3 | 0.0 | 13.3 | 22.0 | 100.0 | 52.5 | 98.0 |

Per entity type, `en`: overlap recall / leak rate (leak only for mask-policy types).

| Entity type | Gold | pii-guard rules | presidio | llm-guard | privaite |
|---|---:|---:|---:|---:|---:|
| `PERSON` | 10 | 0.0 / 100.0 | 90.0 / 10.0 | 100.0 / 0.0 | 100.0 / 0.0 |
| `ADDRESS` | 4 | 50.0 / 50.0 | 25.0 / 25.0 | 0.0 / 100.0 | 100.0 / 0.0 |
| `EMAIL` | 3 | 100.0 / 0.0 | 100.0 / 0.0 | 100.0 / 0.0 | 100.0 / 0.0 |
| `PHONE` | 4 | 100.0 / 0.0 | 75.0 / 0.0 | 100.0 / 0.0 | 100.0 / 0.0 |
| `DATE_OF_BIRTH` | 2 | 0.0 / 100.0 | 100.0 / 0.0 | 0.0 / 100.0 | 100.0 / 0.0 |
| `NATIONAL_ID_HU_TAX` | 1 | 100.0 / 0.0 | 0.0 / 0.0 | 0.0 / 100.0 | 0.0 / 0.0 |
| `ID_DOCUMENT` | 1 | 100.0 / 0.0 | 100.0 / 0.0 | 0.0 / 100.0 | 0.0 / 0.0 |
| `BANK_ACCOUNT` | 4 | 100.0 / 0.0 | 100.0 / 0.0 | 100.0 / 0.0 | 100.0 / 0.0 |
| `ORGANIZATION` | 4 | 0.0 | 75.0 | 0.0 | 0.0 |
| `VEHICLE_PLATE` | 1 | 100.0 / 0.0 | 0.0 / 100.0 | 0.0 / 100.0 | 0.0 / 0.0 |

### `hu`

| System | Docs | P overlap | R overlap | F1 overlap | F1 exact | Leak | Partial leak | Over-masking | Round trip | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| pii-guard rules | 28 | 100.0 | 45.0 | 62.1 | 47.2 | 52.6 | 15.5 | 0.0 | 100.0 | 0.1 | 0.2 |
| presidio | 28 | 76.4 | 64.9 | 70.1 | 48.0 | 28.9 | 12.4 | 15.5 | n/a | 75.6 | 128.0 |
| llm-guard | 28 | 57.1 | 43.2 | 49.2 | 5.0 | 49.5 | 4.1 | 41.7 | 100.0 | 61.4 | 86.8 |
| privaite | 28 | 47.5 | 53.2 | 50.2 | 23.2 | 19.6 | 10.3 | 26.6 | 100.0 | 60.1 | 120.1 |

Per entity type, `hu`: overlap recall / leak rate (leak only for mask-policy types).

| Entity type | Gold | pii-guard rules | presidio | llm-guard | privaite |
|---|---:|---:|---:|---:|---:|
| `PERSON` | 36 | 0.0 / 100.0 | 97.2 / 2.9 | 88.9 / 11.4 | 66.7 / 28.6 |
| `ADDRESS` | 13 | 92.3 / 7.7 | 100.0 / 0.0 | 0.0 / 92.3 | 100.0 / 0.0 |
| `EMAIL` | 6 | 100.0 / 0.0 | 83.3 / 0.0 | 100.0 / 0.0 | 100.0 / 0.0 |
| `PHONE` | 7 | 100.0 / 0.0 | 100.0 / 0.0 | 100.0 / 0.0 | 100.0 / 0.0 |
| `DATE_OF_BIRTH` | 6 | 0.0 / 100.0 | 0.0 / 100.0 | 0.0 / 100.0 | 50.0 / 16.7 |
| `NATIONAL_ID_HU_TAX` | 5 | 100.0 / 0.0 | 0.0 / 0.0 | 0.0 / 100.0 | 0.0 / 0.0 |
| `NATIONAL_ID_HU_TAJ` | 5 | 100.0 / 0.0 | 0.0 / 100.0 | 0.0 / 100.0 | 0.0 / 0.0 |
| `ID_DOCUMENT` | 5 | 0.0 / 100.0 | 0.0 / 100.0 | 0.0 / 100.0 | 0.0 / 0.0 |
| `BANK_ACCOUNT` | 6 | 100.0 / 0.0 | 50.0 / 50.0 | 50.0 / 33.3 | 100.0 / 0.0 |
| `COMPANY_ID_HU` | 4 | 100.0 | 0.0 | 0.0 | 0.0 |
| `ORGANIZATION` | 9 | 0.0 | 100.0 | 0.0 | 0.0 |
| `PARCEL_NUMBER_HU` | 4 | 0.0 / 100.0 | 0.0 / 100.0 | 0.0 / 100.0 | 0.0 / 75.0 |
| `VEHICLE_PLATE` | 5 | 100.0 / 0.0 | 0.0 / 80.0 | 0.0 / 100.0 | 0.0 / 100.0 |

### Baseline configurations

- **presidio**: presidio-analyzer 2.2.365, presidio-anonymizer 2.2.365, spacy 3.8.18
  - model: `en_core_web_lg 3.8.0 (en)`
  - model: `hu_core_news_lg 3.8.1 (hu, huSpaCy)`
  - unmapped labels (masked, not scored for P/R): `NRP` x1, `URL` x10
- **llm-guard**: llm-guard 0.3.16, presidio-analyzer 2.2.358, transformers 4.51.3, torch 2.14.1, spacy 3.8.18
  - model: `Isotonic/deberta-v3-base_finetuned_ai4privacy_v2@9ea992753ab2686be4a8f64605ccc7be197ad794`
  - model: `en_core_web_sm 3.8.0`
  - model: `zh_core_web_sm 3.8.0`
- **privaite**: privaite 0.7.3, presidio-analyzer 2.2.365, onnxruntime 1.31.1, transformers 5.21.0, spacy 3.8.18
  - model: `openai/privacy-filter@7ffa9a043d54d1be65afb281eddf0ffbe629385b (q4)`
  - model: `en_core_web_lg 3.8.0`
  - model: `fr_core_news_md 3.8.0`
  - unmapped labels (masked, not scored for P/R): `URL` x2

Latency measured on arm64 (macOS-26.5.2-arm64-arm-64bit, 10 CPUs), CPU only, single process, after one warm-up call.
