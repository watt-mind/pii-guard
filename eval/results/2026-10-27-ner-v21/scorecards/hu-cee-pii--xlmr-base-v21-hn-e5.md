# pii-guard evaluation

- commit: `477196a3427c (dirty)`, pii-guard 0.1.0
- detectors: `rules`, `ner`
- fixtures: `eval/datasets/cee-pii/hu-cee-pii.jsonl` sha256 `f68b658427027042`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `hu` | 251 | 308 | 425 | 71.1 | 98.1 | 82.4 | 72.2 | 99.7 | 83.8 | 54.6 | 0.3 | 0.0 | 27.8 | 100.0 | 99.7 | 19.26 | 46.14 |
| **overall** | 251 | 308 | 425 | 71.1 | 98.1 | 82.4 | 72.2 | 99.7 | 83.8 | 54.6 | 0.3 | 0.0 | 27.8 | 100.0 | 99.7 | 19.26 | 46.14 |

## Per entity type: `hu`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 67 | 84 | 77.4 | 97.0 | 86.1 | 79.8 | 100.0 | 88.7 | 0.0 | 0.0 |
| `PHONE` | 12 | 13 | 92.3 | 100.0 | 96.0 | 92.3 | 100.0 | 96.0 | 0.0 | 0.0 |
| `DATE_OF_BIRTH` | 57 | 56 | 94.6 | 93.0 | 93.8 | 100.0 | 98.2 | 99.1 | 1.8 | 0.0 |
| `NATIONAL_ID_HU_TAX` | 0 | 10 | 0.0 | — | 0.0 | 0.0 | — | 0.0 | keep | keep |
| `NATIONAL_ID_HU_TAJ` | 172 | 177 | 97.2 | 100.0 | 98.6 | 97.2 | 100.0 | 98.6 | 0.0 | 0.0 |
| `ID_DOCUMENT` | 0 | 25 | 0.0 | — | 0.0 | 0.0 | — | 0.0 | keep | keep |
| `BANK_ACCOUNT` | 0 | 60 | 0.0 | — | 0.0 | 0.0 | — | 0.0 | keep | keep |
| **all (micro)** | 308 | 425 | 71.1 | 98.1 | 82.4 | 72.2 | 99.7 | 83.8 | 0.3 | 0.0 |
