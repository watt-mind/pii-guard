# pii-guard evaluation

- commit: `b6e7bac54675 (dirty)`, pii-guard 0.1.0
- detectors: `rules`, `ner_gliner`
- fixtures: `eval/fixtures/public/en-ai4privacy.jsonl` sha256 `fcfc735dff402d7d`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `en` | 200 | 805 | 822 | 91.2 | 91.7 | 91.4 | 93.9 | 95.0 | 94.5 | 63.9 | 0.7 | 0.1 | 1.0 | 100.0 | 98.9 | 112.89 | 288.54 |
| **overall** | 200 | 805 | 822 | 91.2 | 91.7 | 91.4 | 93.9 | 95.0 | 94.5 | 63.9 | 0.7 | 0.1 | 1.0 | 100.0 | 98.9 | 112.89 | 288.54 |

## Per entity type: `en`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 205 | 205 | 98.0 | 98.0 | 98.0 | 99.5 | 99.0 | 99.3 | 0.5 | 0.5 |
| `ADDRESS` | 176 | 170 | 92.4 | 89.2 | 90.8 | 97.1 | 97.2 | 97.1 | 2.3 | 0.0 |
| `EMAIL` | 111 | 112 | 99.1 | 100.0 | 99.6 | 99.1 | 100.0 | 99.6 | 0.0 | 0.0 |
| `PHONE` | 85 | 92 | 83.7 | 90.6 | 87.0 | 92.4 | 98.8 | 95.5 | 0.0 | 0.0 |
| `NATIONAL_ID_HU_TAX` | 0 | 17 | 0.0 | - | 0.0 | 0.0 | - | 0.0 | keep | keep |
| `NATIONAL_ID_HU_TAJ` | 0 | 2 | 0.0 | - | 0.0 | 0.0 | - | 0.0 | keep | keep |
| `ID_DOCUMENT` | 187 | 156 | 96.8 | 80.7 | 88.0 | 98.7 | 82.9 | 90.1 | 0.5 | 0.0 |
| `BANK_ACCOUNT` | 41 | 47 | 87.2 | 100.0 | 93.2 | 87.2 | 100.0 | 93.2 | 0.0 | 0.0 |
| `ORGANIZATION` | 0 | 8 | 0.0 | - | 0.0 | 0.0 | - | 0.0 | keep | keep |
| **all (micro)** | 805 | 809 | 91.2 | 91.7 | 91.4 | 93.9 | 95.0 | 94.5 | 0.7 | 0.1 |
