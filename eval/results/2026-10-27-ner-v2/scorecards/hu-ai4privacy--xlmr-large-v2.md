# pii-guard evaluation

- commit: `b6e7bac54675 (dirty)`, pii-guard 0.1.0
- detectors: `rules`, `ner`
- fixtures: `eval/fixtures/public/hu-ai4privacy.jsonl` sha256 `bd1901745c33316d`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `hu` | 200 | 752 | 847 | 98.4 | 98.4 | 98.4 | 99.6 | 99.5 | 99.5 | 99.6 | 0.4 | 0.1 | 0.3 | 100.0 | 99.5 | 29.10 | 44.67 |
| **overall** | 200 | 752 | 847 | 98.4 | 98.4 | 98.4 | 99.6 | 99.5 | 99.5 | 99.6 | 0.4 | 0.1 | 0.3 | 100.0 | 99.5 | 29.10 | 44.67 |

## Per entity type: `hu`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 195 | 195 | 99.0 | 99.0 | 99.0 | 99.0 | 99.0 | 99.0 | 1.0 | 0.0 |
| `ADDRESS` | 119 | 117 | 98.3 | 96.6 | 97.5 | 100.0 | 98.3 | 99.2 | 0.8 | 0.0 |
| `EMAIL` | 105 | 105 | 99.0 | 99.0 | 99.0 | 100.0 | 100.0 | 100.0 | 0.0 | 1.0 |
| `PHONE` | 88 | 89 | 93.3 | 94.3 | 93.8 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `NATIONAL_ID_HU_TAX` | 41 | 41 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `NATIONAL_ID_HU_TAJ` | 42 | 43 | 97.7 | 100.0 | 98.8 | 97.7 | 100.0 | 98.8 | 0.0 | 0.0 |
| `ID_DOCUMENT` | 104 | 104 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `BANK_ACCOUNT` | 58 | 58 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| **all (micro)** | 752 | 752 | 98.4 | 98.4 | 98.4 | 99.6 | 99.5 | 99.5 | 0.4 | 0.1 |
