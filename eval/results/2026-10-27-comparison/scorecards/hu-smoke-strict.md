# pii-guard evaluation

- commit: `4f84c6adc9ba (dirty)`, pii-guard 0.1.0
- detectors: `rules`, `ner`, `llm`
- fixtures: `eval/fixtures/hu-smoke.jsonl` sha256 `3766a651708e8749`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `hu` | 31 | 120 | 126 | 87.3 | 91.7 | 89.4 | 95.2 | 99.2 | 97.2 | 97.2 | 0.9 | 0.9 | 1.8 | 100.0 | 97.2 | 1948.78 | 3793.35 |
| **overall** | 31 | 120 | 126 | 87.3 | 91.7 | 89.4 | 95.2 | 99.2 | 97.2 | 97.2 | 0.9 | 0.9 | 1.8 | 100.0 | 97.2 | 1948.78 | 3793.35 |

## Per entity type: `hu`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 38 | 38 | 92.1 | 92.1 | 92.1 | 97.4 | 97.4 | 97.4 | 2.7 | 2.7 |
| `ADDRESS` | 13 | 14 | 78.6 | 84.6 | 81.5 | 92.9 | 100.0 | 96.3 | 0.0 | 0.0 |
| `EMAIL` | 6 | 6 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `PHONE` | 7 | 7 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `DATE_OF_BIRTH` | 6 | 8 | 62.5 | 83.3 | 71.4 | 75.0 | 100.0 | 85.7 | 0.0 | 0.0 |
| `NATIONAL_ID_HU_TAX` | 5 | 5 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `NATIONAL_ID_HU_TAJ` | 5 | 5 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `ID_DOCUMENT` | 10 | 11 | 72.7 | 80.0 | 76.2 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `BANK_ACCOUNT` | 6 | 6 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `COMPANY_ID_HU` | 4 | 5 | 80.0 | 100.0 | 88.9 | 80.0 | 100.0 | 88.9 | keep | keep |
| `ORGANIZATION` | 9 | 10 | 90.0 | 100.0 | 94.7 | 90.0 | 100.0 | 94.7 | keep | keep |
| `PARCEL_NUMBER_HU` | 6 | 6 | 66.7 | 66.7 | 66.7 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `VEHICLE_PLATE` | 5 | 5 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| **all (micro)** | 120 | 126 | 87.3 | 91.7 | 89.4 | 95.2 | 99.2 | 97.2 | 0.9 | 0.9 |
