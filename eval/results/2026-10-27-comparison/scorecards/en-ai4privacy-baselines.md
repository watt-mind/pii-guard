# pii-guard evaluation

- commit: `8944f96f0da3 (dirty)`, pii-guard 0.1.0
- detectors: `rules`
- fixtures: `eval/fixtures/public/en-ai4privacy.jsonl` sha256 `fcfc735dff402d7d`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `en` | 200 | 805 | 203 | 95.1 | 24.0 | 38.3 | 95.6 | 24.1 | 38.5 | 29.5 | 74.7 | 0.4 | 0.5 | 100.0 | 25.1 | 0.26 | 0.77 |
| **overall** | 200 | 805 | 203 | 95.1 | 24.0 | 38.3 | 95.6 | 24.1 | 38.5 | 29.5 | 74.7 | 0.4 | 0.5 | 100.0 | 25.1 | 0.26 | 0.77 |

## Per entity type: `en`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 205 | 0 | - | 0.0 | 0.0 | - | 0.0 | 0.0 | 99.0 | 0.5 |
| `ADDRESS` | 176 | 10 | 90.0 | 5.1 | 9.7 | 90.0 | 5.1 | 9.7 | 94.9 | 0.0 |
| `EMAIL` | 111 | 111 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `PHONE` | 85 | 57 | 86.0 | 57.6 | 69.0 | 87.7 | 58.8 | 70.4 | 41.2 | 1.2 |
| `NATIONAL_ID_HU_TAX` | 0 | 1 | 0.0 | - | 0.0 | 0.0 | - | 0.0 | keep | keep |
| `ID_DOCUMENT` | 187 | 23 | 100.0 | 12.3 | 21.9 | 100.0 | 12.3 | 21.9 | 83.4 | 0.5 |
| `BANK_ACCOUNT` | 41 | 1 | 100.0 | 2.4 | 4.8 | 100.0 | 2.4 | 4.8 | 97.6 | 0.0 |
| **all (micro)** | 805 | 203 | 95.1 | 24.0 | 38.3 | 95.6 | 24.1 | 38.5 | 74.7 | 0.4 |

# pii-guard vs open-source baselines

All ratios in %. P/R/F1 are span-level micro averages over pii-guard's entity types (tool labels mapped as in docs/evaluation.md). Leak = labelled values of mask-policy types surviving the text each system would send upstream (its own masking). Latency is detection only.

## Fixtures: `en-ai4privacy.jsonl`

- fixture sha256: `en-ai4privacy.jsonl` `fcfc735dff402d7d`
- commit: `8944f96f0da3 (dirty)`

### `en`

| System | Docs | P overlap | R overlap | F1 overlap | F1 exact | Leak | Partial leak | Over-masking | Round trip | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| pii-guard rules | 200 | 95.6 | 24.1 | 38.5 | 38.3 | 74.7 | 0.4 | 0.5 | 100.0 | 0.3 | 0.8 |
| presidio | 200 | 38.5 | 48.3 | 42.8 | 33.0 | 22.5 | 9.9 | 37.2 | n/a | 9.3 | 25.1 |
| llm-guard | 200 | 96.5 | 51.6 | 67.2 | 15.9 | 46.1 | 1.0 | 1.1 | 100.0 | 61.3 | 123.6 |
| privaite | 200 | 57.1 | 68.6 | 62.3 | 39.4 | 7.7 | 1.1 | 22.7 | 99.5 | 131.8 | 294.2 |

Per entity type, `en`: overlap recall / leak rate (leak only for mask-policy types).

| Entity type | Gold | pii-guard rules | presidio | llm-guard | privaite |
|---|---:|---:|---:|---:|---:|
| `PERSON` | 205 | 0.0 / 99.0 | 73.2 / 18.0 | 96.6 / 2.9 | 92.7 / 5.9 |
| `ADDRESS` | 176 | 5.1 / 94.9 | 10.8 / 43.2 | 0.0 / 100.0 | 73.9 / 22.7 |
| `EMAIL` | 111 | 100.0 / 0.0 | 100.0 / 0.0 | 100.0 / 0.0 | 100.0 / 0.0 |
| `PHONE` | 85 | 58.8 / 41.2 | 36.5 / 23.5 | 98.8 / 1.2 | 97.6 / 1.2 |
| `ID_DOCUMENT` | 187 | 12.3 / 83.4 | 29.4 / 22.5 | 4.8 / 85.6 | 2.1 / 2.1 |
| `BANK_ACCOUNT` | 41 | 2.4 / 97.6 | 56.1 / 14.6 | 31.7 / 68.3 | 82.9 / 12.2 |

### Baseline configurations

- **presidio**: presidio-analyzer 2.2.365, presidio-anonymizer 2.2.365, spacy 3.8.18
  - model: `en_core_web_lg 3.8.0 (en)`
  - model: `hu_core_news_lg 3.8.1 (hu, huSpaCy)`
  - unmapped labels (masked, not scored for P/R): `MEDICAL_LICENSE` x1, `NRP` x11, `URL` x111
- **llm-guard**: llm-guard 0.3.16, presidio-analyzer 2.2.358, transformers 4.51.3, torch 2.14.1, spacy 3.8.18
  - model: `Isotonic/deberta-v3-base_finetuned_ai4privacy_v2@9ea992753ab2686be4a8f64605ccc7be197ad794`
  - model: `en_core_web_sm 3.8.0`
  - model: `zh_core_web_sm 3.8.0`
  - unmapped labels (masked, not scored for P/R): `CRYPTO` x2, `IP_ADDRESS` x3
- **privaite**: privaite 0.7.3, presidio-analyzer 2.2.365, onnxruntime 1.31.1, transformers 5.21.0, spacy 3.8.18
  - model: `openai/privacy-filter@7ffa9a043d54d1be65afb281eddf0ffbe629385b (q4)`
  - model: `en_core_web_lg 3.8.0`
  - model: `fr_core_news_md 3.8.0`

Latency measured on arm64 (macOS-26.5.2-arm64-arm-64bit, 10 CPUs), CPU only, single process, after one warm-up call.
