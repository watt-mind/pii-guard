# Image baseline eka-tuned on official specimen ID documents

65 specimen images, baseline `eka-tuned` (eka-pii-redaction). A region is a hit at IoU ≥ 0.5 with one covered box; coverage is the share of its pixels under any mask (cov ≥ 0.9 = fully covered).

| Region type | Regions | Recall@IoU≥0.5 % | Recall@cov≥0.9 % | Mean coverage % |
|---|---:|---:|---:|---:|
| portrait | 65 | 55.4 | 47.7 | 53.5 |
| signature | 37 | 48.6 | 37.8 | 53.1 |
| mrz | 30 | 10.0 | 16.7 | 69.3 |
| text | 274 | 32.5 | 24.1 | 47.5 |
| **all** | 406 | 36.0 | 28.6 | 50.5 |

| Country | Images | Regions | Recall@IoU≥0.5 % | Recall@cov≥0.9 % | Portrait IoU % | Signature IoU % | MRZ IoU % | Text IoU % |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| AT | 5 | 27 | 22.2 | 7.4 | 20.0 | 100.0 | 0.0 | 16.7 |
| BE | 2 | 9 | 55.6 | 33.3 | 100.0 | 0.0 | 0.0 | 60.0 |
| BG | 2 | 19 | 52.6 | 36.8 | 100.0 | 100.0 | 0.0 | 46.7 |
| CY | 2 | 13 | 38.5 | 30.8 | 100.0 | 100.0 | 0.0 | 30.0 |
| CZ | 2 | 12 | 58.3 | 33.3 | 100.0 | 100.0 | 0.0 | 55.6 |
| DE | 6 | 33 | 54.5 | 51.5 | 100.0 | 75.0 | 50.0 | 43.5 |
| EE | 2 | 11 | 45.5 | 54.5 | 0.0 | 100.0 | 0.0 | 50.0 |
| ES | 3 | 24 | 37.5 | 41.7 | 100.0 | 50.0 | 0.0 | 33.3 |
| FI | 2 | 11 | 63.6 | 27.3 | 66.7 | 100.0 | 0.0 | 66.7 |
| FR | 4 | 29 | 10.3 | 10.3 | 33.3 | 0.0 | 33.3 | 0.0 |
| GR | 2 | 13 | 38.5 | 30.8 | 50.0 | 0.0 | 0.0 | 44.4 |
| HR | 2 | 10 | 50.0 | 30.0 | 100.0 | 100.0 | 0.0 | 42.9 |
| HU | 6 | 42 | 9.5 | 23.8 | 0.0 | 0.0 | 33.3 | 10.3 |
| IT | 4 | 21 | 38.1 | 38.1 | 33.3 | 50.0 | 0.0 | 40.0 |
| LT | 2 | 11 | 0.0 | 9.1 | 0.0 | 0.0 | 0.0 | 0.0 |
| LU | 2 | 12 | 41.7 | 8.3 | 33.3 | 50.0 | 0.0 | 50.0 |
| LV | 2 | 12 | 66.7 | 41.7 | 75.0 | 0.0 | 0.0 | 83.3 |
| MT | 1 | 5 | 40.0 | 40.0 | 100.0 | - | 0.0 | 33.3 |
| NL | 2 | 11 | 63.6 | 27.3 | 100.0 | 0.0 | 0.0 | 71.4 |
| PL | 5 | 34 | 23.5 | 29.4 | 71.4 | 33.3 | 0.0 | 9.1 |
| RO | 1 | 8 | 87.5 | 25.0 | 100.0 | 100.0 | - | 83.3 |
| SE | 2 | 10 | 0.0 | 10.0 | 0.0 | 0.0 | 0.0 | 0.0 |
| SI | 2 | 13 | 15.4 | 0.0 | 33.3 | 0.0 | 0.0 | 12.5 |
| SK | 2 | 16 | 62.5 | 43.8 | 100.0 | 100.0 | - | 50.0 |

| Document type | Images | Regions | Recall@IoU≥0.5 % | Recall@cov≥0.9 % |
|---|---:|---:|---:|---:|
| driving_licence | 10 | 46 | 37.0 | 26.1 |
| id_card | 49 | 304 | 38.2 | 28.0 |
| passport | 6 | 56 | 23.2 | 33.9 |

Over-masking (covered area outside every labelled region, mean share of the image): 12.0 %. Errors: none.

Latency (the tool's own time per image, without the worker pipe): p50 1615.8 ms / p95 2294.7 ms.
