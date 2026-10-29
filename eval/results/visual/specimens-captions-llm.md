# Visual recall on official specimen ID documents

65 specimen images, SAM `sam-3.1` (FACE, SIGNATURE, ID_PHOTO), OCR `tesseract`, text detector `rules+llm+captions` (OCR on images enlarged to 2000 px). A region is a hit at IoU ≥ 0.5 with one covered box; coverage is the share of its pixels under any mask (cov ≥ 0.9 = fully covered).

| Region type | Regions | Recall@IoU≥0.5 % | Recall@cov≥0.9 % | Mean coverage % |
|---|---:|---:|---:|---:|
| portrait | 65 | 90.8 | 73.9 | 87.7 |
| signature | 37 | 83.8 | 64.9 | 82.9 |
| mrz | 30 | 80.0 | 60.0 | 75.7 |
| text | 274 | 29.2 | 20.1 | 38.6 |
| **all** | 406 | 47.8 | 35.7 | 53.3 |

| Country | Images | Regions | Recall@IoU≥0.5 % | Recall@cov≥0.9 % | Portrait IoU % | Signature IoU % | MRZ IoU % | Text IoU % |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| AT | 5 | 27 | 44.4 | 33.3 | 100.0 | 100.0 | 100.0 | 16.7 |
| BE | 2 | 9 | 100.0 | 66.7 | 100.0 | 100.0 | 100.0 | 100.0 |
| BG | 2 | 19 | 57.9 | 26.3 | 100.0 | 100.0 | 100.0 | 46.7 |
| CY | 2 | 13 | 30.8 | 7.7 | 100.0 | 100.0 | 100.0 | 10.0 |
| CZ | 2 | 12 | 41.7 | 50.0 | 100.0 | 100.0 | 100.0 | 22.2 |
| DE | 6 | 33 | 60.6 | 54.5 | 100.0 | 100.0 | 100.0 | 43.5 |
| EE | 2 | 11 | 63.6 | 81.8 | 100.0 | 100.0 | 100.0 | 50.0 |
| ES | 3 | 24 | 37.5 | 41.7 | 100.0 | 100.0 | 100.0 | 16.7 |
| FI | 2 | 11 | 54.5 | 18.2 | 66.7 | 100.0 | 0.0 | 50.0 |
| FR | 4 | 29 | 27.6 | 20.7 | 83.3 | 50.0 | 66.7 | 0.0 |
| GR | 2 | 13 | 53.8 | 38.5 | 100.0 | 100.0 | 0.0 | 44.4 |
| HR | 2 | 10 | 80.0 | 40.0 | 100.0 | 100.0 | 100.0 | 71.4 |
| HU | 6 | 42 | 26.2 | 26.2 | 66.7 | 50.0 | 66.7 | 10.3 |
| IT | 4 | 21 | 57.1 | 38.1 | 100.0 | 100.0 | 100.0 | 40.0 |
| LT | 2 | 11 | 27.3 | 36.4 | 100.0 | 100.0 | 0.0 | 0.0 |
| LU | 2 | 12 | 58.3 | 33.3 | 66.7 | 100.0 | 100.0 | 33.3 |
| LV | 2 | 12 | 75.0 | 66.7 | 100.0 | 0.0 | 100.0 | 66.7 |
| MT | 1 | 5 | 60.0 | 20.0 | 100.0 | - | 100.0 | 33.3 |
| NL | 2 | 11 | 81.8 | 36.4 | 100.0 | 100.0 | 100.0 | 71.4 |
| PL | 5 | 34 | 35.3 | 35.3 | 85.7 | 100.0 | 50.0 | 9.1 |
| RO | 1 | 8 | 75.0 | 12.5 | 100.0 | 0.0 | - | 83.3 |
| SE | 2 | 10 | 20.0 | 20.0 | 100.0 | 0.0 | 100.0 | 0.0 |
| SI | 2 | 13 | 46.2 | 15.4 | 100.0 | 100.0 | 100.0 | 12.5 |
| SK | 2 | 16 | 50.0 | 43.8 | 100.0 | 100.0 | - | 33.3 |

| Document type | Images | Regions | Recall@IoU≥0.5 % | Recall@cov≥0.9 % |
|---|---:|---:|---:|---:|
| driving_licence | 10 | 46 | 50.0 | 39.1 |
| id_card | 49 | 304 | 48.7 | 34.2 |
| passport | 6 | 56 | 41.1 | 41.1 |

Over-masking (covered area outside every labelled region, mean share of the image): 4.8 %. Errors: none.

SAM: 260 calls (4.0 per image), estimated $0.65 at $0.0025/call; this run 0 live, 260 cached.
Latency: SAM per call p50 1595.9 ms / p95 3411.1 ms; SAM per image p50 6586.0 ms / p95 11423.8 ms (sequential calls); OCR + detection per image p50 5695.8 ms / p95 8528.7 ms.
