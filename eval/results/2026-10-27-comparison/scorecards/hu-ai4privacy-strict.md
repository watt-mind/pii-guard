# pii-guard evaluation

- commit: `4f84c6adc9ba (dirty)`, pii-guard 0.1.0
- detectors: `rules`, `ner`, `llm`
- fixtures: `eval/fixtures/public/hu-ai4privacy.jsonl` sha256 `bd1901745c33316d`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `hu` | 200 | 752 | 864 | 76.0 | 87.4 | 81.3 | 82.1 | 95.2 | 88.1 | 58.7 | 3.7 | 0.1 | 14.1 | 100.0 | 96.0 | 2299.34 | 5001.76 |
| **overall** | 200 | 752 | 864 | 76.0 | 87.4 | 81.3 | 82.1 | 95.2 | 88.1 | 58.7 | 3.7 | 0.1 | 14.1 | 100.0 | 96.0 | 2299.34 | 5001.76 |

## Per entity type: `hu`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 195 | 200 | 80.5 | 82.6 | 81.5 | 97.5 | 99.0 | 98.2 | 1.0 | 0.0 |
| `ADDRESS` | 119 | 121 | 66.1 | 67.2 | 66.7 | 80.2 | 89.1 | 84.4 | 10.1 | 0.0 |
| `EMAIL` | 105 | 105 | 99.0 | 99.0 | 99.0 | 100.0 | 100.0 | 100.0 | 0.0 | 1.0 |
| `PHONE` | 88 | 87 | 98.9 | 97.7 | 98.3 | 98.9 | 97.7 | 98.3 | 1.1 | 0.0 |
| `DATE_OF_BIRTH` | 0 | 89 | 0.0 | - | 0.0 | 0.0 | - | 0.0 | keep | keep |
| `NATIONAL_ID_HU_TAX` | 41 | 39 | 100.0 | 95.1 | 97.5 | 100.0 | 95.1 | 97.5 | 2.4 | 0.0 |
| `NATIONAL_ID_HU_TAJ` | 42 | 39 | 100.0 | 92.9 | 96.3 | 100.0 | 92.9 | 96.3 | 2.4 | 0.0 |
| `ID_DOCUMENT` | 104 | 100 | 98.0 | 94.2 | 96.1 | 98.0 | 94.2 | 96.1 | 2.9 | 0.0 |
| `BANK_ACCOUNT` | 58 | 51 | 98.0 | 86.2 | 91.7 | 98.0 | 86.2 | 91.7 | 13.8 | 0.0 |
| `COMPANY_ID_HU` | 0 | 2 | 0.0 | - | 0.0 | 0.0 | - | 0.0 | keep | keep |
| `ORGANIZATION` | 0 | 27 | 0.0 | - | 0.0 | 0.0 | - | 0.0 | keep | keep |
| `PARCEL_NUMBER_HU` | 0 | 1 | 0.0 | - | 0.0 | 0.0 | - | 0.0 | keep | keep |
| `VEHICLE_PLATE` | 0 | 3 | 0.0 | - | 0.0 | 0.0 | - | 0.0 | keep | keep |
| **all (micro)** | 752 | 864 | 76.0 | 87.4 | 81.3 | 82.1 | 95.2 | 88.1 | 3.7 | 0.1 |
