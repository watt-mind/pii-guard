# pii-guard (rules) on fictional specimen-style documents (Muse Image)

24 specimen images, SAM `sam-3.1` (FACE, SIGNATURE, ID_PHOTO), OCR `tesseract`, text detector `rules+captions` (OCR on images enlarged to 2000 px). A region is a hit at IoU ≥ 0.5 with one covered box; coverage is the share of its pixels under any mask (cov ≥ 0.9 = fully covered).

| Region type | Regions | Recall@IoU≥0.5 % | Recall@cov≥0.9 % | Mean coverage % |
|---|---:|---:|---:|---:|
| portrait | 18 | 100.0 | 100.0 | 98.9 |
| signature | 15 | 100.0 | 100.0 | 97.1 |
| mrz | 6 | 100.0 | 100.0 | 99.1 |
| text | 110 | 87.3 | 85.5 | 87.2 |
| **all** | 149 | 90.6 | 89.3 | 90.1 |

| Country | Images | Regions | Recall@IoU≥0.5 % | Recall@cov≥0.9 % | Portrait IoU % | Signature IoU % | MRZ IoU % | Text IoU % |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| DE | 8 | 50 | 92.0 | 92.0 | 100.0 | 100.0 | 100.0 | 89.2 |
| GB | 8 | 49 | 87.8 | 87.8 | 100.0 | 100.0 | 100.0 | 83.3 |
| HU | 8 | 50 | 92.0 | 88.0 | 100.0 | 100.0 | 100.0 | 89.2 |

| Document type | Images | Regions | Recall@IoU≥0.5 % | Recall@cov≥0.9 % |
|---|---:|---:|---:|---:|
| badge | 3 | 12 | 75.0 | 75.0 |
| driving_licence | 3 | 15 | 100.0 | 100.0 |
| form | 3 | 27 | 100.0 | 100.0 |
| id_card | 6 | 29 | 100.0 | 96.5 |
| letter | 3 | 24 | 58.3 | 58.3 |
| member_card | 3 | 15 | 93.3 | 93.3 |
| passport | 3 | 27 | 100.0 | 96.3 |

Over-masking (covered area outside every labelled region, mean share of the image): 1.2 %. Errors: none.

SAM: 96 calls (4.0 per image), estimated $0.24 at $0.0025/call; this run 96 live, 0 cached.
Latency: SAM per call p50 1203.3 ms / p95 1945.2 ms; SAM per image p50 4868.6 ms / p95 6799.8 ms (sequential calls); OCR + detection per image p50 1384.3 ms / p95 4203.1 ms; total per image p50 6384.8 ms / p95 9565.8 ms.
