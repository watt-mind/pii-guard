# pii-guard evaluation

- commit: `b6e7bac54675 (dirty)`, pii-guard 0.1.0
- detectors: `rules`, `ner`
- fixtures: `eval/fixtures/public/en-ai4privacy.jsonl` sha256 `fcfc735dff402d7d`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `en` | 200 | 805 | 836 | 70.5 | 64.8 | 67.6 | 86.9 | 78.3 | 82.4 | 57.0 | 14.3 | 1.9 | 1.9 | 100.0 | 81.1 | 30.51 | 51.33 |
| **overall** | 200 | 805 | 836 | 70.5 | 64.8 | 67.6 | 86.9 | 78.3 | 82.4 | 57.0 | 14.3 | 1.9 | 1.9 | 100.0 | 81.1 | 30.51 | 51.33 |

## Per entity type: `en`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 205 | 247 | 70.0 | 84.4 | 76.5 | 94.7 | 99.0 | 96.8 | 1.0 | 4.4 |
| `ADDRESS` | 176 | 101 | 62.4 | 35.8 | 45.5 | 98.0 | 68.8 | 80.8 | 30.1 | 1.7 |
| `EMAIL` | 111 | 111 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `PHONE` | 85 | 98 | 77.6 | 89.4 | 83.1 | 86.7 | 98.8 | 92.4 | 0.0 | 0.0 |
| `NATIONAL_ID_HU_TAX` | 0 | 47 | 0.0 | - | 0.0 | 0.0 | - | 0.0 | keep | keep |
| `NATIONAL_ID_HU_TAJ` | 0 | 5 | 0.0 | - | 0.0 | 0.0 | - | 0.0 | keep | keep |
| `ID_DOCUMENT` | 187 | 83 | 83.1 | 36.9 | 51.1 | 98.8 | 42.2 | 59.2 | 27.8 | 1.6 |
| `BANK_ACCOUNT` | 41 | 35 | 85.7 | 73.2 | 78.9 | 91.4 | 78.0 | 84.2 | 19.5 | 0.0 |
| `ORGANIZATION` | 0 | 13 | 0.0 | - | 0.0 | 0.0 | - | 0.0 | keep | keep |
| **all (micro)** | 805 | 740 | 70.5 | 64.8 | 67.6 | 86.9 | 78.3 | 82.4 | 14.3 | 1.9 |
