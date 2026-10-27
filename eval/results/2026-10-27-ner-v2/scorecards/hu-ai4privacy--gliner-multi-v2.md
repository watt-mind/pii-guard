# pii-guard evaluation

- commit: `b6e7bac54675 (dirty)`, pii-guard 0.1.0
- detectors: `rules`, `ner_gliner`
- fixtures: `eval/fixtures/public/hu-ai4privacy.jsonl` sha256 `bd1901745c33316d`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `hu` | 200 | 752 | 792 | 95.9 | 97.2 | 96.6 | 97.0 | 98.3 | 97.6 | 86.4 | 0.5 | 0.1 | 0.8 | 100.0 | 99.5 | 105.66 | 203.32 |
| **overall** | 200 | 752 | 792 | 95.9 | 97.2 | 96.6 | 97.0 | 98.3 | 97.6 | 86.4 | 0.5 | 0.1 | 0.8 | 100.0 | 99.5 | 105.66 | 203.32 |

## Per entity type: `hu`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 195 | 196 | 98.5 | 99.0 | 98.7 | 98.5 | 99.0 | 98.7 | 1.0 | 0.0 |
| `ADDRESS` | 119 | 120 | 95.8 | 96.6 | 96.2 | 98.3 | 99.2 | 98.7 | 0.8 | 0.0 |
| `EMAIL` | 105 | 105 | 99.0 | 99.0 | 99.0 | 100.0 | 100.0 | 100.0 | 0.0 | 1.0 |
| `PHONE` | 88 | 91 | 92.3 | 95.5 | 93.9 | 96.7 | 100.0 | 98.3 | 0.0 | 0.0 |
| `NATIONAL_ID_HU_TAX` | 41 | 43 | 90.7 | 95.1 | 92.9 | 90.7 | 95.1 | 92.9 | 0.0 | 0.0 |
| `NATIONAL_ID_HU_TAJ` | 42 | 37 | 100.0 | 88.1 | 93.7 | 100.0 | 88.1 | 93.7 | 2.4 | 0.0 |
| `ID_DOCUMENT` | 104 | 106 | 98.1 | 100.0 | 99.0 | 98.1 | 100.0 | 99.0 | 0.0 | 0.0 |
| `BANK_ACCOUNT` | 58 | 56 | 98.2 | 94.8 | 96.5 | 98.2 | 94.8 | 96.5 | 0.0 | 0.0 |
| `ORGANIZATION` | 0 | 8 | 0.0 | - | 0.0 | 0.0 | - | 0.0 | keep | keep |
| **all (micro)** | 752 | 762 | 95.9 | 97.2 | 96.6 | 97.0 | 98.3 | 97.6 | 0.5 | 0.1 |
