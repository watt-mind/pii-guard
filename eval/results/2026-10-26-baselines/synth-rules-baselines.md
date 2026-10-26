# pii-guard evaluation

- commit: `62b64fc65593`, pii-guard 0.1.0
- detectors: `rules`
- fixtures: `eval/fixtures/hu-synth-sample.jsonl` sha256 `ed547228ddc329bb`
- fixtures: `eval/fixtures/en-synth-sample.jsonl` sha256 `2c7ab3d12880065d`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `en` | 10 | 120 | 45 | 62.2 | 23.3 | 33.9 | 100.0 | 37.5 | 54.5 | 66.7 | 46.2 | 25.0 | 0.0 | 100.0 | 0.80 | 1.64 |
| `hu` | 20 | 271 | 110 | 64.5 | 26.2 | 37.3 | 100.0 | 40.6 | 57.7 | 61.5 | 50.3 | 22.5 | 0.0 | 100.0 | 0.61 | 1.37 |
| **overall** | 30 | 391 | 155 | 63.9 | 25.3 | 36.3 | 100.0 | 39.6 | 56.8 | 64.8 | 49.0 | 23.3 | 0.0 | 100.0 | 0.66 | 1.62 |

## Per entity type: `en`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 59 | 0 | - | 0.0 | 0.0 | - | 0.0 | 0.0 | 100.0 | 0.0 |
| `ADDRESS` | 17 | 17 | 0.0 | 0.0 | 0.0 | 100.0 | 100.0 | 100.0 | 0.0 | 100.0 |
| `EMAIL` | 7 | 7 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 50.0 |
| `PHONE` | 8 | 8 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `DATE_OF_BIRTH` | 6 | 0 | - | 0.0 | 0.0 | - | 0.0 | 0.0 | 100.0 | 0.0 |
| `ID_DOCUMENT` | 3 | 3 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `BANK_ACCOUNT` | 7 | 7 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `ORGANIZATION` | 10 | 0 | - | 0.0 | 0.0 | - | 0.0 | 0.0 | keep | keep |
| `VEHICLE_PLATE` | 3 | 3 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| **all (micro)** | 120 | 45 | 62.2 | 23.3 | 33.9 | 100.0 | 37.5 | 54.5 | 46.2 | 25.0 |

## Per entity type: `hu`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 107 | 0 | - | 0.0 | 0.0 | - | 0.0 | 0.0 | 100.0 | 0.0 |
| `ADDRESS` | 39 | 39 | 0.0 | 0.0 | 0.0 | 100.0 | 100.0 | 100.0 | 0.0 | 94.9 |
| `EMAIL` | 9 | 9 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 28.6 |
| `PHONE` | 14 | 14 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `DATE_OF_BIRTH` | 17 | 0 | - | 0.0 | 0.0 | - | 0.0 | 0.0 | 100.0 | 0.0 |
| `NATIONAL_ID_HU_TAX` | 8 | 8 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `NATIONAL_ID_HU_TAJ` | 5 | 5 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `ID_DOCUMENT` | 8 | 0 | - | 0.0 | 0.0 | - | 0.0 | 0.0 | 100.0 | 0.0 |
| `BANK_ACCOUNT` | 17 | 17 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `COMPANY_ID_HU` | 10 | 10 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | keep | keep |
| `ORGANIZATION` | 22 | 0 | - | 0.0 | 0.0 | - | 0.0 | 0.0 | keep | keep |
| `PARCEL_NUMBER_HU` | 7 | 0 | - | 0.0 | 0.0 | - | 0.0 | 0.0 | 100.0 | 0.0 |
| `VEHICLE_PLATE` | 8 | 8 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| **all (micro)** | 271 | 110 | 64.5 | 26.2 | 37.3 | 100.0 | 40.6 | 57.7 | 50.3 | 22.5 |

