# pii-guard evaluation

- commit: `e1268295b0d3 (dirty)`, pii-guard 0.1.0
- detectors: `rules`, `ner`
- fixtures: `eval/fixtures/public/hu-ai4privacy.jsonl` sha256 `bd1901745c33316d`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `hu` | 200 | 752 | 891 | 61.1 | 67.0 | 63.9 | 77.6 | 80.6 | 79.1 | 64.2 | 11.8 | 1.2 | 11.3 | 100.0 | 84.2 | 29.35 | 48.32 |
| **overall** | 200 | 752 | 891 | 61.1 | 67.0 | 63.9 | 77.6 | 80.6 | 79.1 | 64.2 | 11.8 | 1.2 | 11.3 | 100.0 | 84.2 | 29.35 | 48.32 |

## Per entity type: `hu`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 195 | 231 | 59.3 | 70.3 | 64.3 | 91.3 | 95.4 | 93.3 | 3.6 | 3.1 |
| `ADDRESS` | 119 | 166 | 28.9 | 40.3 | 33.7 | 58.4 | 73.9 | 65.3 | 21.8 | 1.7 |
| `EMAIL` | 105 | 106 | 98.1 | 99.0 | 98.6 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `PHONE` | 88 | 111 | 71.2 | 89.8 | 79.4 | 77.5 | 97.7 | 86.4 | 2.3 | 1.1 |
| `NATIONAL_ID_HU_TAX` | 41 | 10 | 100.0 | 24.4 | 39.2 | 100.0 | 24.4 | 39.2 | 34.1 | 0.0 |
| `NATIONAL_ID_HU_TAJ` | 42 | 9 | 100.0 | 21.4 | 35.3 | 100.0 | 21.4 | 35.3 | 16.7 | 0.0 |
| `ID_DOCUMENT` | 104 | 105 | 71.4 | 72.1 | 71.8 | 73.3 | 75.0 | 74.2 | 24.0 | 0.0 |
| `BANK_ACCOUNT` | 58 | 47 | 89.4 | 72.4 | 80.0 | 93.6 | 75.9 | 83.8 | 13.8 | 0.0 |
| `ORGANIZATION` | 0 | 40 | 0.0 | - | 0.0 | 0.0 | - | 0.0 | keep | keep |
| **all (micro)** | 752 | 825 | 61.1 | 67.0 | 63.9 | 77.6 | 80.6 | 79.1 | 11.8 | 1.2 |
