# pii-guard evaluation

- commit: `477196a3427c (dirty)`, pii-guard 0.1.0
- detectors: `rules`, `ner`
- fixtures: `eval/fixtures/public/en-ai4privacy.jsonl` sha256 `fcfc735dff402d7d`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `en` | 200 | 805 | 900 | 90.7 | 91.3 | 91.0 | 94.7 | 95.8 | 95.2 | 70.8 | 0.7 | 0.4 | 1.5 | 100.0 | 98.8 | 13.29 | 23.17 |
| **overall** | 200 | 805 | 900 | 90.7 | 91.3 | 91.0 | 94.7 | 95.8 | 95.2 | 70.8 | 0.7 | 0.4 | 1.5 | 100.0 | 98.8 | 13.29 | 23.17 |

## Per entity type: `en`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 205 | 212 | 95.3 | 98.5 | 96.9 | 96.7 | 100.0 | 98.3 | 0.0 | 0.0 |
| `ADDRESS` | 176 | 168 | 89.3 | 85.2 | 87.2 | 98.8 | 97.7 | 98.3 | 1.7 | 1.7 |
| `EMAIL` | 111 | 112 | 99.1 | 100.0 | 99.6 | 99.1 | 100.0 | 99.6 | 0.0 | 0.0 |
| `PHONE` | 85 | 94 | 80.9 | 89.4 | 84.9 | 90.4 | 98.8 | 94.4 | 0.0 | 0.0 |
| `NATIONAL_ID_HU_TAX` | 0 | 5 | 0.0 | — | 0.0 | 0.0 | — | 0.0 | keep | keep |
| `ID_DOCUMENT` | 187 | 161 | 96.9 | 83.4 | 89.7 | 98.8 | 84.5 | 91.1 | 1.6 | 0.0 |
| `BANK_ACCOUNT` | 41 | 56 | 71.4 | 97.6 | 82.5 | 73.2 | 100.0 | 84.5 | 0.0 | 0.0 |
| `ORGANIZATION` | 0 | 2 | 0.0 | — | 0.0 | 0.0 | — | 0.0 | keep | keep |
| **all (micro)** | 805 | 810 | 90.7 | 91.3 | 91.0 | 94.7 | 95.8 | 95.2 | 0.7 | 0.4 |
