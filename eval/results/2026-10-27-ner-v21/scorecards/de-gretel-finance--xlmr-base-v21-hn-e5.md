# pii-guard evaluation

- commit: `477196a3427c (dirty)`, pii-guard 0.1.0
- detectors: `rules`, `ner`
- fixtures: `eval/datasets/gretel-finance/de-gretel-finance.jsonl` sha256 `2401233fa20513d7`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `de` | 200 | 912 | 946 | 53.2 | 50.7 | 51.9 | 70.5 | 63.0 | 66.6 | 57.9 | 30.4 | 4.2 | 27.5 | 100.0 | 63.0 | 25.14 | 34.96 |
| **overall** | 200 | 912 | 946 | 53.2 | 50.7 | 51.9 | 70.5 | 63.0 | 66.6 | 57.9 | 30.4 | 4.2 | 27.5 | 100.0 | 63.0 | 25.14 | 34.96 |

## Per entity type: `de`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 452 | 326 | 74.5 | 53.8 | 62.5 | 84.0 | 60.2 | 70.1 | 44.3 | 3.8 |
| `ADDRESS` | 142 | 259 | 31.3 | 57.0 | 40.4 | 59.5 | 88.0 | 71.0 | 7.6 | 5.9 |
| `EMAIL` | 28 | 28 | 75.0 | 75.0 | 75.0 | 96.4 | 96.4 | 96.4 | 4.5 | 9.1 |
| `PHONE` | 20 | 27 | 59.3 | 80.0 | 68.1 | 66.7 | 90.0 | 76.6 | 10.5 | 0.0 |
| `DATE_OF_BIRTH` | 12 | 14 | 71.4 | 83.3 | 76.9 | 92.9 | 100.0 | 96.3 | 0.0 | 0.0 |
| `NATIONAL_ID_HU_TAX` | 0 | 1 | 0.0 | — | 0.0 | 0.0 | — | 0.0 | keep | keep |
| `NATIONAL_ID_HU_TAJ` | 0 | 4 | 0.0 | — | 0.0 | 0.0 | — | 0.0 | keep | keep |
| `ID_DOCUMENT` | 18 | 86 | 17.4 | 83.3 | 28.8 | 17.4 | 83.3 | 28.8 | 13.3 | 6.7 |
| `BANK_ACCOUNT` | 19 | 26 | 57.7 | 78.9 | 66.7 | 73.1 | 100.0 | 84.4 | 0.0 | 0.0 |
| `ORGANIZATION` | 221 | 97 | 62.9 | 27.6 | 38.4 | 94.8 | 39.4 | 55.6 | keep | keep |
| **all (micro)** | 912 | 868 | 53.2 | 50.7 | 51.9 | 70.5 | 63.0 | 66.6 | 30.4 | 4.2 |
