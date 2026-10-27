# pii-guard evaluation

- commit: `e394a0636ca0 (dirty)`, pii-guard 0.1.0
- detectors: `rules`, `ner`
- fixtures: `eval/fixtures/public/en-ai4privacy.jsonl` sha256 `fcfc735dff402d7d`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `en` | 200 | 805 | 666 | 61.7 | 51.1 | 55.9 | 82.7 | 64.1 | 72.2 | 41.6 | 34.8 | 1.9 | 12.8 | 100.0 | 59.0 | 30.38 | 52.63 |
| **overall** | 200 | 805 | 666 | 61.7 | 51.1 | 55.9 | 82.7 | 64.1 | 72.2 | 41.6 | 34.8 | 1.9 | 12.8 | 100.0 | 59.0 | 30.38 | 52.63 |

## Per entity type: `en`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 205 | 271 | 58.3 | 77.1 | 66.4 | 95.6 | 100.0 | 97.7 | 0.0 | 3.9 |
| `ADDRESS` | 176 | 120 | 57.5 | 39.2 | 46.6 | 89.2 | 71.6 | 79.4 | 27.8 | 2.8 |
| `EMAIL` | 111 | 111 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `PHONE` | 85 | 57 | 86.0 | 57.6 | 69.0 | 87.7 | 58.8 | 70.4 | 41.2 | 1.2 |
| `DATE_OF_BIRTH` | 0 | 62 | 0.0 | - | 0.0 | 0.0 | - | 0.0 | keep | keep |
| `NATIONAL_ID_HU_TAX` | 0 | 1 | 0.0 | - | 0.0 | 0.0 | - | 0.0 | keep | keep |
| `ID_DOCUMENT` | 187 | 23 | 100.0 | 12.3 | 21.9 | 100.0 | 12.3 | 21.9 | 83.4 | 0.5 |
| `BANK_ACCOUNT` | 41 | 1 | 100.0 | 2.4 | 4.8 | 100.0 | 2.4 | 4.8 | 97.6 | 0.0 |
| `ORGANIZATION` | 0 | 20 | 0.0 | - | 0.0 | 0.0 | - | 0.0 | keep | keep |
| **all (micro)** | 805 | 666 | 61.7 | 51.1 | 55.9 | 82.7 | 64.1 | 72.2 | 34.8 | 1.9 |
