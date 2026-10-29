# pii-guard evaluation

- commit: `e1268295b0d3 (dirty)`, pii-guard 0.1.0
- detectors: `rules`, `ner`
- fixtures: `eval/fixtures/en-synth-sample.jsonl` sha256 `2c7ab3d12880065d`

All ratios in %. P/R/F1 are span-level micro averages; macro F1 is over entity types (overlap match). Leak = labelled values of mask-policy types surviving the masked text in any surface form; partial = an identifying token survives. Consistency = gold entities whose occurrences (all surface forms) are masked by one placeholder.

| Language | Docs | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Macro F1 | Leak | Partial leak | Over-masking | Round trip | Consistency | Detect p50 ms | Detect p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `en` | 10 | 120 | 127 | 80.3 | 85.0 | 82.6 | 96.1 | 98.3 | 97.2 | 95.0 | 1.2 | 5.0 | 4.3 | 100.0 | 91.2 | 50.80 | 97.66 |
| **overall** | 10 | 120 | 127 | 80.3 | 85.0 | 82.6 | 96.1 | 98.3 | 97.2 | 95.0 | 1.2 | 5.0 | 4.3 | 100.0 | 91.2 | 50.80 | 97.66 |

## Per entity type: `en`

| Entity type | Gold | Pred | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap | Leak | Partial leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PERSON` | 59 | 57 | 87.7 | 84.7 | 86.2 | 100.0 | 96.6 | 98.3 | 3.2 | 3.2 |
| `ADDRESS` | 17 | 22 | 50.0 | 64.7 | 56.4 | 95.5 | 100.0 | 97.7 | 0.0 | 17.6 |
| `EMAIL` | 7 | 7 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `PHONE` | 8 | 8 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `DATE_OF_BIRTH` | 6 | 7 | 85.7 | 100.0 | 92.3 | 85.7 | 100.0 | 92.3 | 0.0 | 0.0 |
| `ID_DOCUMENT` | 3 | 6 | 16.7 | 33.3 | 22.2 | 50.0 | 100.0 | 66.7 | 0.0 | 0.0 |
| `BANK_ACCOUNT` | 7 | 7 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| `ORGANIZATION` | 10 | 10 | 90.0 | 90.0 | 90.0 | 100.0 | 100.0 | 100.0 | keep | keep |
| `VEHICLE_PLATE` | 3 | 3 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| **all (micro)** | 120 | 127 | 80.3 | 85.0 | 82.6 | 96.1 | 98.3 | 97.2 | 1.2 | 5.0 |