## Per entity type: overall

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 166 | 0 | - | 0.0 | 0.0 | - | 0.0 | 0.0 | 100.0 | 0.0 |
| `ADDRESS` | 56 | 56 | 0.0 | 0.0 | 0.0 | 100.0 | 100.0 | 100.0 | 0.0 | 96.4 |
| `EMAIL` | 16 | 16 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 38.5 |
| `PHONE` | 22 | 22 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `DATE_OF_BIRTH` | 23 | 0 | - | 0.0 | 0.0 | - | 0.0 | 0.0 | 100.0 | 0.0 |
| `NATIONAL_ID_HU_TAX` | 8 | 8 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `NATIONAL_ID_HU_TAJ` | 5 | 5 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `ID_DOCUMENT` | 11 | 3 | 100.0 | 27.3 | 42.9 | 100.0 | 27.3 | 42.9 | 72.7 | 0.0 |
| `BANK_ACCOUNT` | 24 | 24 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `COMPANY_ID_HU` | 10 | 10 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | keep | keep |
| `ORGANIZATION` | 32 | 0 | - | 0.0 | 0.0 | - | 0.0 | 0.0 | keep | keep |
| `PARCEL_NUMBER_HU` | 7 | 0 | - | 0.0 | 0.0 | - | 0.0 | 0.0 | 100.0 | 0.0 |
| `VEHICLE_PLATE` | 11 | 11 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| **all (micro)** | 391 | 155 | 63.9 | 25.3 | 36.3 | 100.0 | 39.6 | 56.8 | 49.0 | 23.3 |

# pii-guard vs open-source baselines

All ratios in %. P/R/F1 are span-level micro averages over pii-guard's entity types (tool labels mapped as in docs/evaluation.md). Leak = labelled values of mask-policy types surviving the text each system would send upstream (its own masking). Latency is detection only.

## Fixtures: `hu-synth-sample.jsonl`, `en-synth-sample.jsonl`

- fixture sha256: `hu-synth-sample.jsonl` `ed547228ddc329bb`, `en-synth-sample.jsonl` `2c7ab3d12880065d`
- commit: `62b64fc65593`

### `en`

| System | Docs | P overlap | R overlap | F1 overlap | F1 exact | Leak | Partial leak | Over-masking | Round trip | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| pii-guard rules | 10 | 100.0 | 37.5 | 54.5 | 33.9 | 46.2 | 25.0 | 0.0 | 100.0 | 0.8 | 1.6 |
| presidio | 10 | 50.5 | 83.3 | 62.9 | 47.2 | 11.2 | 26.2 | 44.6 | n/a | 31.5 | 78.2 |
| llm-guard | 10 | 98.4 | 46.7 | 63.3 | 36.3 | 48.8 | 13.8 | 1.6 | 100.0 | 136.8 | 367.7 |
| privaite | 10 | 73.1 | 80.8 | 76.8 | 66.1 | 7.5 | 3.8 | 21.6 | 100.0 | 231.1 | 465.4 |

Per entity type, `en`: overlap recall / leak rate (leak only for mask-policy types).

| Entity type | Gold | pii-guard rules | presidio | llm-guard | privaite |
|---|---:|---:|---:|---:|---:|
| `PERSON` | 59 | 0.0 / 100.0 | 89.8 / 6.5 | 57.6 / 32.3 | 100.0 / 0.0 |
| `ADDRESS` | 17 | 100.0 / 0.0 | 88.2 / 11.8 | 0.0 / 100.0 | 76.5 / 17.6 |
| `EMAIL` | 7 | 100.0 / 0.0 | 57.1 / 33.3 | 100.0 / 0.0 | 57.1 / 33.3 |
| `PHONE` | 8 | 100.0 / 0.0 | 37.5 / 0.0 | 100.0 / 0.0 | 100.0 / 0.0 |
| `DATE_OF_BIRTH` | 6 | 0.0 / 100.0 | 100.0 / 0.0 | 0.0 / 100.0 | 100.0 / 0.0 |
| `ID_DOCUMENT` | 3 | 100.0 / 0.0 | 100.0 / 0.0 | 0.0 / 100.0 | 0.0 / 0.0 |
| `BANK_ACCOUNT` | 7 | 100.0 / 0.0 | 100.0 / 0.0 | 100.0 / 0.0 | 100.0 / 0.0 |
| `ORGANIZATION` | 10 | 0.0 | 90.0 | 0.0 | 0.0 |
| `VEHICLE_PLATE` | 3 | 100.0 / 0.0 | 0.0 / 100.0 | 0.0 / 100.0 | 0.0 / 33.3 |

### `hu`

