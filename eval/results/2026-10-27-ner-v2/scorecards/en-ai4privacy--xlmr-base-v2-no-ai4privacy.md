# pii-guard evaluation

- commit: `b6e7bac54675 (dirty)`, pii-guard 0.1.0
- detectors: `rules`, `ner`
- fixtures: `eval/fixtures/public/en-ai4privacy.jsonl` sha256 `fcfc735dff402d7d`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `en` | 200 | 805 | 780 | 71.3 | 63.6 | 67.2 | 83.7 | 75.7 | 79.5 | 54.4 | 15.0 | 1.7 | 2.7 | 100.0 | 81.9 | 18.26 | 27.06 |
| **overall** | 200 | 805 | 780 | 71.3 | 63.6 | 67.2 | 83.7 | 75.7 | 79.5 | 54.4 | 15.0 | 1.7 | 2.7 | 100.0 | 81.9 | 18.26 | 27.06 |

## Per entity type: `en`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 205 | 240 | 73.3 | 85.9 | 79.1 | 90.0 | 98.0 | 93.9 | 2.0 | 2.0 |
| `ADDRESS` | 176 | 93 | 59.1 | 31.2 | 40.9 | 95.7 | 64.2 | 76.9 | 33.0 | 4.0 |
| `EMAIL` | 111 | 111 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `PHONE` | 85 | 98 | 77.6 | 89.4 | 83.1 | 86.7 | 98.8 | 92.4 | 1.2 | 0.0 |
| `NATIONAL_ID_HU_TAX` | 0 | 40 | 0.0 | - | 0.0 | 0.0 | - | 0.0 | keep | keep |
| `NATIONAL_ID_HU_TAJ` | 0 | 2 | 0.0 | - | 0.0 | 0.0 | - | 0.0 | keep | keep |
| `ID_DOCUMENT` | 187 | 61 | 96.7 | 31.6 | 47.6 | 98.4 | 32.1 | 48.4 | 31.0 | 1.6 |
| `BANK_ACCOUNT` | 41 | 61 | 57.4 | 85.4 | 68.6 | 65.6 | 97.6 | 78.4 | 0.0 | 0.0 |
| `ORGANIZATION` | 0 | 12 | 0.0 | - | 0.0 | 0.0 | - | 0.0 | keep | keep |
| **all (micro)** | 805 | 718 | 71.3 | 63.6 | 67.2 | 83.7 | 75.7 | 79.5 | 15.0 | 1.7 |
