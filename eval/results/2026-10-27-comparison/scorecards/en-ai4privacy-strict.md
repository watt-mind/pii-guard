# pii-guard evaluation

- commit: `4f84c6adc9ba (dirty)`, pii-guard 0.1.0
- detectors: `rules`, `ner`, `llm`
- fixtures: `eval/fixtures/public/en-ai4privacy.jsonl` sha256 `fcfc735dff402d7d`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `en` | 200 | 805 | 842 | 78.3 | 81.9 | 80.0 | 83.5 | 93.0 | 88.0 | 55.4 | 3.5 | 0.1 | 10.5 | 100.0 | 96.4 | 1987.51 | 3681.97 |
| **overall** | 200 | 805 | 842 | 78.3 | 81.9 | 80.0 | 83.5 | 93.0 | 88.0 | 55.4 | 3.5 | 0.1 | 10.5 | 100.0 | 96.4 | 1987.51 | 3681.97 |

## Per entity type: `en`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 205 | 213 | 96.2 | 100.0 | 98.1 | 96.2 | 100.0 | 98.1 | 0.0 | 0.0 |
| `ADDRESS` | 176 | 125 | 60.8 | 43.2 | 50.5 | 95.2 | 93.8 | 94.5 | 6.2 | 0.0 |
| `EMAIL` | 111 | 111 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `PHONE` | 85 | 102 | 82.4 | 98.8 | 89.8 | 83.3 | 100.0 | 90.9 | 0.0 | 1.2 |
| `DATE_OF_BIRTH` | 0 | 71 | 0.0 | - | 0.0 | 0.0 | - | 0.0 | keep | keep |
| `NATIONAL_ID_HU_TAX` | 0 | 1 | 0.0 | - | 0.0 | 0.0 | - | 0.0 | keep | keep |
| `ID_DOCUMENT` | 187 | 146 | 100.0 | 78.1 | 87.7 | 100.0 | 78.1 | 87.7 | 7.0 | 0.0 |
| `BANK_ACCOUNT` | 41 | 48 | 77.1 | 90.2 | 83.1 | 77.1 | 90.2 | 83.1 | 9.8 | 0.0 |
| `ORGANIZATION` | 0 | 24 | 0.0 | - | 0.0 | 0.0 | - | 0.0 | keep | keep |
| `VEHICLE_PLATE` | 0 | 1 | 0.0 | - | 0.0 | 0.0 | - | 0.0 | keep | keep |
| **all (micro)** | 805 | 842 | 78.3 | 81.9 | 80.0 | 83.5 | 93.0 | 88.0 | 3.5 | 0.1 |
