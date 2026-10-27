# pii-guard evaluation

- commit: `e394a0636ca0 (dirty)`, pii-guard 0.1.0
- detectors: `rules`
- fixtures: `eval/fixtures/de-smoke.jsonl` sha256 `b623ca3b33af7ef7`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `de` | 10 | 40 | 22 | 90.9 | 50.0 | 64.5 | 100.0 | 52.5 | 68.9 | 62.5 | 43.2 | 8.1 | 0.0 | 100.0 | 54.1 | 0.19 | 0.32 |
| **overall** | 10 | 40 | 22 | 90.9 | 50.0 | 64.5 | 100.0 | 52.5 | 68.9 | 62.5 | 43.2 | 8.1 | 0.0 | 100.0 | 54.1 | 0.19 | 0.32 |

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

# pii-guard vs open-source baselines

All ratios in %. P/R/F1 are span-level micro averages over pii-guard's entity types (tool labels mapped as in docs/evaluation.md). Leak = labelled values of mask-policy types surviving the text each system would send upstream (its own masking). Latency is detection only.

## Fixtures: `de-smoke.jsonl`

- fixture sha256: `de-smoke.jsonl` `b623ca3b33af7ef7`
- commit: `e394a0636ca0 (dirty)`

### `de`

| System | Docs | P overlap | R overlap | F1 overlap | F1 exact | Leak | Partial leak | Over-masking | Round trip | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| pii-guard rules | 10 | 100.0 | 52.5 | 68.9 | 64.5 | 43.2 | 8.1 | 0.0 | 100.0 | 0.2 | 0.3 |
| presidio | 10 | 43.1 | 77.5 | 55.4 | 39.3 | 10.8 | 10.8 | 44.4 | n/a | 7.0 | 18.1 |
| llm-guard | 10 | 97.1 | 50.0 | 66.0 | 16.0 | 43.2 | 10.8 | 0.0 | 100.0 | 68.3 | 106.5 |
| privaite | 10 | 62.5 | 70.0 | 66.0 | 47.7 | 8.1 | 8.1 | 20.8 | 100.0 | 52.8 | 71.7 |

Per entity type, `de`: overlap recall / leak rate (leak only for mask-policy types).

| Entity type | Gold | pii-guard rules | presidio | llm-guard | privaite |
|---|---:|---:|---:|---:|---:|
| `PERSON` | 13 | 0.0 / 100.0 | 84.6 / 15.4 | 76.9 / 23.1 | 76.9 / 23.1 |
| `ADDRESS` | 5 | 100.0 / 0.0 | 100.0 / 0.0 | 0.0 / 100.0 | 100.0 / 0.0 |
| `EMAIL` | 3 | 100.0 / 0.0 | 100.0 / 0.0 | 100.0 / 0.0 | 100.0 / 0.0 |
| `PHONE` | 5 | 100.0 / 0.0 | 80.0 / 0.0 | 100.0 / 0.0 | 100.0 / 0.0 |
| `DATE_OF_BIRTH` | 3 | 0.0 / 100.0 | 100.0 / 0.0 | 0.0 / 100.0 | 100.0 / 0.0 |
| `ID_DOCUMENT` | 6 | 100.0 / 0.0 | 16.7 / 33.3 | 0.0 / 83.3 | 0.0 / 0.0 |
| `BANK_ACCOUNT` | 2 | 100.0 / 0.0 | 100.0 / 0.0 | 100.0 / 0.0 | 100.0 / 0.0 |
| `ORGANIZATION` | 3 | 0.0 | 66.7 | 0.0 | 0.0 |

### Baseline configurations

- **presidio**: presidio-analyzer 2.2.365, presidio-anonymizer 2.2.365, spacy 3.8.18
  - model: `en_core_web_lg 3.8.0 (en)`
  - model: `hu_core_news_lg 3.8.1 (hu, huSpaCy)`
  - unmapped labels (masked, not scored for P/R): `URL` x6
- **llm-guard**: llm-guard 0.3.16, presidio-analyzer 2.2.358, transformers 4.51.3, torch 2.14.1, spacy 3.8.18
  - model: `Isotonic/deberta-v3-base_finetuned_ai4privacy_v2@9ea992753ab2686be4a8f64605ccc7be197ad794`
  - model: `en_core_web_sm 3.8.0`
  - model: `zh_core_web_sm 3.8.0`
- **privaite**: privaite 0.7.3, presidio-analyzer 2.2.365, onnxruntime 1.31.1, transformers 5.21.0, spacy 3.8.18
  - model: `openai/privacy-filter@7ffa9a043d54d1be65afb281eddf0ffbe629385b (q4)`
  - model: `en_core_web_lg 3.8.0`
  - model: `fr_core_news_md 3.8.0`

Latency measured on arm64 (macOS-26.5.2-arm64-arm-64bit, 10 CPUs), CPU only, single process, after one warm-up call.
