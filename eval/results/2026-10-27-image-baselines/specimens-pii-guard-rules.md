# pii-guard (rules) on official specimen ID documents

65 specimen images, SAM `sam-3.1` (FACE, SIGNATURE, ID_PHOTO), OCR `tesseract`, text detector `rules+captions` (OCR on images enlarged to 2000 px). A region is a hit at IoU ≥ 0.5 with one covered box; coverage is the share of its pixels under any mask (cov ≥ 0.9 = fully covered).

| Region type | Regions | Recall@IoU≥0.5 % | Recall@cov≥0.9 % | Mean coverage % |
|---|---:|---:|---:|---:|
| portrait | 65 | 90.8 | 73.9 | 87.7 |
| signature | 37 | 83.8 | 64.9 | 82.8 |
| mrz | 30 | 76.7 | 60.0 | 72.4 |
| text | 274 | 15.0 | 10.2 | 21.3 |
| **all** | 406 | 37.9 | 29.1 | 41.3 |

| Country | Images | Regions | Recall@IoU≥0.5 % | Recall@cov≥0.9 % | Portrait IoU % | Signature IoU % | MRZ IoU % | Text IoU % |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| AT | 5 | 27 | 40.7 | 33.3 | 100.0 | 100.0 | 100.0 | 11.1 |
| BE | 2 | 9 | 77.8 | 66.7 | 100.0 | 100.0 | 100.0 | 60.0 |
| BG | 2 | 19 | 47.4 | 26.3 | 100.0 | 100.0 | 100.0 | 33.3 |
| CY | 2 | 13 | 23.1 | 7.7 | 100.0 | 100.0 | 100.0 | 0.0 |
| CZ | 2 | 12 | 41.7 | 50.0 | 100.0 | 100.0 | 100.0 | 22.2 |
| DE | 6 | 33 | 33.3 | 33.3 | 100.0 | 100.0 | 100.0 | 4.3 |
| EE | 2 | 11 | 27.3 | 27.3 | 100.0 | 100.0 | 100.0 | 0.0 |
| ES | 3 | 24 | 25.0 | 25.0 | 100.0 | 100.0 | 100.0 | 0.0 |
| FI | 2 | 11 | 27.3 | 18.2 | 66.7 | 100.0 | 0.0 | 0.0 |
| FR | 4 | 29 | 24.1 | 20.7 | 83.3 | 50.0 | 33.3 | 0.0 |
| GR | 2 | 13 | 38.5 | 30.8 | 100.0 | 100.0 | 0.0 | 22.2 |
| HR | 2 | 10 | 80.0 | 30.0 | 100.0 | 100.0 | 100.0 | 71.4 |
| HU | 6 | 42 | 19.1 | 21.4 | 66.7 | 50.0 | 66.7 | 0.0 |
| IT | 4 | 21 | 52.4 | 33.3 | 100.0 | 100.0 | 100.0 | 33.3 |
| LT | 2 | 11 | 27.3 | 18.2 | 100.0 | 100.0 | 0.0 | 0.0 |
| LU | 2 | 12 | 50.0 | 33.3 | 66.7 | 100.0 | 100.0 | 16.7 |
| LV | 2 | 12 | 50.0 | 58.3 | 100.0 | 0.0 | 100.0 | 16.7 |
| MT | 1 | 5 | 40.0 | 20.0 | 100.0 | - | 100.0 | 0.0 |
| NL | 2 | 11 | 72.7 | 27.3 | 100.0 | 100.0 | 100.0 | 57.1 |
| PL | 5 | 34 | 35.3 | 32.4 | 85.7 | 100.0 | 50.0 | 9.1 |
| RO | 1 | 8 | 50.0 | 12.5 | 100.0 | 0.0 | - | 50.0 |
| SE | 2 | 10 | 20.0 | 20.0 | 100.0 | 0.0 | 100.0 | 0.0 |
| SI | 2 | 13 | 46.2 | 15.4 | 100.0 | 100.0 | 100.0 | 12.5 |
| SK | 2 | 16 | 50.0 | 43.8 | 100.0 | 100.0 | - | 33.3 |

| Document type | Images | Regions | Recall@IoU≥0.5 % | Recall@cov≥0.9 % |
|---|---:|---:|---:|---:|
| driving_licence | 10 | 46 | 39.1 | 34.8 |
| id_card | 49 | 304 | 39.1 | 28.9 |
| passport | 6 | 56 | 30.4 | 25.0 |

Over-masking (covered area outside every labelled region, mean share of the image): 4.0 %. Errors: none.

SAM: 260 calls (4.0 per image), estimated $0.65 at $0.0025/call; this run 260 live, 0 cached.
Latency: SAM per call p50 1394.5 ms / p95 2363.7 ms; SAM per image p50 5320.0 ms / p95 9149.7 ms (sequential calls); OCR + detection per image p50 1901.3 ms / p95 7190.0 ms; total per image p50 8022.3 ms / p95 12604.3 ms.
