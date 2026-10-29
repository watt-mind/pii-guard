# pii-guard evaluation

- commit: `477196a3427c (dirty)`, pii-guard 0.1.0
- detectors: `rules`, `ner`
- fixtures: `eval/synthetic/dev/hu-agent-traffic-dev.jsonl` sha256 `f5a0a0e3de68534f`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `hu` | 100 | 561 | 631 | 81.0 | 89.5 | 85.0 | 86.5 | 94.8 | 90.4 | 83.8 | 2.7 | 0.2 | 9.0 | 100.0 | 93.5 | 15.40 | 24.25 |
| **overall** | 100 | 561 | 631 | 81.0 | 89.5 | 85.0 | 86.5 | 94.8 | 90.4 | 83.8 | 2.7 | 0.2 | 9.0 | 100.0 | 93.5 | 15.40 | 24.25 |

## Per entity type: `hu`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 187 | 194 | 89.2 | 92.5 | 90.8 | 96.4 | 100.0 | 98.2 | 0.0 | 0.0 |
| `ADDRESS` | 22 | 22 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `EMAIL` | 121 | 114 | 98.2 | 92.6 | 95.3 | 100.0 | 93.4 | 96.6 | 6.6 | 0.8 |
| `PHONE` | 77 | 83 | 91.6 | 98.7 | 95.0 | 91.6 | 98.7 | 95.0 | 1.3 | 0.0 |
| `DATE_OF_BIRTH` | 22 | 22 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `NATIONAL_ID_HU_TAX` | 54 | 50 | 50.0 | 46.3 | 48.1 | 78.0 | 68.5 | 73.0 | 3.7 | 0.0 |
| `NATIONAL_ID_HU_TAJ` | 11 | 11 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `ID_DOCUMENT` | 0 | 34 | 0.0 | — | 0.0 | 0.0 | — | 0.0 | keep | keep |
| `BANK_ACCOUNT` | 56 | 78 | 64.1 | 89.3 | 74.6 | 69.2 | 94.6 | 80.0 | 5.4 | 0.0 |
| `ORGANIZATION` | 11 | 12 | 91.7 | 100.0 | 95.7 | 91.7 | 100.0 | 95.7 | keep | keep |
| **all (micro)** | 561 | 620 | 81.0 | 89.5 | 85.0 | 86.5 | 94.8 | 90.4 | 2.7 | 0.2 |
