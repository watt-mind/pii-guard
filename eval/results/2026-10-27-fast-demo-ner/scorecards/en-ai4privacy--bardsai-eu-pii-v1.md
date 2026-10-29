# pii-guard evaluation

- commit: `e1268295b0d3 (dirty)`, pii-guard 0.1.0
- detectors: `rules`, `ner`
- fixtures: `eval/fixtures/public/en-ai4privacy.jsonl` sha256 `fcfc735dff402d7d`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `en` | 200 | 805 | 855 | 67.9 | 68.4 | 68.2 | 85.9 | 86.5 | 86.2 | 66.0 | 11.2 | 1.7 | 8.1 | 100.0 | 85.5 | 31.36 | 56.85 |
| **overall** | 200 | 805 | 855 | 67.9 | 68.4 | 68.2 | 85.9 | 86.5 | 86.2 | 66.0 | 11.2 | 1.7 | 8.1 | 100.0 | 85.5 | 31.36 | 56.85 |

## Per entity type: `en`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 205 | 228 | 75.4 | 83.9 | 79.4 | 96.1 | 99.5 | 97.8 | 0.0 | 4.4 |
| `ADDRESS` | 176 | 187 | 34.8 | 36.9 | 35.8 | 72.2 | 84.1 | 77.7 | 13.6 | 0.0 |
| `EMAIL` | 111 | 112 | 99.1 | 100.0 | 99.6 | 99.1 | 100.0 | 99.6 | 0.0 | 0.0 |
| `PHONE` | 85 | 94 | 79.8 | 88.2 | 83.8 | 89.4 | 97.6 | 93.3 | 2.4 | 0.0 |
| `NATIONAL_ID_HU_TAX` | 0 | 1 | 0.0 | - | 0.0 | 0.0 | - | 0.0 | keep | keep |
| `ID_DOCUMENT` | 187 | 120 | 84.2 | 54.0 | 65.8 | 96.7 | 63.1 | 76.4 | 29.4 | 2.7 |
| `BANK_ACCOUNT` | 41 | 36 | 75.0 | 65.9 | 70.1 | 88.9 | 78.0 | 83.1 | 22.0 | 0.0 |
| `ORGANIZATION` | 0 | 33 | 0.0 | - | 0.0 | 0.0 | - | 0.0 | keep | keep |
| **all (micro)** | 805 | 811 | 67.9 | 68.4 | 68.2 | 85.9 | 86.5 | 86.2 | 11.2 | 1.7 |
