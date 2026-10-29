# pii-guard evaluation

- commit: `b6e7bac54675 (dirty)`, pii-guard 0.1.0
- detectors: `rules`, `ner`, `ner_gliner`
- fixtures: `eval/fixtures/public/hu-ai4privacy.jsonl` sha256 `bd1901745c33316d`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `hu` | 200 | 752 | 973 | 79.4 | 88.4 | 83.6 | 88.7 | 98.9 | 93.5 | 87.0 | 0.5 | 0.1 | 4.5 | 100.0 | 99.5 | 145.35 | 237.73 |
| **overall** | 200 | 752 | 973 | 79.4 | 88.4 | 83.6 | 88.7 | 98.9 | 93.5 | 87.0 | 0.5 | 0.1 | 4.5 | 100.0 | 99.5 | 145.35 | 237.73 |

## Per entity type: `hu`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 195 | 213 | 63.4 | 69.2 | 66.2 | 90.1 | 98.5 | 94.1 | 1.5 | 0.0 |
| `ADDRESS` | 119 | 121 | 84.3 | 85.7 | 85.0 | 95.9 | 98.3 | 97.1 | 0.8 | 0.0 |
| `EMAIL` | 105 | 110 | 94.5 | 99.0 | 96.7 | 95.5 | 100.0 | 97.7 | 0.0 | 1.0 |
| `PHONE` | 88 | 90 | 91.1 | 93.2 | 92.1 | 96.7 | 98.9 | 97.8 | 0.0 | 0.0 |
| `NATIONAL_ID_HU_TAX` | 41 | 42 | 97.6 | 100.0 | 98.8 | 97.6 | 100.0 | 98.8 | 0.0 | 0.0 |
| `NATIONAL_ID_HU_TAJ` | 42 | 42 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `ID_DOCUMENT` | 104 | 106 | 95.3 | 97.1 | 96.2 | 96.2 | 98.1 | 97.1 | 0.0 | 0.0 |
| `BANK_ACCOUNT` | 58 | 58 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `ORGANIZATION` | 0 | 56 | 0.0 | - | 0.0 | 0.0 | - | 0.0 | keep | keep |
| **all (micro)** | 752 | 838 | 79.4 | 88.4 | 83.6 | 88.7 | 98.9 | 93.5 | 0.5 | 0.1 |
