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
| pii-guard rules+llm | 10 | 94.4 | 100.0 | 97.1 | 94.3 | 0.0 | 3.3 | 3.2 | 100.0 | 6952.7 | 29319.3 |

Per entity type, `en`: overlap recall / leak rate (leak only for mask-policy types).

| Entity type | Gold | pii-guard rules | presidio | llm-guard | privaite | pii-guard rules+llm |
|---|---:|---:|---:|---:|---:|---:|
| `PERSON` | 10 | 0.0 / 100.0 | 90.0 / 10.0 | 100.0 / 0.0 | 100.0 / 0.0 | 100.0 / 0.0 |
| `ADDRESS` | 4 | 50.0 / 50.0 | 25.0 / 25.0 | 0.0 / 100.0 | 100.0 / 0.0 | 100.0 / 0.0 |
| `EMAIL` | 3 | 100.0 / 0.0 | 100.0 / 0.0 | 100.0 / 0.0 | 100.0 / 0.0 | 100.0 / 0.0 |
| `PHONE` | 4 | 100.0 / 0.0 | 75.0 / 0.0 | 100.0 / 0.0 | 100.0 / 0.0 | 100.0 / 0.0 |
| `DATE_OF_BIRTH` | 2 | 0.0 / 100.0 | 100.0 / 0.0 | 0.0 / 100.0 | 100.0 / 0.0 | 100.0 / 0.0 |
| `NATIONAL_ID_HU_TAX` | 1 | 100.0 / 0.0 | 0.0 / 0.0 | 0.0 / 100.0 | 0.0 / 0.0 | 100.0 / 0.0 |
| `ID_DOCUMENT` | 1 | 100.0 / 0.0 | 100.0 / 0.0 | 0.0 / 100.0 | 0.0 / 0.0 | 100.0 / 0.0 |
| `BANK_ACCOUNT` | 4 | 100.0 / 0.0 | 100.0 / 0.0 | 100.0 / 0.0 | 100.0 / 0.0 | 100.0 / 0.0 |
| `ORGANIZATION` | 4 | 0.0 | 75.0 | 0.0 | 0.0 | 100.0 |
| `VEHICLE_PLATE` | 1 | 100.0 / 0.0 | 0.0 / 100.0 | 0.0 / 100.0 | 0.0 / 0.0 | 100.0 / 0.0 |

### `hu`

| System | Docs | P overlap | R overlap | F1 overlap | F1 exact | Leak | Partial leak | Over-masking | Round trip | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| pii-guard rules | 28 | 100.0 | 45.0 | 62.1 | 47.2 | 52.6 | 15.5 | 0.0 | 100.0 | 0.1 | 0.2 |
| presidio | 28 | 76.4 | 64.9 | 70.1 | 48.0 | 28.9 | 12.4 | 15.5 | n/a | 75.6 | 128.0 |
| llm-guard | 28 | 57.1 | 43.2 | 49.2 | 5.0 | 49.5 | 4.1 | 41.7 | 100.0 | 61.4 | 86.8 |
| privaite | 28 | 47.5 | 53.2 | 50.2 | 23.2 | 19.6 | 10.3 | 26.6 | 100.0 | 60.1 | 120.1 |
| pii-guard rules+llm | 28 | 98.2 | 98.2 | 98.2 | 86.6 | 1.0 | 1.0 | 0.0 | 100.0 | 10578.0 | 26002.2 |

Per entity type, `hu`: overlap recall / leak rate (leak only for mask-policy types).

| Entity type | Gold | pii-guard rules | presidio | llm-guard | privaite | pii-guard rules+llm |
|---|---:|---:|---:|---:|---:|---:|
| `PERSON` | 36 | 0.0 / 100.0 | 97.2 / 2.9 | 88.9 / 11.4 | 66.7 / 28.6 | 97.2 / 2.9 |
| `ADDRESS` | 13 | 92.3 / 7.7 | 100.0 / 0.0 | 0.0 / 92.3 | 100.0 / 0.0 | 100.0 / 0.0 |
| `EMAIL` | 6 | 100.0 / 0.0 | 83.3 / 0.0 | 100.0 / 0.0 | 100.0 / 0.0 | 100.0 / 0.0 |
| `PHONE` | 7 | 100.0 / 0.0 | 100.0 / 0.0 | 100.0 / 0.0 | 100.0 / 0.0 | 100.0 / 0.0 |
| `DATE_OF_BIRTH` | 6 | 0.0 / 100.0 | 0.0 / 100.0 | 0.0 / 100.0 | 50.0 / 16.7 | 100.0 / 0.0 |
| `NATIONAL_ID_HU_TAX` | 5 | 100.0 / 0.0 | 0.0 / 0.0 | 0.0 / 100.0 | 0.0 / 0.0 | 100.0 / 0.0 |
| `NATIONAL_ID_HU_TAJ` | 5 | 100.0 / 0.0 | 0.0 / 100.0 | 0.0 / 100.0 | 0.0 / 0.0 | 100.0 / 0.0 |
| `ID_DOCUMENT` | 5 | 0.0 / 100.0 | 0.0 / 100.0 | 0.0 / 100.0 | 0.0 / 0.0 | 100.0 / 0.0 |
| `BANK_ACCOUNT` | 6 | 100.0 / 0.0 | 50.0 / 50.0 | 50.0 / 33.3 | 100.0 / 0.0 | 100.0 / 0.0 |
| `COMPANY_ID_HU` | 4 | 100.0 | 0.0 | 0.0 | 0.0 | 100.0 |
| `ORGANIZATION` | 9 | 0.0 | 100.0 | 0.0 | 0.0 | 100.0 |
| `PARCEL_NUMBER_HU` | 4 | 0.0 / 100.0 | 0.0 / 100.0 | 0.0 / 100.0 | 0.0 / 75.0 | 75.0 / 0.0 |
| `VEHICLE_PLATE` | 5 | 100.0 / 0.0 | 0.0 / 80.0 | 0.0 / 100.0 | 0.0 / 100.0 | 100.0 / 0.0 |

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
