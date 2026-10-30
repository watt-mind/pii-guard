# Visual recall on official specimen ID documents

65 specimen images, SAM `sam-3.1` (FACE, SIGNATURE, ID_PHOTO), OCR `tesseract`, text detector `rules+captions` (OCR on images enlarged to 2000 px). A region is a hit at IoU ≥ 0.5 with one covered box; coverage is the share of its pixels under any mask (cov ≥ 0.9 = fully covered).

| Region type | Regions | Recall@IoU≥0.5 % | Recall@cov≥0.9 % | Mean coverage % |
|---|---:|---:|---:|---:|
| portrait | 65 | 90.8 | 73.9 | 87.8 |
| signature | 37 | 83.8 | 64.9 | 82.8 |
| mrz | 30 | 83.3 | 66.7 | 80.1 |
| text | 274 | 20.8 | 15.0 | 30.3 |
| **all** | 406 | 42.4 | 32.8 | 47.9 |

| Country | Images | Regions | Recall@IoU≥0.5 % | Recall@cov≥0.9 % | Portrait IoU % | Signature IoU % | MRZ IoU % | Text IoU % |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| AT | 5 | 27 | 51.8 | 37.0 | 100.0 | 100.0 | 100.0 | 27.8 |
| BE | 2 | 9 | 77.8 | 66.7 | 100.0 | 100.0 | 100.0 | 60.0 |
| BG | 2 | 19 | 47.4 | 21.1 | 100.0 | 100.0 | 100.0 | 33.3 |
| CY | 2 | 13 | 23.1 | 7.7 | 100.0 | 100.0 | 100.0 | 0.0 |
| CZ | 2 | 12 | 41.7 | 58.3 | 100.0 | 100.0 | 100.0 | 22.2 |
| DE | 6 | 33 | 39.4 | 39.4 | 100.0 | 100.0 | 100.0 | 13.0 |
| EE | 2 | 11 | 36.4 | 27.3 | 100.0 | 100.0 | 100.0 | 12.5 |
| ES | 3 | 24 | 29.2 | 29.2 | 100.0 | 100.0 | 100.0 | 5.6 |
| FI | 2 | 11 | 27.3 | 18.2 | 66.7 | 100.0 | 0.0 | 0.0 |
| FR | 4 | 29 | 34.5 | 27.6 | 83.3 | 50.0 | 33.3 | 16.7 |
| GR | 2 | 13 | 46.2 | 38.5 | 100.0 | 100.0 | 100.0 | 22.2 |
| HR | 2 | 10 | 80.0 | 30.0 | 100.0 | 100.0 | 100.0 | 71.4 |
| HU | 6 | 42 | 23.8 | 28.6 | 66.7 | 50.0 | 66.7 | 6.9 |
| IT | 4 | 21 | 52.4 | 42.9 | 100.0 | 100.0 | 100.0 | 33.3 |
| LT | 2 | 11 | 36.4 | 54.5 | 100.0 | 100.0 | 100.0 | 0.0 |
| LU | 2 | 12 | 50.0 | 33.3 | 66.7 | 100.0 | 100.0 | 16.7 |
| LV | 2 | 12 | 50.0 | 58.3 | 100.0 | 0.0 | 100.0 | 16.7 |
| MT | 1 | 5 | 40.0 | 20.0 | 100.0 | - | 100.0 | 0.0 |
| NL | 2 | 11 | 72.7 | 27.3 | 100.0 | 100.0 | 100.0 | 57.1 |
| PL | 5 | 34 | 47.1 | 26.5 | 85.7 | 100.0 | 50.0 | 27.3 |
| RO | 1 | 8 | 50.0 | 12.5 | 100.0 | 0.0 | - | 50.0 |
| SE | 2 | 10 | 20.0 | 20.0 | 100.0 | 0.0 | 100.0 | 0.0 |
| SI | 2 | 13 | 46.2 | 23.1 | 100.0 | 100.0 | 100.0 | 12.5 |
| SK | 2 | 16 | 50.0 | 43.8 | 100.0 | 100.0 | - | 33.3 |

| Document type | Images | Regions | Recall@IoU≥0.5 % | Recall@cov≥0.9 % |
|---|---:|---:|---:|---:|
| driving_licence | 10 | 46 | 54.4 | 34.8 |
| id_card | 49 | 304 | 43.1 | 33.2 |
| passport | 6 | 56 | 28.6 | 28.6 |

Over-masking (covered area outside every labelled region, mean share of the image): 4.7 %. Errors: none.

SAM: 260 calls (4.0 per image), estimated $0.65 at $0.0025/call; this run 0 live, 260 cached.
Latency: SAM per call p50 1303.7 ms / p95 2212.5 ms; SAM per image p50 5226.0 ms / p95 7919.8 ms (sequential calls); OCR + detection per image p50 3283.8 ms / p95 6591.3 ms; total per image p50 8400.1 ms / p95 13022.5 ms.
