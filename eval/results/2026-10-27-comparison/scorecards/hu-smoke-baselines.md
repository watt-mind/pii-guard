# pii-guard evaluation

- commit: `e394a0636ca0 (dirty)`, pii-guard 0.1.0
- detectors: `rules`
- fixtures: `eval/fixtures/hu-smoke.jsonl` sha256 `3766a651708e8749`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `hu` | 31 | 120 | 67 | 100.0 | 55.8 | 71.7 | 100.0 | 55.8 | 71.7 | 76.9 | 40.6 | 3.8 | 0.0 | 100.0 | 59.4 | 0.17 | 0.39 |
| **overall** | 31 | 120 | 67 | 100.0 | 55.8 | 71.7 | 100.0 | 55.8 | 71.7 | 76.9 | 40.6 | 3.8 | 0.0 | 100.0 | 59.4 | 0.17 | 0.39 |

## Per entity type: `hu`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 38 | 0 | - | 0.0 | 0.0 | - | 0.0 | 0.0 | 100.0 | 0.0 |
| `ADDRESS` | 13 | 13 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `EMAIL` | 6 | 6 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 50.0 |
| `PHONE` | 7 | 7 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `DATE_OF_BIRTH` | 6 | 0 | - | 0.0 | 0.0 | - | 0.0 | 0.0 | 100.0 | 0.0 |
| `NATIONAL_ID_HU_TAX` | 5 | 5 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `NATIONAL_ID_HU_TAJ` | 5 | 5 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `ID_DOCUMENT` | 10 | 10 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 10.0 |
| `BANK_ACCOUNT` | 6 | 6 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `COMPANY_ID_HU` | 4 | 4 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | keep | keep |
| `ORGANIZATION` | 9 | 0 | - | 0.0 | 0.0 | - | 0.0 | 0.0 | keep | keep |
| `PARCEL_NUMBER_HU` | 6 | 6 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `VEHICLE_PLATE` | 5 | 5 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| **all (micro)** | 120 | 67 | 100.0 | 55.8 | 71.7 | 100.0 | 55.8 | 71.7 | 40.6 | 3.8 |

# pii-guard vs open-source baselines

All ratios in %. P/R/F1 are span-level micro averages over pii-guard's entity types (tool labels mapped as in docs/evaluation.md). Leak = labelled values of mask-policy types surviving the text each system would send upstream (its own masking). Latency is detection only.

## Fixtures: `hu-smoke.jsonl`

- fixture sha256: `hu-smoke.jsonl` `3766a651708e8749`
- commit: `e394a0636ca0 (dirty)`

### `hu`

| System | Docs | P overlap | R overlap | F1 overlap | F1 exact | Leak | Partial leak | Over-masking | Round trip | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| pii-guard rules | 31 | 100.0 | 55.8 | 71.7 | 71.7 | 40.6 | 3.8 | 0.0 | 100.0 | 0.2 | 0.4 |
| presidio | 31 | 74.8 | 61.7 | 67.6 | 46.8 | 33.0 | 12.3 | 17.4 | n/a | 78.7 | 135.4 |
| llm-guard | 31 | 53.0 | 41.7 | 46.7 | 4.5 | 50.0 | 5.7 | 45.2 | 100.0 | 71.9 | 110.4 |
| privaite | 31 | 42.8 | 50.8 | 46.5 | 22.2 | 17.9 | 9.4 | 28.3 | 96.8 | 73.5 | 109.2 |

Per entity type, `hu`: overlap recall / leak rate (leak only for mask-policy types).

| Entity type | Gold | pii-guard rules | presidio | llm-guard | privaite |
|---|---:|---:|---:|---:|---:|
| `PERSON` | 38 | 0.0 / 100.0 | 97.4 / 2.7 | 89.5 / 10.8 | 68.4 / 27.0 |
| `ADDRESS` | 13 | 100.0 / 0.0 | 100.0 / 0.0 | 0.0 / 92.3 | 100.0 / 0.0 |
| `EMAIL` | 6 | 100.0 / 0.0 | 83.3 / 0.0 | 100.0 / 0.0 | 100.0 / 0.0 |
| `PHONE` | 7 | 100.0 / 0.0 | 100.0 / 0.0 | 100.0 / 0.0 | 100.0 / 0.0 |
| `DATE_OF_BIRTH` | 6 | 0.0 / 100.0 | 0.0 / 100.0 | 0.0 / 100.0 | 50.0 / 16.7 |
| `NATIONAL_ID_HU_TAX` | 5 | 100.0 / 0.0 | 0.0 / 0.0 | 0.0 / 100.0 | 0.0 / 0.0 |
| `NATIONAL_ID_HU_TAJ` | 5 | 100.0 / 0.0 | 0.0 / 100.0 | 0.0 / 100.0 | 0.0 / 0.0 |
| `ID_DOCUMENT` | 10 | 100.0 / 0.0 | 0.0 / 100.0 | 0.0 / 80.0 | 0.0 / 0.0 |
| `BANK_ACCOUNT` | 6 | 100.0 / 0.0 | 50.0 / 50.0 | 50.0 / 33.3 | 100.0 / 0.0 |
| `COMPANY_ID_HU` | 4 | 100.0 | 0.0 | 0.0 | 0.0 |
| `ORGANIZATION` | 9 | 0.0 | 100.0 | 0.0 | 0.0 |
| `PARCEL_NUMBER_HU` | 6 | 100.0 / 0.0 | 0.0 / 100.0 | 0.0 / 100.0 | 0.0 / 50.0 |
| `VEHICLE_PLATE` | 5 | 100.0 / 0.0 | 0.0 / 80.0 | 0.0 / 100.0 | 0.0 / 100.0 |

### Baseline configurations

- **presidio**: presidio-analyzer 2.2.365, presidio-anonymizer 2.2.365, spacy 3.8.18
  - model: `en_core_web_lg 3.8.0 (en)`
  - model: `hu_core_news_lg 3.8.1 (hu, huSpaCy)`
  - unmapped labels (masked, not scored for P/R): `URL` x7
- **llm-guard**: llm-guard 0.3.16, presidio-analyzer 2.2.358, transformers 4.51.3, torch 2.14.1, spacy 3.8.18
  - model: `Isotonic/deberta-v3-base_finetuned_ai4privacy_v2@9ea992753ab2686be4a8f64605ccc7be197ad794`
  - model: `en_core_web_sm 3.8.0`
  - model: `zh_core_web_sm 3.8.0`
  - unmapped labels (masked, not scored for P/R): `CRYPTO` x1
- **privaite**: privaite 0.7.3, presidio-analyzer 2.2.365, onnxruntime 1.31.1, transformers 5.21.0, spacy 3.8.18
  - model: `openai/privacy-filter@7ffa9a043d54d1be65afb281eddf0ffbe629385b (q4)`
  - model: `en_core_web_lg 3.8.0`
  - model: `fr_core_news_md 3.8.0`
  - unmapped labels (masked, not scored for P/R): `SECRET` x1, `URL` x2

Latency measured on arm64 (macOS-26.5.2-arm64-arm-64bit, 10 CPUs), CPU only, single process, after one warm-up call.
