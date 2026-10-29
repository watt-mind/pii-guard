# pii-guard evaluation

- commit: `b6e7bac54675 (dirty)`, pii-guard 0.1.0
- detectors: `rules`, `ner_gliner`
- fixtures: `eval/fixtures/public/en-ai4privacy.jsonl` sha256 `fcfc735dff402d7d`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `en` | 200 | 805 | 829 | 54.8 | 51.4 | 53.0 | 79.6 | 74.8 | 77.1 | 50.7 | 21.7 | 5.5 | 6.2 | 100.0 | 75.7 | 99.65 | 201.87 |
| **overall** | 200 | 805 | 829 | 54.8 | 51.4 | 53.0 | 79.6 | 74.8 | 77.1 | 50.7 | 21.7 | 5.5 | 6.2 | 100.0 | 75.7 | 99.65 | 201.87 |

## Per entity type: `en`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 205 | 221 | 45.2 | 48.8 | 46.9 | 88.2 | 95.1 | 91.5 | 3.9 | 3.9 |
| `ADDRESS` | 176 | 134 | 34.3 | 26.1 | 29.7 | 97.8 | 75.0 | 84.9 | 24.4 | 19.9 |
| `EMAIL` | 111 | 116 | 95.7 | 100.0 | 97.8 | 95.7 | 100.0 | 97.8 | 0.0 | 0.0 |
| `PHONE` | 85 | 101 | 76.2 | 90.6 | 82.8 | 81.2 | 95.3 | 87.7 | 4.7 | 0.0 |
| `NATIONAL_ID_HU_TAX` | 0 | 10 | 0.0 | - | 0.0 | 0.0 | - | 0.0 | keep | keep |
| `NATIONAL_ID_HU_TAJ` | 0 | 1 | 0.0 | - | 0.0 | 0.0 | - | 0.0 | keep | keep |
| `ID_DOCUMENT` | 187 | 79 | 88.6 | 37.4 | 52.6 | 92.4 | 39.0 | 54.9 | 48.1 | 0.5 |
| `BANK_ACCOUNT` | 41 | 10 | 100.0 | 24.4 | 39.2 | 100.0 | 24.4 | 39.2 | 73.2 | 0.0 |
| `ORGANIZATION` | 0 | 84 | 0.0 | - | 0.0 | 0.0 | - | 0.0 | keep | keep |
| **all (micro)** | 805 | 756 | 54.8 | 51.4 | 53.0 | 79.6 | 74.8 | 77.1 | 21.7 | 5.5 |
