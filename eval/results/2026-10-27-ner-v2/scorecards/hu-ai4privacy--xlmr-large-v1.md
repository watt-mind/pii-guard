# pii-guard evaluation

- commit: `b6e7bac54675 (dirty)`, pii-guard 0.1.0
- detectors: `rules`, `ner`
- fixtures: `eval/fixtures/public/hu-ai4privacy.jsonl` sha256 `bd1901745c33316d`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `hu` | 200 | 752 | 698 | 64.9 | 53.3 | 58.5 | 91.3 | 66.1 | 76.7 | 56.6 | 33.6 | 1.7 | 1.7 | 100.0 | 57.7 | 42.25 | 74.30 |
| **overall** | 200 | 752 | 698 | 64.9 | 53.3 | 58.5 | 91.3 | 66.1 | 76.7 | 56.6 | 33.6 | 1.7 | 1.7 | 100.0 | 57.7 | 42.25 | 74.30 |

## Per entity type: `hu`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 195 | 256 | 50.0 | 65.6 | 56.8 | 94.9 | 96.9 | 95.9 | 3.1 | 3.1 |
| `ADDRESS` | 119 | 87 | 41.4 | 30.3 | 35.0 | 94.3 | 58.0 | 71.8 | 40.3 | 5.0 |
| `EMAIL` | 105 | 105 | 99.0 | 99.0 | 99.0 | 100.0 | 100.0 | 100.0 | 0.0 | 1.0 |
| `PHONE` | 88 | 49 | 98.0 | 54.5 | 70.1 | 100.0 | 55.7 | 71.5 | 44.3 | 0.0 |
| `NATIONAL_ID_HU_TAX` | 41 | 10 | 100.0 | 24.4 | 39.2 | 100.0 | 24.4 | 39.2 | 75.6 | 0.0 |
| `NATIONAL_ID_HU_TAJ` | 42 | 9 | 100.0 | 21.4 | 35.3 | 100.0 | 21.4 | 35.3 | 78.6 | 0.0 |
| `ID_DOCUMENT` | 104 | 58 | 100.0 | 55.8 | 71.6 | 100.0 | 55.8 | 71.6 | 44.2 | 0.0 |
| `BANK_ACCOUNT` | 58 | 8 | 100.0 | 13.8 | 24.2 | 100.0 | 13.8 | 24.2 | 86.2 | 0.0 |
| `ORGANIZATION` | 0 | 36 | 0.0 | - | 0.0 | 0.0 | - | 0.0 | keep | keep |
| **all (micro)** | 752 | 618 | 64.9 | 53.3 | 58.5 | 91.3 | 66.1 | 76.7 | 33.6 | 1.7 |
