# pii-guard evaluation

- commit: `477196a3427c (dirty)`, pii-guard 0.1.0
- detectors: `rules`, `ner`
- fixtures: `eval/fixtures/public/en-ai4privacy.jsonl` sha256 `fcfc735dff402d7d`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `en` | 200 | 805 | 931 | 94.4 | 95.0 | 94.7 | 97.4 | 98.5 | 98.0 | 83.8 | 0.1 | 0.0 | 1.1 | 100.0 | 99.5 | 13.42 | 25.80 |
| **overall** | 200 | 805 | 931 | 94.4 | 95.0 | 94.7 | 97.4 | 98.5 | 98.0 | 83.8 | 0.1 | 0.0 | 1.1 | 100.0 | 99.5 | 13.42 | 25.80 |

## Per entity type: `en`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 205 | 209 | 97.6 | 99.5 | 98.6 | 98.6 | 100.0 | 99.3 | 0.0 | 0.0 |
| `ADDRESS` | 176 | 170 | 93.5 | 90.3 | 91.9 | 99.4 | 99.4 | 99.4 | 0.6 | 0.0 |
| `EMAIL` | 111 | 111 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `PHONE` | 85 | 95 | 81.1 | 90.6 | 85.6 | 90.5 | 100.0 | 95.0 | 0.0 | 0.0 |
| `NATIONAL_ID_HU_TAX` | 0 | 2 | 0.0 | — | 0.0 | 0.0 | — | 0.0 | keep | keep |
| `ID_DOCUMENT` | 187 | 179 | 97.2 | 93.0 | 95.1 | 98.3 | 94.1 | 96.2 | 0.0 | 0.0 |
| `BANK_ACCOUNT` | 41 | 44 | 90.9 | 97.6 | 94.1 | 93.2 | 100.0 | 96.5 | 0.0 | 0.0 |
| **all (micro)** | 805 | 810 | 94.4 | 95.0 | 94.7 | 97.4 | 98.5 | 98.0 | 0.1 | 0.0 |
