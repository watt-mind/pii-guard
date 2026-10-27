# pii-guard evaluation

- commit: `b6e7bac54675 (dirty)`, pii-guard 0.1.0
- detectors: `rules`, `ner`
- fixtures: `eval/fixtures/public/hu-ai4privacy.jsonl` sha256 `bd1901745c33316d`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `hu` | 200 | 752 | 656 | 55.5 | 48.4 | 51.7 | 83.4 | 65.0 | 73.1 | 55.2 | 34.3 | 2.4 | 12.4 | 100.0 | 60.9 | 23.71 | 35.28 |
| **overall** | 200 | 752 | 656 | 55.5 | 48.4 | 51.7 | 83.4 | 65.0 | 73.1 | 55.2 | 34.3 | 2.4 | 12.4 | 100.0 | 60.9 | 23.71 | 35.28 |

## Per entity type: `hu`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 195 | 193 | 61.7 | 61.0 | 61.3 | 97.9 | 91.8 | 94.8 | 5.6 | 1.5 |
| `ADDRESS` | 119 | 198 | 4.0 | 6.7 | 5.0 | 60.1 | 59.7 | 59.9 | 40.3 | 11.8 |
| `EMAIL` | 105 | 105 | 99.0 | 99.0 | 99.0 | 100.0 | 100.0 | 100.0 | 0.0 | 1.0 |
| `PHONE` | 88 | 49 | 98.0 | 54.5 | 70.1 | 100.0 | 55.7 | 71.5 | 44.3 | 0.0 |
| `NATIONAL_ID_HU_TAX` | 41 | 10 | 100.0 | 24.4 | 39.2 | 100.0 | 24.4 | 39.2 | 75.6 | 0.0 |
| `NATIONAL_ID_HU_TAJ` | 42 | 9 | 100.0 | 21.4 | 35.3 | 100.0 | 21.4 | 35.3 | 78.6 | 0.0 |
| `ID_DOCUMENT` | 104 | 58 | 100.0 | 55.8 | 71.6 | 100.0 | 55.8 | 71.6 | 44.2 | 0.0 |
| `BANK_ACCOUNT` | 58 | 8 | 100.0 | 13.8 | 24.2 | 100.0 | 13.8 | 24.2 | 86.2 | 0.0 |
| `ORGANIZATION` | 0 | 26 | 0.0 | - | 0.0 | 0.0 | - | 0.0 | keep | keep |
| **all (micro)** | 752 | 656 | 55.5 | 48.4 | 51.7 | 83.4 | 65.0 | 73.1 | 34.3 | 2.4 |
