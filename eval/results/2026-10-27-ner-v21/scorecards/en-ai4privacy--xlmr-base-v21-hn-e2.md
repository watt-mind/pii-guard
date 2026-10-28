# pii-guard evaluation

- commit: `477196a3427c (dirty)`, pii-guard 0.1.0
- detectors: `rules`, `ner`
- fixtures: `eval/fixtures/public/en-ai4privacy.jsonl` sha256 `fcfc735dff402d7d`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `en` | 200 | 805 | 930 | 91.2 | 94.3 | 92.7 | 94.4 | 98.0 | 96.1 | 81.4 | 0.4 | 0.1 | 3.7 | 100.0 | 99.0 | 13.73 | 23.50 |
| **overall** | 200 | 805 | 930 | 91.2 | 94.3 | 92.7 | 94.4 | 98.0 | 96.1 | 81.4 | 0.4 | 0.1 | 3.7 | 100.0 | 99.0 | 13.73 | 23.50 |

## Per entity type: `en`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 205 | 214 | 94.9 | 99.0 | 96.9 | 96.3 | 100.0 | 98.1 | 0.0 | 0.0 |
| `ADDRESS` | 176 | 168 | 91.7 | 87.5 | 89.5 | 99.4 | 98.3 | 98.8 | 1.7 | 0.6 |
| `EMAIL` | 111 | 111 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `PHONE` | 85 | 91 | 83.5 | 89.4 | 86.4 | 92.3 | 97.6 | 94.9 | 0.0 | 0.0 |
| `NATIONAL_ID_HU_TAX` | 0 | 1 | 0.0 | — | 0.0 | 0.0 | — | 0.0 | keep | keep |
| `ID_DOCUMENT` | 187 | 192 | 91.1 | 93.6 | 92.3 | 91.7 | 94.1 | 92.9 | 0.0 | 0.0 |
| `BANK_ACCOUNT` | 41 | 55 | 72.7 | 97.6 | 83.3 | 74.5 | 100.0 | 85.4 | 0.0 | 0.0 |
| **all (micro)** | 805 | 832 | 91.2 | 94.3 | 92.7 | 94.4 | 98.0 | 96.1 | 0.4 | 0.1 |
