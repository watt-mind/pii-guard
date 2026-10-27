# Image baseline eka on official specimen ID documents

65 specimen images, baseline `eka` (eka-pii-redaction). A region is a hit at IoU ≥ 0.5 with one covered box; coverage is the share of its pixels under any mask (cov ≥ 0.9 = fully covered).

| Region type | Regions | Recall@IoU≥0.5 % | Recall@cov≥0.9 % | Mean coverage % |
|---|---:|---:|---:|---:|
| portrait | 65 | 56.9 | 52.3 | 55.4 |
| signature | 37 | 46.0 | 37.8 | 45.7 |
| mrz | 30 | 6.7 | 13.3 | 70.3 |
| text | 274 | 32.5 | 17.2 | 41.9 |
| **all** | 406 | 35.7 | 24.4 | 46.5 |

| Country | Images | Regions | Recall@IoU≥0.5 % | Recall@cov≥0.9 % | Portrait IoU % | Signature IoU % | MRZ IoU % | Text IoU % |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| AT | 5 | 27 | 18.5 | 11.1 | 20.0 | 100.0 | 0.0 | 11.1 |
| BE | 2 | 9 | 55.6 | 22.2 | 100.0 | 0.0 | 0.0 | 60.0 |
| BG | 2 | 19 | 52.6 | 21.1 | 50.0 | 100.0 | 0.0 | 53.3 |
| CY | 2 | 13 | 30.8 | 30.8 | 100.0 | 100.0 | 0.0 | 20.0 |
| CZ | 2 | 12 | 75.0 | 25.0 | 100.0 | 100.0 | 0.0 | 77.8 |
| DE | 6 | 33 | 45.5 | 48.5 | 100.0 | 75.0 | 50.0 | 30.4 |
| EE | 2 | 11 | 54.5 | 36.4 | 100.0 | 100.0 | 0.0 | 50.0 |
| ES | 3 | 24 | 41.7 | 41.7 | 100.0 | 50.0 | 0.0 | 38.9 |
| FI | 2 | 11 | 45.5 | 27.3 | 66.7 | 0.0 | 0.0 | 50.0 |
| FR | 4 | 29 | 10.3 | 6.9 | 33.3 | 0.0 | 33.3 | 0.0 |
| GR | 2 | 13 | 38.5 | 15.4 | 50.0 | 0.0 | 0.0 | 44.4 |
| HR | 2 | 10 | 60.0 | 30.0 | 100.0 | 100.0 | 0.0 | 57.1 |
| HU | 6 | 42 | 14.3 | 11.9 | 0.0 | 0.0 | 0.0 | 20.7 |
| IT | 4 | 21 | 38.1 | 19.1 | 33.3 | 50.0 | 0.0 | 40.0 |
| LT | 2 | 11 | 9.1 | 9.1 | 0.0 | 0.0 | 0.0 | 14.3 |
| LU | 2 | 12 | 33.3 | 33.3 | 33.3 | 50.0 | 0.0 | 33.3 |
| LV | 2 | 12 | 25.0 | 33.3 | 75.0 | 0.0 | 0.0 | 0.0 |
| MT | 1 | 5 | 40.0 | 0.0 | 100.0 | - | 0.0 | 33.3 |
| NL | 2 | 11 | 72.7 | 27.3 | 100.0 | 0.0 | 0.0 | 85.7 |
| PL | 5 | 34 | 26.5 | 35.3 | 85.7 | 33.3 | 0.0 | 9.1 |
| RO | 1 | 8 | 87.5 | 25.0 | 100.0 | 100.0 | - | 83.3 |
| SE | 2 | 10 | 10.0 | 0.0 | 0.0 | 0.0 | 0.0 | 14.3 |
| SI | 2 | 13 | 15.4 | 15.4 | 33.3 | 0.0 | 0.0 | 12.5 |
| SK | 2 | 16 | 68.8 | 37.5 | 100.0 | 100.0 | - | 58.3 |

| Document type | Images | Regions | Recall@IoU≥0.5 % | Recall@cov≥0.9 % |
|---|---:|---:|---:|---:|
| driving_licence | 10 | 46 | 37.0 | 30.4 |
| id_card | 49 | 304 | 38.5 | 24.0 |
| passport | 6 | 56 | 19.6 | 21.4 |

Over-masking (covered area outside every labelled region, mean share of the image): 10.8 %. Errors: none.

Latency (the tool's own time per image, without the worker pipe): p50 597.7 ms / p95 915.2 ms.
