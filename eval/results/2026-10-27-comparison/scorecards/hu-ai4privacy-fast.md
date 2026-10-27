# pii-guard evaluation

- commit: `4f84c6adc9ba (dirty)`, pii-guard 0.1.0
- detectors: `rules`, `ner`
- fixtures: `eval/fixtures/public/hu-ai4privacy.jsonl` sha256 `bd1901745c33316d`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `hu` | 200 | 752 | 647 | 54.3 | 46.7 | 50.2 | 79.4 | 59.3 | 67.9 | 41.0 | 40.4 | 1.7 | 14.7 | 100.0 | 50.8 | 30.48 | 46.73 |
| **overall** | 200 | 752 | 647 | 54.3 | 46.7 | 50.2 | 79.4 | 59.3 | 67.9 | 41.0 | 40.4 | 1.7 | 14.7 | 100.0 | 50.8 | 30.48 | 46.73 |

## Per entity type: `hu`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 195 | 257 | 49.8 | 65.6 | 56.6 | 94.9 | 96.9 | 95.9 | 3.1 | 3.1 |
| `ADDRESS` | 119 | 87 | 41.4 | 30.3 | 35.0 | 94.3 | 58.0 | 71.8 | 40.3 | 5.0 |
| `EMAIL` | 105 | 105 | 99.0 | 99.0 | 99.0 | 100.0 | 100.0 | 100.0 | 0.0 | 1.0 |
| `PHONE` | 88 | 23 | 100.0 | 26.1 | 41.4 | 100.0 | 26.1 | 41.4 | 73.9 | 0.0 |
| `DATE_OF_BIRTH` | 0 | 80 | 0.0 | - | 0.0 | 0.0 | - | 0.0 | keep | keep |
| `NATIONAL_ID_HU_TAX` | 41 | 1 | 100.0 | 2.4 | 4.8 | 100.0 | 2.4 | 4.8 | 97.6 | 0.0 |
| `NATIONAL_ID_HU_TAJ` | 42 | 4 | 100.0 | 9.5 | 17.4 | 100.0 | 9.5 | 17.4 | 90.5 | 0.0 |
| `ID_DOCUMENT` | 104 | 51 | 100.0 | 49.0 | 65.8 | 100.0 | 49.0 | 65.8 | 51.0 | 0.0 |
| `BANK_ACCOUNT` | 58 | 4 | 100.0 | 6.9 | 12.9 | 100.0 | 6.9 | 12.9 | 93.1 | 0.0 |
| `ORGANIZATION` | 0 | 35 | 0.0 | - | 0.0 | 0.0 | - | 0.0 | keep | keep |
| **all (micro)** | 752 | 647 | 54.3 | 46.7 | 50.2 | 79.4 | 59.3 | 67.9 | 40.4 | 1.7 |