| System | Docs | P overlap | R overlap | F1 overlap | F1 exact | Leak | Partial leak | Over-masking | Round trip | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| pii-guard rules | 20 | 100.0 | 40.6 | 57.7 | 37.3 | 50.3 | 22.5 | 0.0 | 100.0 | 0.6 | 1.4 |
| presidio | 20 | 83.1 | 70.8 | 76.5 | 54.3 | 28.9 | 23.1 | 9.7 | n/a | 322.5 | 715.7 |
| llm-guard | 20 | 58.1 | 39.1 | 46.8 | 5.6 | 60.1 | 9.2 | 38.6 | 100.0 | 246.5 | 982.3 |
| privaite | 20 | 51.7 | 49.4 | 50.6 | 31.7 | 24.3 | 11.6 | 25.2 | 75.0 | 321.2 | 885.4 |

Per entity type, `hu`: overlap recall / leak rate (leak only for mask-policy types).

| Entity type | Gold | pii-guard rules | presidio | llm-guard | privaite |
|---|---:|---:|---:|---:|---:|
| `PERSON` | 107 | 0.0 / 100.0 | 97.2 / 5.5 | 70.1 / 18.2 | 55.1 / 45.5 |
| `ADDRESS` | 39 | 100.0 / 0.0 | 100.0 / 0.0 | 0.0 / 100.0 | 71.8 / 15.4 |
| `EMAIL` | 9 | 100.0 / 0.0 | 66.7 / 28.6 | 100.0 / 0.0 | 77.8 / 14.3 |
| `PHONE` | 14 | 100.0 / 0.0 | 100.0 / 0.0 | 100.0 / 0.0 | 85.7 / 0.0 |
| `DATE_OF_BIRTH` | 17 | 0.0 / 100.0 | 5.9 / 94.1 | 0.0 / 100.0 | 76.5 / 17.6 |
| `NATIONAL_ID_HU_TAX` | 8 | 100.0 / 0.0 | 0.0 / 0.0 | 0.0 / 100.0 | 0.0 / 0.0 |
| `NATIONAL_ID_HU_TAJ` | 5 | 100.0 / 0.0 | 0.0 / 100.0 | 0.0 / 100.0 | 0.0 / 0.0 |
| `ID_DOCUMENT` | 8 | 0.0 / 100.0 | 0.0 / 100.0 | 0.0 / 100.0 | 0.0 / 0.0 |
| `BANK_ACCOUNT` | 17 | 100.0 / 0.0 | 35.3 / 58.3 | 47.1 / 50.0 | 88.2 / 8.3 |
| `COMPANY_ID_HU` | 10 | 100.0 | 0.0 | 0.0 | 0.0 |
| `ORGANIZATION` | 22 | 0.0 | 100.0 | 0.0 | 0.0 |
| `PARCEL_NUMBER_HU` | 7 | 0.0 / 100.0 | 0.0 / 100.0 | 0.0 / 100.0 | 0.0 / 42.9 |
| `VEHICLE_PLATE` | 8 | 100.0 / 0.0 | 0.0 / 50.0 | 0.0 / 100.0 | 0.0 / 75.0 |

### Baseline configurations

- **presidio**: presidio-analyzer 2.2.365, presidio-anonymizer 2.2.365, spacy 3.8.18
  - model: `en_core_web_lg 3.8.0 (en)`
  - model: `hu_core_news_lg 3.8.1 (hu, huSpaCy)`
  - unmapped labels (masked, not scored for P/R): `URL` x13
- **llm-guard**: llm-guard 0.3.16, presidio-analyzer 2.2.358, transformers 4.51.3, torch 2.14.1, spacy 3.8.18
  - model: `Isotonic/deberta-v3-base_finetuned_ai4privacy_v2@9ea992753ab2686be4a8f64605ccc7be197ad794`
  - model: `en_core_web_sm 3.8.0`
  - model: `zh_core_web_sm 3.8.0`
  - unmapped labels (masked, not scored for P/R): `CRYPTO` x4, `IP_ADDRESS` x41
- **privaite**: privaite 0.7.3, presidio-analyzer 2.2.365, onnxruntime 1.31.1, transformers 5.21.0, spacy 3.8.18
  - model: `openai/privacy-filter@7ffa9a043d54d1be65afb281eddf0ffbe629385b (q4)`
  - model: `en_core_web_lg 3.8.0`
  - model: `fr_core_news_md 3.8.0`
  - unmapped labels (masked, not scored for P/R): `SECRET` x3

Latency measured on arm64 (macOS-26.5.2-arm64-arm-64bit, 10 CPUs), CPU only, single process, after one warm-up call.
