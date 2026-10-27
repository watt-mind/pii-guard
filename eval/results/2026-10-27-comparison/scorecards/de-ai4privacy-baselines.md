# pii-guard evaluation

- commit: `8944f96f0da3 (dirty)`, pii-guard 0.1.0
- detectors: `rules`
- fixtures: `eval/fixtures/public/de-ai4privacy.jsonl` sha256 `d0005390afa5e1a6`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `de` | 200 | 628 | 167 | 92.8 | 24.7 | 39.0 | 98.2 | 26.1 | 41.3 | 39.0 | 73.4 | 1.4 | 0.0 | 100.0 | 26.6 | 0.20 | 0.58 |
| **overall** | 200 | 628 | 167 | 92.8 | 24.7 | 39.0 | 98.2 | 26.1 | 41.3 | 39.0 | 73.4 | 1.4 | 0.0 | 100.0 | 26.6 | 0.20 | 0.58 |

## Per entity type: `de`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 182 | 0 | - | 0.0 | 0.0 | - | 0.0 | 0.0 | 100.0 | 0.0 |
| `ADDRESS` | 84 | 20 | 55.0 | 13.1 | 21.2 | 100.0 | 23.8 | 38.5 | 76.2 | 9.5 |
| `EMAIL` | 99 | 99 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `PHONE` | 64 | 38 | 92.1 | 54.7 | 68.6 | 92.1 | 54.7 | 68.6 | 45.3 | 0.0 |
| `ID_DOCUMENT` | 156 | 5 | 100.0 | 3.2 | 6.2 | 100.0 | 3.2 | 6.2 | 94.9 | 0.6 |
| `BANK_ACCOUNT` | 43 | 5 | 100.0 | 11.6 | 20.8 | 100.0 | 11.6 | 20.8 | 88.4 | 0.0 |
| **all (micro)** | 628 | 167 | 92.8 | 24.7 | 39.0 | 98.2 | 26.1 | 41.3 | 73.4 | 1.4 |

# pii-guard vs open-source baselines

All ratios in %. P/R/F1 are span-level micro averages over pii-guard's entity types (tool labels mapped as in docs/evaluation.md). Leak = labelled values of mask-policy types surviving the text each system would send upstream (its own masking). Latency is detection only.

## Fixtures: `de-ai4privacy.jsonl`

- fixture sha256: `de-ai4privacy.jsonl` `d0005390afa5e1a6`
- commit: `8944f96f0da3 (dirty)`

### `de`

| System | Docs | P overlap | R overlap | F1 overlap | F1 exact | Leak | Partial leak | Over-masking | Round trip | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| pii-guard rules | 200 | 98.2 | 26.1 | 41.3 | 39.0 | 73.4 | 1.4 | 0.0 | 100.0 | 0.2 | 0.6 |
| presidio | 200 | 20.3 | 56.5 | 29.8 | 18.8 | 18.9 | 7.6 | 70.2 | n/a | 7.6 | 17.1 |
| llm-guard | 200 | 92.4 | 57.5 | 70.9 | 14.7 | 39.8 | 1.6 | 4.6 | 100.0 | 67.5 | 209.2 |
| privaite | 200 | 52.3 | 68.0 | 59.1 | 37.0 | 6.5 | 3.2 | 28.1 | 96.5 | 92.7 | 203.7 |

Per entity type, `de`: overlap recall / leak rate (leak only for mask-policy types).

| Entity type | Gold | pii-guard rules | presidio | llm-guard | privaite |
|---|---:|---:|---:|---:|---:|
| `PERSON` | 182 | 0.0 / 100.0 | 70.3 / 17.6 | 98.9 / 1.1 | 84.1 / 14.3 |
| `ADDRESS` | 84 | 23.8 / 76.2 | 9.5 / 38.1 | 0.0 / 95.2 | 82.1 / 14.3 |
| `EMAIL` | 99 | 100.0 / 0.0 | 99.0 / 0.0 | 100.0 / 0.0 | 100.0 / 0.0 |
| `PHONE` | 64 | 54.7 / 45.3 | 42.2 / 15.6 | 100.0 / 0.0 | 96.9 / 0.0 |
| `ID_DOCUMENT` | 156 | 3.2 / 94.9 | 39.1 / 27.6 | 0.0 / 92.9 | 1.9 / 1.9 |
| `BANK_ACCOUNT` | 43 | 11.6 / 88.4 | 76.7 / 4.7 | 41.9 / 53.5 | 95.3 / 0.0 |

### Baseline configurations

- **presidio**: presidio-analyzer 2.2.365, presidio-anonymizer 2.2.365, spacy 3.8.18
  - model: `en_core_web_lg 3.8.0 (en)`
  - model: `hu_core_news_lg 3.8.1 (hu, huSpaCy)`
  - unmapped labels (masked, not scored for P/R): `NRP` x35, `URL` x100
- **llm-guard**: llm-guard 0.3.16, presidio-analyzer 2.2.358, transformers 4.51.3, torch 2.14.1, spacy 3.8.18
  - model: `Isotonic/deberta-v3-base_finetuned_ai4privacy_v2@9ea992753ab2686be4a8f64605ccc7be197ad794`
  - model: `en_core_web_sm 3.8.0`
  - model: `zh_core_web_sm 3.8.0`
- **privaite**: privaite 0.7.3, presidio-analyzer 2.2.365, onnxruntime 1.31.1, transformers 5.21.0, spacy 3.8.18
  - model: `openai/privacy-filter@7ffa9a043d54d1be65afb281eddf0ffbe629385b (q4)`
  - model: `en_core_web_lg 3.8.0`
  - model: `fr_core_news_md 3.8.0`
  - unmapped labels (masked, not scored for P/R): `SECRET` x2, `URL` x2

Latency measured on arm64 (macOS-26.5.2-arm64-arm-64bit, 10 CPUs), CPU only, single process, after one warm-up call.
