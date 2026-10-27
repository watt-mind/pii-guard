# pii-guard (rules,llm) on fictional specimen-style documents (Muse Image)

24 specimen images, SAM `sam-3.1` (FACE, SIGNATURE, ID_PHOTO), OCR `tesseract`, text detector `rules+llm+captions` (OCR on images enlarged to 2000 px). A region is a hit at IoU ≥ 0.5 with one covered box; coverage is the share of its pixels under any mask (cov ≥ 0.9 = fully covered).

| Region type | Regions | Recall@IoU≥0.5 % | Recall@cov≥0.9 % | Mean coverage % |
|---|---:|---:|---:|---:|
| portrait | 18 | 100.0 | 100.0 | 98.9 |
| signature | 15 | 100.0 | 100.0 | 97.2 |
| mrz | 6 | 100.0 | 100.0 | 99.1 |
| text | 110 | 100.0 | 97.3 | 99.6 |
| **all** | 149 | 100.0 | 98.0 | 99.2 |

| Country | Images | Regions | Recall@IoU≥0.5 % | Recall@cov≥0.9 % | Portrait IoU % | Signature IoU % | MRZ IoU % | Text IoU % |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| DE | 8 | 50 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 |
| GB | 8 | 49 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 |
| HU | 8 | 50 | 100.0 | 94.0 | 100.0 | 100.0 | 100.0 | 100.0 |

| Document type | Images | Regions | Recall@IoU≥0.5 % | Recall@cov≥0.9 % |
|---|---:|---:|---:|---:|
| badge | 3 | 12 | 100.0 | 100.0 |
| driving_licence | 3 | 15 | 100.0 | 100.0 |
| form | 3 | 27 | 100.0 | 100.0 |
| id_card | 6 | 29 | 100.0 | 96.5 |
| letter | 3 | 24 | 100.0 | 95.8 |
| member_card | 3 | 15 | 100.0 | 100.0 |
| passport | 3 | 27 | 100.0 | 96.3 |

Over-masking (covered area outside every labelled region, mean share of the image): 1.2 %. Errors: none.

SAM: 96 calls (4.0 per image), estimated $0.24 at $0.0025/call; this run 0 live, 96 cached.
Latency: SAM per call p50 1203.3 ms / p95 1945.2 ms; SAM per image p50 4868.6 ms / p95 6799.7 ms (sequential calls); OCR + detection per image p50 3745.6 ms / p95 5468.6 ms; total per image p50 8351.3 ms / p95 11641.7 ms.
