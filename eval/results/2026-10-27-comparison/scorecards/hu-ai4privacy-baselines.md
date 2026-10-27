# pii-guard evaluation

- commit: `e394a0636ca0 (dirty)`, pii-guard 0.1.0
- detectors: `rules`
- fixtures: `eval/fixtures/public/hu-ai4privacy.jsonl` sha256 `bd1901745c33316d`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `hu` | 200 | 752 | 209 | 91.4 | 25.4 | 39.8 | 100.0 | 27.8 | 43.5 | 34.0 | 72.2 | 2.4 | 0.0 | 100.0 | 27.8 | 0.20 | 0.61 |
| **overall** | 200 | 752 | 209 | 91.4 | 25.4 | 39.8 | 100.0 | 27.8 | 43.5 | 34.0 | 72.2 | 2.4 | 0.0 | 100.0 | 27.8 | 0.20 | 0.61 |

## Per entity type: `hu`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 195 | 0 | - | 0.0 | 0.0 | - | 0.0 | 0.0 | 100.0 | 0.0 |
| `ADDRESS` | 119 | 21 | 19.0 | 3.4 | 5.7 | 100.0 | 17.6 | 30.0 | 82.4 | 14.3 |
| `EMAIL` | 105 | 105 | 99.0 | 99.0 | 99.0 | 100.0 | 100.0 | 100.0 | 0.0 | 1.0 |
| `PHONE` | 88 | 23 | 100.0 | 26.1 | 41.4 | 100.0 | 26.1 | 41.4 | 73.9 | 0.0 |
| `NATIONAL_ID_HU_TAX` | 41 | 1 | 100.0 | 2.4 | 4.8 | 100.0 | 2.4 | 4.8 | 97.6 | 0.0 |
| `NATIONAL_ID_HU_TAJ` | 42 | 4 | 100.0 | 9.5 | 17.4 | 100.0 | 9.5 | 17.4 | 90.5 | 0.0 |
| `ID_DOCUMENT` | 104 | 51 | 100.0 | 49.0 | 65.8 | 100.0 | 49.0 | 65.8 | 51.0 | 0.0 |
| `BANK_ACCOUNT` | 58 | 4 | 100.0 | 6.9 | 12.9 | 100.0 | 6.9 | 12.9 | 93.1 | 0.0 |
| **all (micro)** | 752 | 209 | 91.4 | 25.4 | 39.8 | 100.0 | 27.8 | 43.5 | 72.2 | 2.4 |

# pii-guard vs open-source baselines

All ratios in %. P/R/F1 are span-level micro averages over pii-guard's entity types (tool labels mapped as in docs/evaluation.md). Leak = labelled values of mask-policy types surviving the text each system would send upstream (its own masking). Latency is detection only.

## Fixtures: `hu-ai4privacy.jsonl`

- fixture sha256: `hu-ai4privacy.jsonl` `bd1901745c33316d`
- commit: `e394a0636ca0 (dirty)`

### `hu`

| System | Docs | P overlap | R overlap | F1 overlap | F1 exact | Leak | Partial leak | Over-masking | Round trip | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| pii-guard rules | 200 | 100.0 | 27.8 | 43.5 | 39.8 | 72.2 | 2.4 | 0.0 | 100.0 | 0.2 | 0.6 |
| presidio | 200 | 54.1 | 44.9 | 49.1 | 29.3 | 46.1 | 5.7 | 35.1 | n/a | 86.2 | 202.3 |
| llm-guard | 200 | 60.2 | 52.8 | 56.3 | 9.9 | 44.7 | 2.9 | 37.7 | 100.0 | 62.5 | 115.1 |
| privaite | 200 | 48.4 | 59.8 | 53.5 | 35.1 | 14.0 | 3.5 | 29.0 | 98.0 | 74.9 | 187.5 |

Per entity type, `hu`: overlap recall / leak rate (leak only for mask-policy types).

| Entity type | Gold | pii-guard rules | presidio | llm-guard | privaite |
|---|---:|---:|---:|---:|---:|
| `PERSON` | 195 | 0.0 / 100.0 | 70.8 / 17.9 | 94.9 / 3.6 | 80.0 / 17.4 |
| `ADDRESS` | 119 | 17.6 / 82.4 | 52.9 / 47.1 | 0.0 / 98.3 | 43.7 / 46.2 |
| `EMAIL` | 105 | 100.0 / 0.0 | 100.0 / 0.0 | 100.0 / 0.0 | 100.0 / 0.0 |
| `PHONE` | 88 | 26.1 / 73.9 | 36.4 / 62.5 | 100.0 / 0.0 | 94.3 / 0.0 |
| `NATIONAL_ID_HU_TAX` | 41 | 2.4 / 97.6 | 0.0 / 26.8 | 0.0 / 92.7 | 0.0 / 0.0 |
| `NATIONAL_ID_HU_TAJ` | 42 | 9.5 / 90.5 | 0.0 / 85.7 | 0.0 / 76.2 | 0.0 / 4.8 |
| `ID_DOCUMENT` | 104 | 49.0 / 51.0 | 0.0 / 92.3 | 0.0 / 100.0 | 0.0 / 12.5 |
| `BANK_ACCOUNT` | 58 | 6.9 / 93.1 | 0.0 / 100.0 | 32.8 / 65.5 | 93.1 / 1.7 |

### Baseline configurations

- **presidio**: presidio-analyzer 2.2.365, presidio-anonymizer 2.2.365, spacy 3.8.18
  - model: `en_core_web_lg 3.8.0 (en)`
  - model: `hu_core_news_lg 3.8.1 (hu, huSpaCy)`
  - unmapped labels (masked, not scored for P/R): `URL` x105
- **llm-guard**: llm-guard 0.3.16, presidio-analyzer 2.2.358, transformers 4.51.3, torch 2.14.1, spacy 3.8.18
  - model: `Isotonic/deberta-v3-base_finetuned_ai4privacy_v2@9ea992753ab2686be4a8f64605ccc7be197ad794`
  - model: `en_core_web_sm 3.8.0`
  - model: `zh_core_web_sm 3.8.0`
  - unmapped labels (masked, not scored for P/R): `CRYPTO` x3, `IP_ADDRESS` x6
- **privaite**: privaite 0.7.3, presidio-analyzer 2.2.365, onnxruntime 1.31.1, transformers 5.21.0, spacy 3.8.18
  - model: `openai/privacy-filter@7ffa9a043d54d1be65afb281eddf0ffbe629385b (q4)`
  - model: `en_core_web_lg 3.8.0`
  - model: `fr_core_news_md 3.8.0`
  - unmapped labels (masked, not scored for P/R): `SECRET` x3

Latency measured on arm64 (macOS-26.5.2-arm64-arm-64bit, 10 CPUs), CPU only, single process, after one warm-up call.
