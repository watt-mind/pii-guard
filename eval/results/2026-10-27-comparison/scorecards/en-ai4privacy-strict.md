# pii-guard evaluation

- commit: `688b940b05f3 (dirty)`, pii-guard 0.1.0
- detectors: `rules`, `ner`, `llm`
- fixtures: `eval/fixtures/public/en-ai4privacy.jsonl` sha256 `fcfc735dff402d7d`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `en` | 200 | 805 | 842 | 77.6 | 81.1 | 79.3 | 83.0 | 92.8 | 87.6 | 55.3 | 3.7 | 0.2 | 11.1 | 100.0 | 96.1 | 1905.13 | 3561.46 |
| **overall** | 200 | 805 | 842 | 77.6 | 81.1 | 79.3 | 83.0 | 92.8 | 87.6 | 55.3 | 3.7 | 0.2 | 11.1 | 100.0 | 96.1 | 1905.13 | 3561.46 |

## Per entity type: `en`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 205 | 213 | 96.2 | 100.0 | 98.1 | 96.2 | 100.0 | 98.1 | 0.0 | 0.0 |
| `ADDRESS` | 176 | 127 | 58.3 | 42.0 | 48.8 | 93.7 | 94.9 | 94.3 | 5.1 | 0.0 |
| `EMAIL` | 111 | 111 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `PHONE` | 85 | 101 | 82.2 | 97.6 | 89.2 | 83.2 | 98.8 | 90.3 | 1.2 | 1.2 |
| `DATE_OF_BIRTH` | 0 | 75 | 0.0 | - | 0.0 | 0.0 | - | 0.0 | keep | keep |
| `NATIONAL_ID_HU_TAX` | 0 | 1 | 0.0 | - | 0.0 | 0.0 | - | 0.0 | keep | keep |
| `ID_DOCUMENT` | 187 | 144 | 100.0 | 77.0 | 87.0 | 100.0 | 77.0 | 87.0 | 8.0 | 0.5 |
| `BANK_ACCOUNT` | 41 | 45 | 80.0 | 87.8 | 83.7 | 80.0 | 87.8 | 83.7 | 12.2 | 0.0 |
| `ORGANIZATION` | 0 | 23 | 0.0 | - | 0.0 | 0.0 | - | 0.0 | keep | keep |
| `VEHICLE_PLATE` | 0 | 2 | 0.0 | - | 0.0 | 0.0 | - | 0.0 | keep | keep |
| **all (micro)** | 805 | 842 | 77.6 | 81.1 | 79.3 | 83.0 | 92.8 | 87.6 | 3.7 | 0.2 |
