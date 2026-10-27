# pii-guard evaluation

- commit: `b6e7bac54675 (dirty)`, pii-guard 0.1.0
- detectors: `rules`, `ner`
- fixtures: `eval/fixtures/public/en-ai4privacy.jsonl` sha256 `fcfc735dff402d7d`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `en` | 200 | 805 | 848 | 94.4 | 94.7 | 94.5 | 97.3 | 97.6 | 97.5 | 83.4 | 0.2 | 0.0 | 0.4 | 100.0 | 99.3 | 38.19 | 73.32 |
| **overall** | 200 | 805 | 848 | 94.4 | 94.7 | 94.5 | 97.3 | 97.6 | 97.5 | 83.4 | 0.2 | 0.0 | 0.4 | 100.0 | 99.3 | 38.19 | 73.32 |

## Per entity type: `en`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 205 | 207 | 98.6 | 99.5 | 99.0 | 99.0 | 100.0 | 99.5 | 0.0 | 0.0 |
| `ADDRESS` | 176 | 171 | 95.3 | 92.6 | 93.9 | 100.0 | 98.9 | 99.4 | 1.1 | 0.0 |
| `EMAIL` | 111 | 111 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `PHONE` | 85 | 92 | 82.6 | 89.4 | 85.9 | 92.4 | 98.8 | 95.5 | 0.0 | 0.0 |
| `NATIONAL_ID_HU_TAX` | 0 | 7 | 0.0 | - | 0.0 | 0.0 | - | 0.0 | keep | keep |
| `ID_DOCUMENT` | 187 | 173 | 97.1 | 89.8 | 93.3 | 99.4 | 91.4 | 95.3 | 0.0 | 0.0 |
| `BANK_ACCOUNT` | 41 | 46 | 87.0 | 97.6 | 92.0 | 89.1 | 100.0 | 94.3 | 0.0 | 0.0 |
| **all (micro)** | 805 | 807 | 94.4 | 94.7 | 94.5 | 97.3 | 97.6 | 97.5 | 0.2 | 0.0 |
