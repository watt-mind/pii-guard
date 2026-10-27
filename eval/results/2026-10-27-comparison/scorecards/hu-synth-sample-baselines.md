# pii-guard evaluation

- commit: `e394a0636ca0 (dirty)`, pii-guard 0.1.0
- detectors: `rules`
- fixtures: `eval/fixtures/hu-synth-sample.jsonl` sha256 `ed547228ddc329bb`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `hu` | 20 | 271 | 125 | 100.0 | 46.1 | 63.1 | 100.0 | 46.1 | 63.1 | 76.9 | 41.6 | 1.2 | 0.0 | 100.0 | 58.7 | 0.94 | 2.38 |
| **overall** | 20 | 271 | 125 | 100.0 | 46.1 | 63.1 | 100.0 | 46.1 | 63.1 | 76.9 | 41.6 | 1.2 | 0.0 | 100.0 | 58.7 | 0.94 | 2.38 |

## Per entity type: `hu`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 107 | 0 | - | 0.0 | 0.0 | - | 0.0 | 0.0 | 100.0 | 0.0 |
| `ADDRESS` | 39 | 39 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `EMAIL` | 9 | 9 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 28.6 |
| `PHONE` | 14 | 14 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `DATE_OF_BIRTH` | 17 | 0 | - | 0.0 | 0.0 | - | 0.0 | 0.0 | 100.0 | 0.0 |
| `NATIONAL_ID_HU_TAX` | 8 | 8 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `NATIONAL_ID_HU_TAJ` | 5 | 5 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `ID_DOCUMENT` | 8 | 8 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `BANK_ACCOUNT` | 17 | 17 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `COMPANY_ID_HU` | 10 | 10 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | keep | keep |
| `ORGANIZATION` | 22 | 0 | - | 0.0 | 0.0 | - | 0.0 | 0.0 | keep | keep |
| `PARCEL_NUMBER_HU` | 7 | 7 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `VEHICLE_PLATE` | 8 | 8 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| **all (micro)** | 271 | 125 | 100.0 | 46.1 | 63.1 | 100.0 | 46.1 | 63.1 | 41.6 | 1.2 |

# pii-guard vs open-source baselines

All ratios in %. P/R/F1 are span-level micro averages over pii-guard's entity types (tool labels mapped as in docs/evaluation.md). Leak = labelled values of mask-policy types surviving the text each system would send upstream (its own masking). Latency is detection only.

## Fixtures: `hu-synth-sample.jsonl`

- fixture sha256: `hu-synth-sample.jsonl` `ed547228ddc329bb`
- commit: `e394a0636ca0 (dirty)`

### `hu`

| System | Docs | P overlap | R overlap | F1 overlap | F1 exact | Leak | Partial leak | Over-masking | Round trip | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| pii-guard rules | 20 | 100.0 | 46.1 | 63.1 | 63.1 | 41.6 | 1.2 | 0.0 | 100.0 | 0.9 | 2.4 |
| presidio | 20 | 83.1 | 70.8 | 76.5 | 54.3 | 28.9 | 23.1 | 9.7 | n/a | 300.0 | 655.2 |
| llm-guard | 20 | 58.1 | 39.1 | 46.8 | 5.6 | 60.1 | 9.2 | 38.6 | 100.0 | 220.4 | 941.3 |
| privaite | 20 | 51.7 | 49.4 | 50.6 | 31.7 | 24.3 | 11.6 | 25.2 | 75.0 | 267.0 | 730.2 |

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
| `ID_DOCUMENT` | 8 | 100.0 / 0.0 | 0.0 / 100.0 | 0.0 / 100.0 | 0.0 / 0.0 |
| `BANK_ACCOUNT` | 17 | 100.0 / 0.0 | 35.3 / 58.3 | 47.1 / 50.0 | 88.2 / 8.3 |
| `COMPANY_ID_HU` | 10 | 100.0 | 0.0 | 0.0 | 0.0 |
| `ORGANIZATION` | 22 | 0.0 | 100.0 | 0.0 | 0.0 |
| `PARCEL_NUMBER_HU` | 7 | 100.0 / 0.0 | 0.0 / 100.0 | 0.0 / 100.0 | 0.0 / 42.9 |
| `VEHICLE_PLATE` | 8 | 100.0 / 0.0 | 0.0 / 50.0 | 0.0 / 100.0 | 0.0 / 75.0 |

### Baseline configurations

- **presidio**: presidio-analyzer 2.2.365, presidio-anonymizer 2.2.365, spacy 3.8.18
  - model: `en_core_web_lg 3.8.0 (en)`
  - model: `hu_core_news_lg 3.8.1 (hu, huSpaCy)`
  - unmapped labels (masked, not scored for P/R): `URL` x8
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
