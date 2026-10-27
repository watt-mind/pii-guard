# pii-guard evaluation

- commit: `477196a3427c (dirty)`, pii-guard 0.1.0
- detectors: `rules`, `ner`
- fixtures: `eval/fixtures/public/hu-ai4privacy.jsonl` sha256 `bd1901745c33316d`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `hu` | 200 | 752 | 868 | 95.2 | 95.6 | 95.4 | 98.3 | 98.7 | 98.5 | 97.6 | 0.4 | 1.6 | 0.8 | 100.0 | 99.3 | 14.00 | 25.87 |
| **overall** | 200 | 752 | 868 | 95.2 | 95.6 | 95.4 | 98.3 | 98.7 | 98.5 | 97.6 | 0.4 | 1.6 | 0.8 | 100.0 | 99.3 | 14.00 | 25.87 |

## Per entity type: `hu`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 195 | 197 | 97.0 | 97.9 | 97.4 | 99.0 | 99.5 | 99.2 | 0.5 | 0.5 |
| `ADDRESS` | 119 | 119 | 86.6 | 86.6 | 86.6 | 98.3 | 99.2 | 98.7 | 0.8 | 8.4 |
| `EMAIL` | 105 | 105 | 99.0 | 99.0 | 99.0 | 100.0 | 100.0 | 100.0 | 0.0 | 1.0 |
| `PHONE` | 88 | 92 | 91.3 | 95.5 | 93.3 | 95.7 | 100.0 | 97.8 | 0.0 | 0.0 |
| `NATIONAL_ID_HU_TAX` | 41 | 35 | 97.1 | 82.9 | 89.5 | 97.1 | 82.9 | 89.5 | 0.0 | 0.0 |
| `NATIONAL_ID_HU_TAJ` | 42 | 43 | 97.7 | 100.0 | 98.8 | 97.7 | 100.0 | 98.8 | 0.0 | 0.0 |
| `ID_DOCUMENT` | 104 | 103 | 100.0 | 99.0 | 99.5 | 100.0 | 99.0 | 99.5 | 1.0 | 0.0 |
| `BANK_ACCOUNT` | 58 | 61 | 95.1 | 100.0 | 97.5 | 95.1 | 100.0 | 97.5 | 0.0 | 0.0 |
| **all (micro)** | 752 | 755 | 95.2 | 95.6 | 95.4 | 98.3 | 98.7 | 98.5 | 0.4 | 1.6 |
