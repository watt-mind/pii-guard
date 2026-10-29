# pii-guard evaluation

- commit: `477196a3427c (dirty)`, pii-guard 0.1.0
- detectors: `rules`, `ner`
- fixtures: `eval/fixtures/public/hu-ai4privacy.jsonl` sha256 `bd1901745c33316d`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `hu` | 200 | 752 | 884 | 97.1 | 97.9 | 97.5 | 98.4 | 99.2 | 98.8 | 98.6 | 0.5 | 0.3 | 1.2 | 100.0 | 99.2 | 13.56 | 23.20 |
| **overall** | 200 | 752 | 884 | 97.1 | 97.9 | 97.5 | 98.4 | 99.2 | 98.8 | 98.6 | 0.5 | 0.3 | 1.2 | 100.0 | 99.2 | 13.56 | 23.20 |

## Per entity type: `hu`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 195 | 194 | 99.0 | 98.5 | 98.7 | 99.0 | 98.5 | 98.7 | 1.5 | 0.0 |
| `ADDRESS` | 119 | 117 | 96.6 | 95.0 | 95.8 | 100.0 | 98.3 | 99.2 | 0.8 | 0.8 |
| `EMAIL` | 105 | 105 | 99.0 | 99.0 | 99.0 | 100.0 | 100.0 | 100.0 | 0.0 | 1.0 |
| `PHONE` | 88 | 88 | 95.5 | 95.5 | 95.5 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `NATIONAL_ID_HU_TAX` | 41 | 40 | 97.5 | 95.1 | 96.3 | 100.0 | 97.6 | 98.8 | 0.0 | 0.0 |
| `NATIONAL_ID_HU_TAJ` | 42 | 44 | 95.5 | 100.0 | 97.7 | 95.5 | 100.0 | 97.7 | 0.0 | 0.0 |
| `ID_DOCUMENT` | 104 | 106 | 98.1 | 100.0 | 99.0 | 98.1 | 100.0 | 99.0 | 0.0 | 0.0 |
| `BANK_ACCOUNT` | 58 | 64 | 90.6 | 100.0 | 95.1 | 90.6 | 100.0 | 95.1 | 0.0 | 0.0 |
| **all (micro)** | 752 | 758 | 97.1 | 97.9 | 97.5 | 98.4 | 99.2 | 98.8 | 0.5 | 0.3 |
