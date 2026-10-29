# pii-guard evaluation

- commit: `477196a3427c (dirty)`, pii-guard 0.1.0
- detectors: `rules`, `ner`
- fixtures: `eval/datasets/cee-pii/hu-cee-pii.jsonl` sha256 `f68b658427027042`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `hu` | 251 | 308 | 489 | 61.3 | 97.4 | 75.3 | 62.6 | 99.4 | 76.8 | 54.9 | 0.6 | 0.0 | 37.4 | 100.0 | 99.4 | 12.94 | 18.77 |
| **overall** | 251 | 308 | 489 | 61.3 | 97.4 | 75.3 | 62.6 | 99.4 | 76.8 | 54.9 | 0.6 | 0.0 | 37.4 | 100.0 | 99.4 | 12.94 | 18.77 |

## Per entity type: `hu`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 67 | 84 | 77.4 | 97.0 | 86.1 | 78.6 | 98.5 | 87.4 | 1.5 | 0.0 |
| `PHONE` | 12 | 12 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `DATE_OF_BIRTH` | 57 | 56 | 91.1 | 89.5 | 90.3 | 100.0 | 98.2 | 99.1 | 1.8 | 0.0 |
| `NATIONAL_ID_HU_TAX` | 0 | 29 | 0.0 | — | 0.0 | 0.0 | — | 0.0 | keep | keep |
| `NATIONAL_ID_HU_TAJ` | 172 | 181 | 95.0 | 100.0 | 97.5 | 95.0 | 100.0 | 97.5 | 0.0 | 0.0 |
| `ID_DOCUMENT` | 0 | 32 | 0.0 | — | 0.0 | 0.0 | — | 0.0 | keep | keep |
| `BANK_ACCOUNT` | 0 | 95 | 0.0 | — | 0.0 | 0.0 | — | 0.0 | keep | keep |
| **all (micro)** | 308 | 489 | 61.3 | 97.4 | 75.3 | 62.6 | 99.4 | 76.8 | 0.6 | 0.0 |
