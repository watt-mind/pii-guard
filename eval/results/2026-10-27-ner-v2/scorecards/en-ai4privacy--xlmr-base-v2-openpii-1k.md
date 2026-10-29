# pii-guard evaluation

- commit: `b6e7bac54675 (dirty)`, pii-guard 0.1.0
- detectors: `rules`, `ner`
- fixtures: `eval/fixtures/public/en-ai4privacy.jsonl` sha256 `fcfc735dff402d7d`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `en` | 200 | 805 | 881 | 93.3 | 93.2 | 93.2 | 96.9 | 97.5 | 97.2 | 72.9 | 0.5 | 0.1 | 0.7 | 100.0 | 99.1 | 17.06 | 27.83 |
| **overall** | 200 | 805 | 881 | 93.3 | 93.2 | 93.2 | 96.9 | 97.5 | 97.2 | 72.9 | 0.5 | 0.1 | 0.7 | 100.0 | 99.1 | 17.06 | 27.83 |

## Per entity type: `en`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 205 | 206 | 98.5 | 99.0 | 98.8 | 99.5 | 100.0 | 99.8 | 0.0 | 0.0 |
| `ADDRESS` | 176 | 168 | 89.9 | 85.8 | 87.8 | 97.6 | 97.2 | 97.4 | 2.3 | 0.6 |
| `EMAIL` | 111 | 111 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `PHONE` | 85 | 92 | 82.6 | 89.4 | 85.9 | 92.4 | 98.8 | 95.5 | 0.0 | 0.0 |
| `NATIONAL_ID_HU_TAX` | 0 | 5 | 0.0 | - | 0.0 | 0.0 | - | 0.0 | keep | keep |
| `ID_DOCUMENT` | 187 | 176 | 96.0 | 90.4 | 93.1 | 98.3 | 92.5 | 95.3 | 0.0 | 0.0 |
| `BANK_ACCOUNT` | 41 | 45 | 88.9 | 97.6 | 93.0 | 91.1 | 100.0 | 95.3 | 0.0 | 0.0 |
| `ORGANIZATION` | 0 | 1 | 0.0 | - | 0.0 | 0.0 | - | 0.0 | keep | keep |
| **all (micro)** | 805 | 804 | 93.3 | 93.2 | 93.2 | 96.9 | 97.5 | 97.2 | 0.5 | 0.1 |
