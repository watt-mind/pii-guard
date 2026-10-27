# pii-guard evaluation

- commit: `b6e7bac54675 (dirty)`, pii-guard 0.1.0
- detectors: `rules`, `ner`
- fixtures: `eval/fixtures/public/en-ai4privacy.jsonl` sha256 `fcfc735dff402d7d`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `en` | 200 | 805 | 857 | 92.7 | 92.8 | 92.7 | 97.1 | 97.5 | 97.3 | 83.7 | 0.2 | 0.2 | 0.2 | 100.0 | 98.8 | 30.61 | 50.56 |
| **overall** | 200 | 805 | 857 | 92.7 | 92.8 | 92.7 | 97.1 | 97.5 | 97.3 | 83.7 | 0.2 | 0.2 | 0.2 | 100.0 | 98.8 | 30.61 | 50.56 |

## Per entity type: `en`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 205 | 206 | 99.0 | 99.5 | 99.3 | 99.5 | 100.0 | 99.8 | 0.0 | 0.5 |
| `ADDRESS` | 176 | 169 | 88.8 | 85.2 | 87.0 | 100.0 | 98.3 | 99.1 | 1.1 | 0.6 |
| `EMAIL` | 111 | 111 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `PHONE` | 85 | 92 | 82.6 | 89.4 | 85.9 | 92.4 | 98.8 | 95.5 | 0.0 | 0.0 |
| `NATIONAL_ID_HU_TAX` | 0 | 9 | 0.0 | - | 0.0 | 0.0 | - | 0.0 | keep | keep |
| `ID_DOCUMENT` | 187 | 175 | 94.9 | 88.8 | 91.7 | 98.3 | 91.4 | 94.7 | 0.0 | 0.0 |
| `BANK_ACCOUNT` | 41 | 44 | 90.9 | 97.6 | 94.1 | 93.2 | 100.0 | 96.5 | 0.0 | 0.0 |
| **all (micro)** | 805 | 806 | 92.7 | 92.8 | 92.7 | 97.1 | 97.5 | 97.3 | 0.2 | 0.2 |
