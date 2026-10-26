# Visual recall on official specimen ID documents

65 specimen images, SAM `sam-3.1` (FACE, SIGNATURE, ID_PHOTO), OCR `tesseract`, text detector `rules`. A region is a hit at IoU ≥ 0.5 with one covered box; coverage is the share of its pixels under any mask (cov ≥ 0.9 = fully covered).

| Region type | Regions | Recall@IoU≥0.5 % | Recall@cov≥0.9 % | Mean coverage % |
|---|---:|---:|---:|---:|
| portrait | 65 | 90.8 | 72.3 | 87.2 |
| signature | 37 | 83.8 | 64.9 | 82.6 |
| mrz | 30 | 0.0 | 0.0 | 0.0 |
| text | 274 | 0.4 | 0.4 | 2.6 |
| **all** | 406 | 22.4 | 17.7 | 23.2 |

| Country | Images | Regions | Recall@IoU≥0.5 % | Recall@cov≥0.9 % | Portrait IoU % | Signature IoU % | MRZ IoU % | Text IoU % |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| AT | 5 | 27 | 25.9 | 22.2 | 100.0 | 100.0 | 0.0 | 0.0 |
| BE | 2 | 9 | 33.3 | 33.3 | 100.0 | 100.0 | 0.0 | 0.0 |
| BG | 2 | 19 | 15.8 | 15.8 | 100.0 | 100.0 | 0.0 | 0.0 |
| CY | 2 | 13 | 15.4 | 0.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| CZ | 2 | 12 | 16.7 | 16.7 | 100.0 | 100.0 | 0.0 | 0.0 |
| DE | 6 | 33 | 24.2 | 24.2 | 100.0 | 100.0 | 0.0 | 0.0 |
| EE | 2 | 11 | 18.2 | 18.2 | 100.0 | 100.0 | 0.0 | 0.0 |
| ES | 3 | 24 | 16.7 | 12.5 | 100.0 | 100.0 | 0.0 | 0.0 |
| FI | 2 | 11 | 27.3 | 18.2 | 66.7 | 100.0 | 0.0 | 0.0 |
| FR | 4 | 29 | 20.7 | 17.2 | 83.3 | 50.0 | 0.0 | 0.0 |
| GR | 2 | 13 | 23.1 | 15.4 | 100.0 | 100.0 | 0.0 | 0.0 |
| HR | 2 | 10 | 20.0 | 20.0 | 100.0 | 100.0 | 0.0 | 0.0 |
| HU | 6 | 42 | 14.3 | 14.3 | 66.7 | 50.0 | 0.0 | 0.0 |
| IT | 4 | 21 | 23.8 | 19.1 | 100.0 | 100.0 | 0.0 | 0.0 |
| LT | 2 | 11 | 27.3 | 18.2 | 100.0 | 100.0 | 0.0 | 0.0 |
| LU | 2 | 12 | 33.3 | 16.7 | 66.7 | 100.0 | 0.0 | 0.0 |
| LV | 2 | 12 | 33.3 | 25.0 | 100.0 | 0.0 | 0.0 | 0.0 |
| MT | 1 | 5 | 20.0 | 0.0 | 100.0 | - | 0.0 | 0.0 |
| NL | 2 | 11 | 36.4 | 9.1 | 100.0 | 100.0 | 0.0 | 14.3 |
| PL | 5 | 34 | 26.5 | 23.5 | 85.7 | 100.0 | 0.0 | 0.0 |
| RO | 1 | 8 | 12.5 | 12.5 | 100.0 | 0.0 | - | 0.0 |
| SE | 2 | 10 | 10.0 | 10.0 | 100.0 | 0.0 | 0.0 | 0.0 |
| SI | 2 | 13 | 30.8 | 15.4 | 100.0 | 100.0 | 0.0 | 0.0 |
| SK | 2 | 16 | 25.0 | 25.0 | 100.0 | 100.0 | - | 0.0 |

| Document type | Images | Regions | Recall@IoU≥0.5 % | Recall@cov≥0.9 % |
|---|---:|---:|---:|---:|
| driving_licence | 10 | 46 | 30.4 | 30.4 |
| id_card | 49 | 304 | 21.7 | 16.4 |
| passport | 6 | 56 | 19.6 | 14.3 |

Over-masking (covered area outside every labelled region, mean share of the image): 2.1 %. Errors: none.

SAM: 260 calls (4.0 per image), estimated $0.65 at $0.0025/call; this run 35 live, 225 cached.
Latency: SAM per call p50 1372.7 ms / p95 2280.8 ms; SAM per image p50 5625.2 ms / p95 7661.5 ms (sequential calls); OCR + detection per image p50 534.4 ms / p95 1226.9 ms.
