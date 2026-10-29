# pii-guard evaluation

- commit: `b6e7bac54675 (dirty)`, pii-guard 0.1.0
- detectors: `rules`, `ner`
- fixtures: `eval/fixtures/public/hu-ai4privacy.jsonl` sha256 `bd1901745c33316d`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `hu` | 200 | 752 | 836 | 73.1 | 70.7 | 71.9 | 90.1 | 83.9 | 86.9 | 77.0 | 12.6 | 1.6 | 2.0 | 100.0 | 83.2 | 18.21 | 29.08 |
| **overall** | 200 | 752 | 836 | 73.1 | 70.7 | 71.9 | 90.1 | 83.9 | 86.9 | 77.0 | 12.6 | 1.6 | 2.0 | 100.0 | 83.2 | 18.21 | 29.08 |

## Per entity type: `hu`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 195 | 227 | 59.0 | 68.7 | 63.5 | 93.4 | 96.4 | 94.9 | 3.6 | 1.5 |
| `ADDRESS` | 119 | 73 | 47.9 | 29.4 | 36.5 | 94.5 | 57.1 | 71.2 | 40.3 | 6.7 |
| `EMAIL` | 105 | 105 | 99.0 | 99.0 | 99.0 | 100.0 | 100.0 | 100.0 | 0.0 | 1.0 |
| `PHONE` | 88 | 100 | 83.0 | 94.3 | 88.3 | 87.0 | 98.9 | 92.6 | 0.0 | 0.0 |
| `NATIONAL_ID_HU_TAX` | 41 | 44 | 79.5 | 85.4 | 82.4 | 81.8 | 87.8 | 84.7 | 2.4 | 0.0 |
| `NATIONAL_ID_HU_TAJ` | 42 | 31 | 96.8 | 71.4 | 82.2 | 96.8 | 71.4 | 82.2 | 4.8 | 0.0 |
| `ID_DOCUMENT` | 104 | 62 | 91.9 | 54.8 | 68.7 | 98.4 | 58.7 | 73.5 | 35.6 | 0.0 |
| `BANK_ACCOUNT` | 58 | 61 | 88.5 | 93.1 | 90.8 | 91.8 | 96.6 | 94.1 | 0.0 | 0.0 |
| `ORGANIZATION` | 0 | 25 | 0.0 | - | 0.0 | 0.0 | - | 0.0 | keep | keep |
| **all (micro)** | 752 | 728 | 73.1 | 70.7 | 71.9 | 90.1 | 83.9 | 86.9 | 12.6 | 1.6 |
