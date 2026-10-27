# pii-guard evaluation

- commit: `b6e7bac54675 (dirty)`, pii-guard 0.1.0
- detectors: `rules`, `ner`
- fixtures: `eval/fixtures/public/hu-ai4privacy.jsonl` sha256 `bd1901745c33316d`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `hu` | 200 | 752 | 837 | 74.1 | 73.0 | 73.5 | 92.7 | 85.1 | 88.7 | 78.0 | 12.1 | 1.5 | 1.5 | 100.0 | 81.2 | 28.52 | 44.66 |
| **overall** | 200 | 752 | 837 | 74.1 | 73.0 | 73.5 | 92.7 | 85.1 | 88.7 | 78.0 | 12.1 | 1.5 | 1.5 | 100.0 | 81.2 | 28.52 | 44.66 |

## Per entity type: `hu`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 195 | 228 | 64.0 | 74.9 | 69.0 | 96.9 | 96.4 | 96.7 | 3.6 | 2.6 |
| `ADDRESS` | 119 | 98 | 45.9 | 37.8 | 41.5 | 93.9 | 66.4 | 77.8 | 32.8 | 4.2 |
| `EMAIL` | 105 | 105 | 99.0 | 99.0 | 99.0 | 100.0 | 100.0 | 100.0 | 0.0 | 1.0 |
| `PHONE` | 88 | 98 | 84.7 | 94.3 | 89.2 | 90.8 | 100.0 | 95.2 | 0.0 | 0.0 |
| `NATIONAL_ID_HU_TAX` | 41 | 38 | 73.7 | 68.3 | 70.9 | 86.8 | 80.5 | 83.5 | 4.9 | 0.0 |
| `NATIONAL_ID_HU_TAJ` | 42 | 37 | 91.9 | 81.0 | 86.1 | 94.6 | 83.3 | 88.6 | 2.4 | 0.0 |
| `ID_DOCUMENT` | 104 | 74 | 87.8 | 62.5 | 73.0 | 89.2 | 63.5 | 74.2 | 35.6 | 0.0 |
| `BANK_ACCOUNT` | 58 | 49 | 89.8 | 75.9 | 82.2 | 93.9 | 79.3 | 86.0 | 8.6 | 0.0 |
| `ORGANIZATION` | 0 | 14 | 0.0 | - | 0.0 | 0.0 | - | 0.0 | keep | keep |
| **all (micro)** | 752 | 741 | 74.1 | 73.0 | 73.5 | 92.7 | 85.1 | 88.7 | 12.1 | 1.5 |
