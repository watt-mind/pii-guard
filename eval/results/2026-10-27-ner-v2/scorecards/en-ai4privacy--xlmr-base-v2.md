# pii-guard evaluation

- commit: `b6e7bac54675 (dirty)`, pii-guard 0.1.0
- detectors: `rules`, `ner`
- fixtures: `eval/fixtures/public/en-ai4privacy.jsonl` sha256 `fcfc735dff402d7d`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `en` | 200 | 805 | 840 | 94.4 | 94.9 | 94.7 | 97.5 | 98.5 | 98.0 | 83.9 | 0.2 | 0.0 | 1.1 | 100.0 | 99.4 | 15.75 | 23.60 |
| **overall** | 200 | 805 | 840 | 94.4 | 94.9 | 94.7 | 97.5 | 98.5 | 98.0 | 83.9 | 0.2 | 0.0 | 1.1 | 100.0 | 99.4 | 15.75 | 23.60 |

## Per entity type: `en`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 205 | 209 | 98.1 | 100.0 | 99.0 | 98.1 | 100.0 | 99.0 | 0.0 | 0.0 |
| `ADDRESS` | 176 | 170 | 91.8 | 88.6 | 90.2 | 99.4 | 98.9 | 99.1 | 1.1 | 0.0 |
| `EMAIL` | 111 | 112 | 99.1 | 100.0 | 99.6 | 99.1 | 100.0 | 99.6 | 0.0 | 0.0 |
| `PHONE` | 85 | 93 | 81.7 | 89.4 | 85.4 | 91.4 | 98.8 | 95.0 | 0.0 | 0.0 |
| `NATIONAL_ID_HU_TAX` | 0 | 2 | 0.0 | - | 0.0 | 0.0 | - | 0.0 | keep | keep |
| `ID_DOCUMENT` | 187 | 180 | 97.8 | 94.1 | 95.9 | 98.9 | 95.2 | 97.0 | 0.0 | 0.0 |
| `BANK_ACCOUNT` | 41 | 43 | 93.0 | 97.6 | 95.2 | 95.3 | 100.0 | 97.6 | 0.0 | 0.0 |
| **all (micro)** | 805 | 809 | 94.4 | 94.9 | 94.7 | 97.5 | 98.5 | 98.0 | 0.2 | 0.0 |
