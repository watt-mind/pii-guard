# pii-guard evaluation

- commit: `e394a0636ca0 (dirty)`, pii-guard 0.1.0
- detectors: `rules`
- fixtures: `eval/fixtures/en-smoke.jsonl` sha256 `5983d84d8dfc9fe3`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `en` | 10 | 34 | 16 | 87.5 | 41.2 | 56.0 | 100.0 | 47.1 | 64.0 | 66.7 | 46.7 | 13.3 | 0.0 | 100.0 | 53.3 | 0.17 | 0.24 |
| **overall** | 10 | 34 | 16 | 87.5 | 41.2 | 56.0 | 100.0 | 47.1 | 64.0 | 66.7 | 46.7 | 13.3 | 0.0 | 100.0 | 53.3 | 0.17 | 0.24 |

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

# pii-guard vs open-source baselines

All ratios in %. P/R/F1 are span-level micro averages over pii-guard's entity types (tool labels mapped as in docs/evaluation.md). Leak = labelled values of mask-policy types surviving the text each system would send upstream (its own masking). Latency is detection only.

## Fixtures: `en-smoke.jsonl`

- fixture sha256: `en-smoke.jsonl` `5983d84d8dfc9fe3`
- commit: `e394a0636ca0 (dirty)`

### `en`

| System | Docs | P overlap | R overlap | F1 overlap | F1 exact | Leak | Partial leak | Over-masking | Round trip | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| pii-guard rules | 10 | 100.0 | 47.1 | 64.0 | 56.0 | 46.7 | 13.3 | 0.0 | 100.0 | 0.2 | 0.2 |
| presidio | 10 | 61.9 | 76.5 | 68.4 | 65.8 | 10.0 | 13.3 | 26.2 | n/a | 7.3 | 23.1 |
| llm-guard | 10 | 100.0 | 61.8 | 76.4 | 31.7 | 30.0 | 13.3 | 0.0 | 100.0 | 60.2 | 83.9 |
| privaite | 10 | 70.7 | 79.4 | 74.8 | 61.3 | 0.0 | 13.3 | 22.0 | 100.0 | 56.7 | 63.9 |

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

### Baseline configurations

- **presidio**: presidio-analyzer 2.2.365, presidio-anonymizer 2.2.365, spacy 3.8.18
  - model: `en_core_web_lg 3.8.0 (en)`
  - model: `hu_core_news_lg 3.8.1 (hu, huSpaCy)`
  - unmapped labels (masked, not scored for P/R): `NRP` x1, `URL` x3
- **llm-guard**: llm-guard 0.3.16, presidio-analyzer 2.2.358, transformers 4.51.3, torch 2.14.1, spacy 3.8.18
  - model: `Isotonic/deberta-v3-base_finetuned_ai4privacy_v2@9ea992753ab2686be4a8f64605ccc7be197ad794`
  - model: `en_core_web_sm 3.8.0`
  - model: `zh_core_web_sm 3.8.0`
- **privaite**: privaite 0.7.3, presidio-analyzer 2.2.365, onnxruntime 1.31.1, transformers 5.21.0, spacy 3.8.18
  - model: `openai/privacy-filter@7ffa9a043d54d1be65afb281eddf0ffbe629385b (q4)`
  - model: `en_core_web_lg 3.8.0`
  - model: `fr_core_news_md 3.8.0`

Latency measured on arm64 (macOS-26.5.2-arm64-arm-64bit, 10 CPUs), CPU only, single process, after one warm-up call.
