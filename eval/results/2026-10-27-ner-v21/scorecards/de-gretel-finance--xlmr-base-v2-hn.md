# pii-guard evaluation

- commit: `477196a3427c (dirty)`, pii-guard 0.1.0
- detectors: `rules`, `ner`
- fixtures: `eval/datasets/gretel-finance/de-gretel-finance.jsonl` sha256 `2401233fa20513d7`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `de` | 200 | 912 | 913 | 55.0 | 51.1 | 53.0 | 66.6 | 60.9 | 63.6 | 59.9 | 29.1 | 3.1 | 27.9 | 99.5 | 67.8 | 41.27 | 97.61 |
| **overall** | 200 | 912 | 913 | 55.0 | 51.1 | 53.0 | 66.6 | 60.9 | 63.6 | 59.9 | 29.1 | 3.1 | 27.9 | 99.5 | 67.8 | 41.27 | 97.61 |

## Per entity type: `de`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 452 | 355 | 69.6 | 54.6 | 61.2 | 78.9 | 61.7 | 69.3 | 43.8 | 3.2 |
| `ADDRESS` | 142 | 239 | 43.5 | 73.2 | 54.6 | 56.5 | 91.5 | 69.9 | 5.1 | 4.2 |
| `EMAIL` | 28 | 30 | 70.0 | 75.0 | 72.4 | 93.3 | 100.0 | 96.6 | 0.0 | 0.0 |
| `PHONE` | 20 | 27 | 59.3 | 80.0 | 68.1 | 66.7 | 90.0 | 76.6 | 10.5 | 0.0 |
| `DATE_OF_BIRTH` | 12 | 12 | 91.7 | 91.7 | 91.7 | 91.7 | 91.7 | 91.7 | 8.3 | 0.0 |
| `NATIONAL_ID_HU_TAJ` | 0 | 4 | 0.0 | — | 0.0 | 0.0 | — | 0.0 | keep | keep |
| `ID_DOCUMENT` | 18 | 74 | 20.3 | 83.3 | 32.6 | 20.3 | 83.3 | 32.6 | 0.0 | 6.7 |
| `BANK_ACCOUNT` | 19 | 41 | 36.6 | 78.9 | 50.0 | 46.3 | 100.0 | 63.3 | 0.0 | 0.0 |
| `ORGANIZATION` | 221 | 65 | 56.9 | 16.7 | 25.9 | 89.2 | 24.9 | 38.9 | keep | keep |
| **all (micro)** | 912 | 847 | 55.0 | 51.1 | 53.0 | 66.6 | 60.9 | 63.6 | 29.1 | 3.1 |
