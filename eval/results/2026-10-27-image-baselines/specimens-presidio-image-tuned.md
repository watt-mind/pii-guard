# Image baseline presidio-image-tuned on official specimen ID documents

65 specimen images, baseline `presidio-image-tuned` (presidio-image-redactor; can't mask portrait, signature). A region is a hit at IoU ≥ 0.5 with one covered box; coverage is the share of its pixels under any mask (cov ≥ 0.9 = fully covered).

| Region type | Regions | Recall@IoU≥0.5 % | Recall@cov≥0.9 % | Mean coverage % |
|---|---:|---:|---:|---:|
| mrz | 30 | 0.0 | 0.0 | 5.8 |
| text | 274 | 17.5 | 8.8 | 25.4 |
| **all** | 406 | 12.3 | 6.4 | 18.5 |

| Country | Images | Regions | Recall@IoU≥0.5 % | Recall@cov≥0.9 % | Portrait IoU % | Signature IoU % | MRZ IoU % | Text IoU % |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| AT | 5 | 27 | 3.7 | 0.0 | - | - | 0.0 | 5.6 |
| BE | 2 | 9 | 33.3 | 11.1 | - | - | 0.0 | 40.0 |
| BG | 2 | 19 | 21.1 | 0.0 | - | - | 0.0 | 26.7 |
| CY | 2 | 13 | 15.4 | 7.7 | - | - | 0.0 | 20.0 |
| CZ | 2 | 12 | 8.3 | 0.0 | - | - | 0.0 | 11.1 |
| DE | 6 | 33 | 6.1 | 6.1 | - | - | 0.0 | 8.7 |
| EE | 2 | 11 | 9.1 | 27.3 | - | - | 0.0 | 12.5 |
| ES | 3 | 24 | 16.7 | 20.8 | - | - | 0.0 | 22.2 |
| FI | 2 | 11 | 27.3 | 9.1 | - | - | 0.0 | 50.0 |
| FR | 4 | 29 | 0.0 | 0.0 | - | - | 0.0 | 0.0 |
| GR | 2 | 13 | 7.7 | 7.7 | - | - | 0.0 | 11.1 |
| HR | 2 | 10 | 30.0 | 10.0 | - | - | 0.0 | 42.9 |
| HU | 6 | 42 | 2.4 | 7.1 | - | - | 0.0 | 3.5 |
| IT | 4 | 21 | 23.8 | 9.5 | - | - | 0.0 | 33.3 |
| LT | 2 | 11 | 0.0 | 9.1 | - | - | 0.0 | 0.0 |
| LU | 2 | 12 | 8.3 | 0.0 | - | - | 0.0 | 16.7 |
| LV | 2 | 12 | 41.7 | 8.3 | - | - | 0.0 | 66.7 |
| MT | 1 | 5 | 20.0 | 0.0 | - | - | 0.0 | 33.3 |
| NL | 2 | 11 | 36.4 | 18.2 | - | - | 0.0 | 57.1 |
| PL | 5 | 34 | 2.9 | 5.9 | - | - | 0.0 | 4.5 |
| RO | 1 | 8 | 50.0 | 0.0 | - | - | - | 66.7 |
| SE | 2 | 10 | 0.0 | 0.0 | - | - | 0.0 | 0.0 |
| SI | 2 | 13 | 7.7 | 0.0 | - | - | 0.0 | 12.5 |
| SK | 2 | 16 | 12.5 | 0.0 | - | - | - | 16.7 |

| Document type | Images | Regions | Recall@IoU≥0.5 % | Recall@cov≥0.9 % |
|---|---:|---:|---:|---:|
| driving_licence | 10 | 46 | 6.5 | 0.0 |
| id_card | 49 | 304 | 15.1 | 6.6 |
| passport | 6 | 56 | 1.8 | 10.7 |

Over-masking (covered area outside every labelled region, mean share of the image): 3.9 %. Errors: none.

Latency (the tool's own time per image, without the worker pipe): p50 1171.2 ms / p95 1922.6 ms.
