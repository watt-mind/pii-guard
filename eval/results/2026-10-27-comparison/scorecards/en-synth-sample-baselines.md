# pii-guard evaluation

- commit: `e394a0636ca0 (dirty)`, pii-guard 0.1.0
- detectors: `rules`
- fixtures: `eval/fixtures/en-synth-sample.jsonl` sha256 `2c7ab3d12880065d`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `en` | 10 | 120 | 45 | 62.2 | 23.3 | 33.9 | 100.0 | 37.5 | 54.5 | 66.7 | 46.2 | 25.0 | 0.0 | 100.0 | 53.8 | 1.69 | 12.22 |
| **overall** | 10 | 120 | 45 | 62.2 | 23.3 | 33.9 | 100.0 | 37.5 | 54.5 | 66.7 | 46.2 | 25.0 | 0.0 | 100.0 | 53.8 | 1.69 | 12.22 |

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

# pii-guard vs open-source baselines

All ratios in %. P/R/F1 are span-level micro averages over pii-guard's entity types (tool labels mapped as in docs/evaluation.md). Leak = labelled values of mask-policy types surviving the text each system would send upstream (its own masking). Latency is detection only.

## Fixtures: `en-synth-sample.jsonl`

- fixture sha256: `en-synth-sample.jsonl` `2c7ab3d12880065d`
- commit: `e394a0636ca0 (dirty)`

### `en`

| System | Docs | P overlap | R overlap | F1 overlap | F1 exact | Leak | Partial leak | Over-masking | Round trip | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| pii-guard rules | 10 | 100.0 | 37.5 | 54.5 | 33.9 | 46.2 | 25.0 | 0.0 | 100.0 | 1.7 | 12.2 |
| presidio | 10 | 50.5 | 83.3 | 62.9 | 47.2 | 11.2 | 26.2 | 44.6 | n/a | 32.1 | 80.2 |
| llm-guard | 10 | 98.4 | 46.7 | 63.3 | 36.3 | 48.8 | 13.8 | 1.6 | 100.0 | 107.9 | 306.7 |
| privaite | 10 | 73.1 | 80.8 | 76.8 | 66.1 | 7.5 | 3.8 | 21.6 | 100.0 | 157.5 | 330.7 |

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

### Baseline configurations

- **presidio**: presidio-analyzer 2.2.365, presidio-anonymizer 2.2.365, spacy 3.8.18
  - model: `en_core_web_lg 3.8.0 (en)`
  - model: `hu_core_news_lg 3.8.1 (hu, huSpaCy)`
  - unmapped labels (masked, not scored for P/R): `URL` x5
- **llm-guard**: llm-guard 0.3.16, presidio-analyzer 2.2.358, transformers 4.51.3, torch 2.14.1, spacy 3.8.18
  - model: `Isotonic/deberta-v3-base_finetuned_ai4privacy_v2@9ea992753ab2686be4a8f64605ccc7be197ad794`
  - model: `en_core_web_sm 3.8.0`
  - model: `zh_core_web_sm 3.8.0`
- **privaite**: privaite 0.7.3, presidio-analyzer 2.2.365, onnxruntime 1.31.1, transformers 5.21.0, spacy 3.8.18
  - model: `openai/privacy-filter@7ffa9a043d54d1be65afb281eddf0ffbe629385b (q4)`
  - model: `en_core_web_lg 3.8.0`
  - model: `fr_core_news_md 3.8.0`

Latency measured on arm64 (macOS-26.5.2-arm64-arm-64bit, 10 CPUs), CPU only, single process, after one warm-up call.
