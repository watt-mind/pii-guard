# Visual recall on fictional specimen-style documents (Muse Image)

24 specimen images, SAM `sam-3.1` (FACE, SIGNATURE, ID_PHOTO), OCR `tesseract`, text detector `rules+llm+captions` (OCR on images enlarged to 2000 px). A region is a hit at IoU ≥ 0.5 with one covered box; coverage is the share of its pixels under any mask (cov ≥ 0.9 = fully covered).

| Region type | Regions | Recall@IoU≥0.5 % | Recall@cov≥0.9 % | Mean coverage % |
|---|---:|---:|---:|---:|
| portrait | 18 | 100.0 | 100.0 | 98.9 |
| signature | 15 | 100.0 | 100.0 | 97.2 |
| mrz | 6 | 100.0 | 100.0 | 99.1 |
| text | 110 | 99.1 | 96.4 | 98.7 |
| **all** | 149 | 99.3 | 97.3 | 98.6 |

| Country | Images | Regions | Recall@IoU≥0.5 % | Recall@cov≥0.9 % | Portrait IoU % | Signature IoU % | MRZ IoU % | Text IoU % |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| DE | 8 | 50 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 |
| GB | 8 | 49 | 98.0 | 98.0 | 100.0 | 100.0 | 100.0 | 97.2 |
| HU | 8 | 50 | 100.0 | 94.0 | 100.0 | 100.0 | 100.0 | 100.0 |

| Document type | Images | Regions | Recall@IoU≥0.5 % | Recall@cov≥0.9 % |
|---|---:|---:|---:|---:|
| badge | 3 | 12 | 100.0 | 100.0 |
| driving_licence | 3 | 15 | 100.0 | 100.0 |
| form | 3 | 27 | 100.0 | 100.0 |
| id_card | 6 | 29 | 100.0 | 96.5 |
| letter | 3 | 24 | 100.0 | 95.8 |
| member_card | 3 | 15 | 93.3 | 93.3 |
| passport | 3 | 27 | 100.0 | 96.3 |

Over-masking (covered area outside every labelled region, mean share of the image): 1.2 %. Errors: none.

SAM: 96 calls (4.0 per image), estimated $0.24 at $0.0025/call; this run 0 live, 96 cached.
Latency: SAM per call p50 1420.0 ms / p95 2608.7 ms; SAM per image p50 6045.3 ms / p95 7615.7 ms (sequential calls); OCR + detection per image p50 4571.2 ms / p95 6289.1 ms.
