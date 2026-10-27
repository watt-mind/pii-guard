# pii-guard evaluation

- commit: `688b940b05f3 (dirty)`, pii-guard 0.1.0
- detectors: `rules`, `ner`, `llm`
- fixtures: `eval/fixtures/public/hu-ai4privacy.jsonl` sha256 `bd1901745c33316d`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `hu` | 200 | 752 | 864 | 76.4 | 87.8 | 81.7 | 82.2 | 95.6 | 88.4 | 59.0 | 3.5 | 0.3 | 13.7 | 100.0 | 96.4 | 2530.89 | 5601.70 |
| **overall** | 200 | 752 | 864 | 76.4 | 87.8 | 81.7 | 82.2 | 95.6 | 88.4 | 59.0 | 3.5 | 0.3 | 13.7 | 100.0 | 96.4 | 2530.89 | 5601.70 |

## Per entity type: `hu`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 195 | 198 | 82.3 | 83.6 | 83.0 | 98.0 | 99.0 | 98.5 | 1.0 | 0.0 |
| `ADDRESS` | 119 | 119 | 67.2 | 67.2 | 67.2 | 82.4 | 90.8 | 86.4 | 8.4 | 0.8 |
| `EMAIL` | 105 | 105 | 99.0 | 99.0 | 99.0 | 100.0 | 100.0 | 100.0 | 0.0 | 1.0 |
| `PHONE` | 88 | 88 | 97.7 | 97.7 | 97.7 | 97.7 | 97.7 | 97.7 | 1.1 | 0.0 |
| `DATE_OF_BIRTH` | 0 | 89 | 0.0 | - | 0.0 | 0.0 | - | 0.0 | keep | keep |
| `NATIONAL_ID_HU_TAX` | 41 | 40 | 100.0 | 97.6 | 98.8 | 100.0 | 97.6 | 98.8 | 0.0 | 0.0 |
| `NATIONAL_ID_HU_TAJ` | 42 | 39 | 100.0 | 92.9 | 96.3 | 100.0 | 92.9 | 96.3 | 2.4 | 0.0 |
| `ID_DOCUMENT` | 104 | 98 | 99.0 | 93.3 | 96.0 | 99.0 | 93.3 | 96.0 | 4.8 | 0.0 |
| `BANK_ACCOUNT` | 58 | 52 | 98.1 | 87.9 | 92.7 | 98.1 | 87.9 | 92.7 | 12.1 | 0.0 |
| `COMPANY_ID_HU` | 0 | 1 | 0.0 | - | 0.0 | 0.0 | - | 0.0 | keep | keep |
| `ORGANIZATION` | 0 | 32 | 0.0 | - | 0.0 | 0.0 | - | 0.0 | keep | keep |
| `PARCEL_NUMBER_HU` | 0 | 1 | 0.0 | - | 0.0 | 0.0 | - | 0.0 | keep | keep |
| `VEHICLE_PLATE` | 0 | 2 | 0.0 | - | 0.0 | 0.0 | - | 0.0 | keep | keep |
| **all (micro)** | 752 | 864 | 76.4 | 87.8 | 81.7 | 82.2 | 95.6 | 88.4 | 3.5 | 0.3 |
