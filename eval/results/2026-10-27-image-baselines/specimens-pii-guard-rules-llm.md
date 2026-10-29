# pii-guard (rules,llm) on official specimen ID documents

65 specimen images, SAM `sam-3.1` (FACE, SIGNATURE, ID_PHOTO), OCR `tesseract`, text detector `rules+llm+captions` (OCR on images enlarged to 2000 px). A region is a hit at IoU ≥ 0.5 with one covered box; coverage is the share of its pixels under any mask (cov ≥ 0.9 = fully covered).

| Region type | Regions | Recall@IoU≥0.5 % | Recall@cov≥0.9 % | Mean coverage % |
|---|---:|---:|---:|---:|
| portrait | 65 | 90.8 | 73.9 | 87.7 |
| signature | 37 | 83.8 | 64.9 | 82.8 |
| mrz | 30 | 80.0 | 60.0 | 75.7 |
| text | 274 | 30.3 | 19.7 | 39.1 |
| **all** | 406 | 48.5 | 35.5 | 53.6 |

| Country | Images | Regions | Recall@IoU≥0.5 % | Recall@cov≥0.9 % | Portrait IoU % | Signature IoU % | MRZ IoU % | Text IoU % |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| AT | 5 | 27 | 44.4 | 33.3 | 100.0 | 100.0 | 100.0 | 16.7 |
| BE | 2 | 9 | 100.0 | 66.7 | 100.0 | 100.0 | 100.0 | 100.0 |
| BG | 2 | 19 | 68.4 | 26.3 | 100.0 | 100.0 | 100.0 | 60.0 |
| CY | 2 | 13 | 30.8 | 7.7 | 100.0 | 100.0 | 100.0 | 10.0 |
| CZ | 2 | 12 | 50.0 | 50.0 | 100.0 | 100.0 | 100.0 | 33.3 |
| DE | 6 | 33 | 60.6 | 54.5 | 100.0 | 100.0 | 100.0 | 43.5 |
| EE | 2 | 11 | 54.5 | 72.7 | 100.0 | 100.0 | 100.0 | 37.5 |
| ES | 3 | 24 | 37.5 | 41.7 | 100.0 | 100.0 | 100.0 | 16.7 |
| FI | 2 | 11 | 54.5 | 18.2 | 66.7 | 100.0 | 0.0 | 50.0 |
| FR | 4 | 29 | 27.6 | 20.7 | 83.3 | 50.0 | 66.7 | 0.0 |
| GR | 2 | 13 | 53.8 | 38.5 | 100.0 | 100.0 | 0.0 | 44.4 |
| HR | 2 | 10 | 90.0 | 50.0 | 100.0 | 100.0 | 100.0 | 85.7 |
| HU | 6 | 42 | 26.2 | 26.2 | 66.7 | 50.0 | 66.7 | 10.3 |
| IT | 4 | 21 | 57.1 | 38.1 | 100.0 | 100.0 | 100.0 | 40.0 |
| LT | 2 | 11 | 27.3 | 36.4 | 100.0 | 100.0 | 0.0 | 0.0 |
| LU | 2 | 12 | 58.3 | 33.3 | 66.7 | 100.0 | 100.0 | 33.3 |
| LV | 2 | 12 | 75.0 | 66.7 | 100.0 | 0.0 | 100.0 | 66.7 |
| MT | 1 | 5 | 40.0 | 20.0 | 100.0 | - | 100.0 | 0.0 |
| NL | 2 | 11 | 81.8 | 27.3 | 100.0 | 100.0 | 100.0 | 71.4 |
| PL | 5 | 34 | 35.3 | 35.3 | 85.7 | 100.0 | 50.0 | 9.1 |
| RO | 1 | 8 | 75.0 | 12.5 | 100.0 | 0.0 | - | 83.3 |
| SE | 2 | 10 | 20.0 | 20.0 | 100.0 | 0.0 | 100.0 | 0.0 |
| SI | 2 | 13 | 46.2 | 15.4 | 100.0 | 100.0 | 100.0 | 12.5 |
| SK | 2 | 16 | 56.2 | 43.8 | 100.0 | 100.0 | - | 41.7 |

| Document type | Images | Regions | Recall@IoU≥0.5 % | Recall@cov≥0.9 % |
|---|---:|---:|---:|---:|
| driving_licence | 10 | 46 | 50.0 | 39.1 |
| id_card | 49 | 304 | 49.7 | 33.9 |
| passport | 6 | 56 | 41.1 | 41.1 |

Over-masking (covered area outside every labelled region, mean share of the image): 4.7 %. Errors: none.

SAM: 260 calls (4.0 per image), estimated $0.65 at $0.0025/call; this run 0 live, 260 cached.
Latency: SAM per call p50 1394.5 ms / p95 2363.7 ms; SAM per image p50 5319.9 ms / p95 9149.7 ms (sequential calls); OCR + detection per image p50 4151.7 ms / p95 6316.6 ms; total per image p50 9504.1 ms / p95 12309.1 ms.
