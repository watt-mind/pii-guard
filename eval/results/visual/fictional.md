# Visual recall on fictional specimen-style documents (Muse Image)

24 specimen images, SAM `sam-3.1` (FACE, SIGNATURE, ID_PHOTO), OCR `tesseract`, text detector `rules`. A region is a hit at IoU ≥ 0.5 with one covered box; coverage is the share of its pixels under any mask (cov ≥ 0.9 = fully covered).

| Region type | Regions | Recall@IoU≥0.5 % | Recall@cov≥0.9 % | Mean coverage % |
|---|---:|---:|---:|---:|
| portrait | 18 | 100.0 | 100.0 | 98.9 |
| signature | 15 | 100.0 | 100.0 | 97.1 |
| mrz | 6 | 0.0 | 0.0 | 10.1 |
| text | 110 | 34.5 | 34.5 | 35.2 |
| **all** | 149 | 47.6 | 47.6 | 48.1 |

| Country | Images | Regions | Recall@IoU≥0.5 % | Recall@cov≥0.9 % | Portrait IoU % | Signature IoU % | MRZ IoU % | Text IoU % |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| DE | 8 | 50 | 48.0 | 48.0 | 100.0 | 100.0 | 0.0 | 35.1 |
| GB | 8 | 49 | 38.8 | 38.8 | 100.0 | 100.0 | 0.0 | 22.2 |
| HU | 8 | 50 | 56.0 | 56.0 | 100.0 | 100.0 | 0.0 | 46.0 |

| Document type | Images | Regions | Recall@IoU≥0.5 % | Recall@cov≥0.9 % |
|---|---:|---:|---:|---:|
| badge | 3 | 12 | 66.7 | 66.7 |
| driving_licence | 3 | 15 | 46.7 | 46.7 |
| form | 3 | 27 | 63.0 | 63.0 |
| id_card | 6 | 29 | 34.5 | 34.5 |
| letter | 3 | 24 | 54.2 | 54.2 |
| member_card | 3 | 15 | 40.0 | 40.0 |
| passport | 3 | 27 | 37.0 | 37.0 |

Over-masking (covered area outside every labelled region, mean share of the image): 0.8 %. Errors: none.

SAM: 96 calls (4.0 per image), estimated $0.24 at $0.0025/call; this run 8 live, 88 cached.
Latency: SAM per call p50 1204.7 ms / p95 2312.0 ms; SAM per image p50 5159.2 ms / p95 8837.0 ms (sequential calls); OCR + detection per image p50 633.8 ms / p95 1037.2 ms.
