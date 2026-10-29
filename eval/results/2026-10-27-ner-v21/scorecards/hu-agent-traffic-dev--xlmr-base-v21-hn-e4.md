# pii-guard evaluation

- commit: `477196a3427c (dirty)`, pii-guard 0.1.0
- detectors: `rules`, `ner`
- fixtures: `eval/synthetic/dev/hu-agent-traffic-dev.jsonl` sha256 `f5a0a0e3de68534f`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `hu` | 100 | 561 | 629 | 81.9 | 90.2 | 85.8 | 85.4 | 93.8 | 89.4 | 78.0 | 2.9 | 0.4 | 7.4 | 100.0 | 95.2 | 14.01 | 19.74 |
| **overall** | 100 | 561 | 629 | 81.9 | 90.2 | 85.8 | 85.4 | 93.8 | 89.4 | 78.0 | 2.9 | 0.4 | 7.4 | 100.0 | 95.2 | 14.01 | 19.74 |

## Per entity type: `hu`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 187 | 194 | 90.2 | 93.6 | 91.9 | 96.4 | 100.0 | 98.2 | 0.0 | 0.6 |
| `ADDRESS` | 22 | 22 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `EMAIL` | 121 | 116 | 96.6 | 92.6 | 94.5 | 100.0 | 94.2 | 97.0 | 5.8 | 0.8 |
| `PHONE` | 77 | 92 | 81.5 | 97.4 | 88.8 | 81.5 | 97.4 | 88.8 | 2.6 | 0.0 |
| `DATE_OF_BIRTH` | 22 | 22 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `NATIONAL_ID_HU_TAX` | 54 | 36 | 75.0 | 50.0 | 60.0 | 86.1 | 57.4 | 68.9 | 5.6 | 0.0 |
| `NATIONAL_ID_HU_TAJ` | 11 | 11 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `ID_DOCUMENT` | 0 | 10 | 0.0 | — | 0.0 | 0.0 | — | 0.0 | keep | keep |
| `BANK_ACCOUNT` | 56 | 82 | 62.2 | 91.1 | 73.9 | 64.6 | 94.6 | 76.8 | 5.4 | 0.0 |
| `ORGANIZATION` | 11 | 33 | 33.3 | 100.0 | 50.0 | 33.3 | 100.0 | 50.0 | keep | keep |
| **all (micro)** | 561 | 618 | 81.9 | 90.2 | 85.8 | 85.4 | 93.8 | 89.4 | 2.9 | 0.4 |
