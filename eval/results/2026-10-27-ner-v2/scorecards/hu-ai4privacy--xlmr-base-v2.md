# pii-guard evaluation

- commit: `b6e7bac54675 (dirty)`, pii-guard 0.1.0
- detectors: `rules`, `ner`
- fixtures: `eval/fixtures/public/hu-ai4privacy.jsonl` sha256 `bd1901745c33316d`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `hu` | 200 | 752 | 826 | 98.3 | 98.4 | 98.3 | 99.3 | 99.5 | 99.4 | 99.5 | 0.4 | 0.3 | 0.5 | 100.0 | 99.6 | 17.03 | 25.50 |
| **overall** | 200 | 752 | 826 | 98.3 | 98.4 | 98.3 | 99.3 | 99.5 | 99.4 | 99.5 | 0.4 | 0.3 | 0.5 | 100.0 | 99.6 | 17.03 | 25.50 |

## Per entity type: `hu`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 195 | 196 | 98.0 | 98.5 | 98.2 | 98.5 | 99.0 | 98.7 | 1.0 | 0.5 |
| `ADDRESS` | 119 | 118 | 99.2 | 98.3 | 98.7 | 100.0 | 99.2 | 99.6 | 0.8 | 0.0 |
| `EMAIL` | 105 | 105 | 99.0 | 99.0 | 99.0 | 100.0 | 100.0 | 100.0 | 0.0 | 1.0 |
| `PHONE` | 88 | 88 | 95.5 | 95.5 | 95.5 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `NATIONAL_ID_HU_TAX` | 41 | 42 | 95.2 | 97.6 | 96.4 | 97.6 | 100.0 | 98.8 | 0.0 | 0.0 |
| `NATIONAL_ID_HU_TAJ` | 42 | 42 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `ID_DOCUMENT` | 104 | 105 | 99.0 | 100.0 | 99.5 | 99.0 | 100.0 | 99.5 | 0.0 | 0.0 |
| `BANK_ACCOUNT` | 58 | 57 | 100.0 | 98.3 | 99.1 | 100.0 | 98.3 | 99.1 | 0.0 | 0.0 |
| **all (micro)** | 752 | 753 | 98.3 | 98.4 | 98.3 | 99.3 | 99.5 | 99.4 | 0.4 | 0.3 |
