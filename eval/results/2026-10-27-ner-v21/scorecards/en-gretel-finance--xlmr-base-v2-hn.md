# pii-guard evaluation

- commit: `477196a3427c (dirty)`, pii-guard 0.1.0
- detectors: `rules`, `ner`
- fixtures: `eval/datasets/gretel-finance/en-gretel-finance.jsonl` sha256 `12967fcd1a89b570`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `en` | 200 | 798 | 837 | 68.5 | 68.8 | 68.6 | 79.9 | 78.2 | 79.1 | 57.4 | 5.1 | 2.0 | 19.0 | 99.0 | 89.4 | 28.59 | 46.66 |
| **overall** | 200 | 798 | 837 | 68.5 | 68.8 | 68.6 | 79.9 | 78.2 | 79.1 | 57.4 | 5.1 | 2.0 | 19.0 | 99.0 | 89.4 | 28.59 | 46.66 |

## Per entity type: `en`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 242 | 259 | 79.2 | 84.7 | 81.8 | 86.9 | 92.1 | 89.4 | 7.0 | 0.6 |
| `ADDRESS` | 154 | 220 | 51.4 | 73.4 | 60.4 | 72.3 | 94.2 | 81.8 | 3.8 | 5.3 |
| `EMAIL` | 40 | 41 | 92.7 | 95.0 | 93.8 | 92.7 | 95.0 | 93.8 | 3.6 | 0.0 |
| `PHONE` | 31 | 35 | 77.1 | 87.1 | 81.8 | 88.6 | 96.8 | 92.5 | 3.4 | 0.0 |
| `DATE_OF_BIRTH` | 11 | 11 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `NATIONAL_ID_HU_TAX` | 0 | 1 | 0.0 | — | 0.0 | 0.0 | — | 0.0 | keep | keep |
| `NATIONAL_ID_HU_TAJ` | 0 | 5 | 0.0 | — | 0.0 | 0.0 | — | 0.0 | keep | keep |
| `ID_DOCUMENT` | 15 | 40 | 27.5 | 73.3 | 40.0 | 32.5 | 86.7 | 47.3 | 7.7 | 0.0 |
| `BANK_ACCOUNT` | 14 | 33 | 42.4 | 100.0 | 59.6 | 42.4 | 100.0 | 59.6 | 0.0 | 0.0 |
| `ORGANIZATION` | 291 | 156 | 83.3 | 44.7 | 58.2 | 96.2 | 51.5 | 67.1 | keep | keep |
| `SECRET` | 0 | 1 | 0.0 | — | 0.0 | 0.0 | — | 0.0 | keep | keep |
| **all (micro)** | 798 | 802 | 68.5 | 68.8 | 68.6 | 79.9 | 78.2 | 79.1 | 5.1 | 2.0 |
