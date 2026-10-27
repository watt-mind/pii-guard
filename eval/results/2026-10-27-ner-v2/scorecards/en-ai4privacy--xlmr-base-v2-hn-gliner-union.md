# pii-guard evaluation

- commit: `b6e7bac54675 (dirty)`, pii-guard 0.1.0
- detectors: `rules`, `ner`, `ner_gliner`
- fixtures: `eval/fixtures/public/en-ai4privacy.jsonl` sha256 `fcfc735dff402d7d`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `en` | 200 | 805 | 1019 | 69.1 | 78.5 | 73.5 | 84.5 | 98.1 | 90.8 | 71.6 | 0.2 | 0.0 | 5.8 | 100.0 | 99.6 | 132.45 | 319.51 |
| **overall** | 200 | 805 | 1019 | 69.1 | 78.5 | 73.5 | 84.5 | 98.1 | 90.8 | 71.6 | 0.2 | 0.0 | 5.8 | 100.0 | 99.6 | 132.45 | 319.51 |

## Per entity type: `en`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 205 | 234 | 48.7 | 55.6 | 51.9 | 87.6 | 100.0 | 93.4 | 0.0 | 0.0 |
| `ADDRESS` | 176 | 158 | 75.9 | 68.2 | 71.9 | 98.1 | 98.9 | 98.5 | 1.1 | 0.0 |
| `EMAIL` | 111 | 116 | 95.7 | 100.0 | 97.8 | 95.7 | 100.0 | 97.8 | 0.0 | 0.0 |
| `PHONE` | 85 | 95 | 80.0 | 89.4 | 84.4 | 89.5 | 98.8 | 93.9 | 0.0 | 0.0 |
| `NATIONAL_ID_HU_TAX` | 0 | 1 | 0.0 | - | 0.0 | 0.0 | - | 0.0 | keep | keep |
| `ID_DOCUMENT` | 187 | 183 | 93.4 | 91.4 | 92.4 | 95.6 | 93.6 | 94.6 | 0.0 | 0.0 |
| `BANK_ACCOUNT` | 41 | 46 | 87.0 | 97.6 | 92.0 | 89.1 | 100.0 | 94.3 | 0.0 | 0.0 |
| `ORGANIZATION` | 0 | 81 | 0.0 | - | 0.0 | 0.0 | - | 0.0 | keep | keep |
| **all (micro)** | 805 | 914 | 69.1 | 78.5 | 73.5 | 84.5 | 98.1 | 90.8 | 0.2 | 0.0 |
