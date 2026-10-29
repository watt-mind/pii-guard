# pii-guard evaluation

- commit: `b6e7bac54675 (dirty)`, pii-guard 0.1.0
- detectors: `rules`, `ner_gliner`
- fixtures: `eval/fixtures/public/hu-ai4privacy.jsonl` sha256 `bd1901745c33316d`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `hu` | 200 | 752 | 757 | 60.3 | 53.3 | 56.6 | 79.7 | 68.4 | 73.6 | 56.8 | 26.3 | 4.1 | 5.5 | 100.0 | 71.4 | 142.73 | 239.44 |
| **overall** | 200 | 752 | 757 | 60.3 | 53.3 | 56.6 | 79.7 | 68.4 | 73.6 | 56.8 | 26.3 | 4.1 | 5.5 | 100.0 | 71.4 | 142.73 | 239.44 |

## Per entity type: `hu`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 195 | 200 | 55.0 | 56.4 | 55.7 | 88.5 | 89.7 | 89.1 | 10.3 | 3.6 |
| `ADDRESS` | 119 | 90 | 32.2 | 24.4 | 27.8 | 94.4 | 59.7 | 73.1 | 37.8 | 19.3 |
| `EMAIL` | 105 | 116 | 89.7 | 99.0 | 94.1 | 90.5 | 100.0 | 95.0 | 0.0 | 1.0 |
| `PHONE` | 88 | 93 | 72.0 | 76.1 | 74.0 | 76.3 | 80.7 | 78.5 | 11.4 | 0.0 |
| `NATIONAL_ID_HU_TAX` | 41 | 21 | 66.7 | 34.1 | 45.2 | 66.7 | 34.1 | 45.2 | 53.7 | 0.0 |
| `NATIONAL_ID_HU_TAJ` | 42 | 9 | 100.0 | 21.4 | 35.3 | 100.0 | 21.4 | 35.3 | 42.9 | 0.0 |
| `ID_DOCUMENT` | 104 | 68 | 88.2 | 57.7 | 69.8 | 89.7 | 58.7 | 70.9 | 36.5 | 0.0 |
| `BANK_ACCOUNT` | 58 | 8 | 100.0 | 13.8 | 24.2 | 100.0 | 13.8 | 24.2 | 77.6 | 0.0 |
| `ORGANIZATION` | 0 | 60 | 0.0 | - | 0.0 | 0.0 | - | 0.0 | keep | keep |
| **all (micro)** | 752 | 665 | 60.3 | 53.3 | 56.6 | 79.7 | 68.4 | 73.6 | 26.3 | 4.1 |
