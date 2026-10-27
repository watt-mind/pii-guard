# Image baseline presidio-image on official specimen ID documents

65 specimen images, baseline `presidio-image` (presidio-image-redactor; can't mask portrait, signature). A region is a hit at IoU ≥ 0.5 with one covered box; coverage is the share of its pixels under any mask (cov ≥ 0.9 = fully covered).

| Region type | Regions | Recall@IoU≥0.5 % | Recall@cov≥0.9 % | Mean coverage % |
|---|---:|---:|---:|---:|
| mrz | 30 | 0.0 | 0.0 | 11.9 |
| text | 274 | 19.7 | 8.4 | 24.1 |
| **all** | 406 | 13.3 | 5.7 | 17.7 |

| Country | Images | Regions | Recall@IoU≥0.5 % | Recall@cov≥0.9 % | Portrait IoU % | Signature IoU % | MRZ IoU % | Text IoU % |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| AT | 5 | 27 | 7.4 | 0.0 | - | - | 0.0 | 11.1 |
| BE | 2 | 9 | 33.3 | 0.0 | - | - | 0.0 | 60.0 |
| BG | 2 | 19 | 21.1 | 5.3 | - | - | 0.0 | 26.7 |
| CY | 2 | 13 | 15.4 | 15.4 | - | - | 0.0 | 20.0 |
| CZ | 2 | 12 | 41.7 | 0.0 | - | - | 0.0 | 55.6 |
| DE | 6 | 33 | 9.1 | 9.1 | - | - | 0.0 | 13.0 |
| EE | 2 | 11 | 27.3 | 27.3 | - | - | 0.0 | 37.5 |
| ES | 3 | 24 | 16.7 | 29.2 | - | - | 0.0 | 22.2 |
| FI | 2 | 11 | 27.3 | 9.1 | - | - | 0.0 | 50.0 |
| FR | 4 | 29 | 0.0 | 0.0 | - | - | 0.0 | 0.0 |
| GR | 2 | 13 | 15.4 | 7.7 | - | - | 0.0 | 22.2 |
| HR | 2 | 10 | 30.0 | 0.0 | - | - | 0.0 | 42.9 |
| HU | 6 | 42 | 2.4 | 4.8 | - | - | 0.0 | 3.5 |
| IT | 4 | 21 | 19.1 | 4.8 | - | - | 0.0 | 26.7 |
| LT | 2 | 11 | 0.0 | 0.0 | - | - | 0.0 | 0.0 |
| LU | 2 | 12 | 8.3 | 8.3 | - | - | 0.0 | 16.7 |
| LV | 2 | 12 | 0.0 | 0.0 | - | - | 0.0 | 0.0 |
| MT | 1 | 5 | 20.0 | 0.0 | - | - | 0.0 | 33.3 |
| NL | 2 | 11 | 36.4 | 0.0 | - | - | 0.0 | 57.1 |
| PL | 5 | 34 | 2.9 | 2.9 | - | - | 0.0 | 4.5 |
| RO | 1 | 8 | 50.0 | 0.0 | - | - | - | 66.7 |
| SE | 2 | 10 | 0.0 | 0.0 | - | - | 0.0 | 0.0 |
| SI | 2 | 13 | 7.7 | 0.0 | - | - | 0.0 | 12.5 |
| SK | 2 | 16 | 18.8 | 0.0 | - | - | - | 25.0 |

| Document type | Images | Regions | Recall@IoU≥0.5 % | Recall@cov≥0.9 % |
|---|---:|---:|---:|---:|
| driving_licence | 10 | 46 | 8.7 | 4.3 |
| id_card | 49 | 304 | 15.1 | 4.9 |
| passport | 6 | 56 | 7.1 | 10.7 |

Over-masking (covered area outside every labelled region, mean share of the image): 3.4 %. Errors: none.

Latency (the tool's own time per image, without the worker pipe): p50 279.9 ms / p95 574.4 ms.
