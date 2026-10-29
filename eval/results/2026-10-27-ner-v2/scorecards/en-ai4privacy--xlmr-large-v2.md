# pii-guard evaluation

- commit: `b6e7bac54675 (dirty)`, pii-guard 0.1.0
- detectors: `rules`, `ner`
- fixtures: `eval/fixtures/public/en-ai4privacy.jsonl` sha256 `fcfc735dff402d7d`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `en` | 200 | 805 | 876 | 94.7 | 95.3 | 95.0 | 98.0 | 98.8 | 98.4 | 84.2 | 0.0 | 0.0 | 0.4 | 100.0 | 99.4 | 29.83 | 47.69 |
| **overall** | 200 | 805 | 876 | 94.7 | 95.3 | 95.0 | 98.0 | 98.8 | 98.4 | 84.2 | 0.0 | 0.0 | 0.4 | 100.0 | 99.4 | 29.83 | 47.69 |

## Per entity type: `en`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 205 | 207 | 99.0 | 100.0 | 99.5 | 99.0 | 100.0 | 99.5 | 0.0 | 0.0 |
| `ADDRESS` | 176 | 171 | 94.7 | 92.0 | 93.4 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `EMAIL` | 111 | 111 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `PHONE` | 85 | 94 | 80.9 | 89.4 | 84.9 | 92.6 | 100.0 | 96.1 | 0.0 | 0.0 |
| `NATIONAL_ID_HU_TAX` | 0 | 3 | 0.0 | - | 0.0 | 0.0 | - | 0.0 | keep | keep |
| `ID_DOCUMENT` | 187 | 180 | 96.1 | 92.5 | 94.3 | 99.4 | 94.7 | 97.0 | 0.0 | 0.0 |
| `BANK_ACCOUNT` | 41 | 44 | 90.9 | 97.6 | 94.1 | 93.2 | 100.0 | 96.5 | 0.0 | 0.0 |
| **all (micro)** | 805 | 810 | 94.7 | 95.3 | 95.0 | 98.0 | 98.8 | 98.4 | 0.0 | 0.0 |
