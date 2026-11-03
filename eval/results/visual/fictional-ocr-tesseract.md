# OCR on fictional specimen-style documents: Tesseract (LAB-1796, SAM stubbed)

24 specimen images, SAM `sam-3.1` (FACE, SIGNATURE, ID_PHOTO), OCR `tesseract`, text detector `rules+captions` (OCR on images enlarged to 2000 px). A region is a hit at IoU ≥ 0.5 with one covered box; coverage is the share of its pixels under any mask (cov ≥ 0.9 = fully covered).

| Region type | Regions | Recall@IoU≥0.5 % | Recall@cov≥0.9 % | Mean coverage % |
|---|---:|---:|---:|---:|
| portrait | 18 | 0.0 | 0.0 | 0.0 |
| signature | 15 | 0.0 | 0.0 | 0.0 |
| mrz | 6 | 100.0 | 100.0 | 99.1 |
| text | 110 | 87.3 | 85.5 | 87.2 |
| **all** | 149 | 68.5 | 67.1 | 68.4 |

| Country | Images | Regions | Recall@IoU≥0.5 % | Recall@cov≥0.9 % | Portrait IoU % | Signature IoU % | MRZ IoU % | Text IoU % |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| DE | 8 | 50 | 70.0 | 70.0 | 0.0 | 0.0 | 100.0 | 89.2 |
| GB | 8 | 49 | 65.3 | 65.3 | 0.0 | 0.0 | 100.0 | 83.3 |
| HU | 8 | 50 | 70.0 | 66.0 | 0.0 | 0.0 | 100.0 | 89.2 |

| Document type | Images | Regions | Recall@IoU≥0.5 % | Recall@cov≥0.9 % |
|---|---:|---:|---:|---:|
| badge | 3 | 12 | 50.0 | 50.0 |
| driving_licence | 3 | 15 | 60.0 | 60.0 |
| form | 3 | 27 | 77.8 | 77.8 |
| id_card | 6 | 29 | 79.3 | 75.9 |
| letter | 3 | 24 | 45.8 | 45.8 |
| member_card | 3 | 15 | 73.3 | 73.3 |
| passport | 3 | 27 | 77.8 | 74.1 |

Over-masking (covered area outside every labelled region, mean share of the image): 0.5 %. Errors: none.

SAM: 96 calls (4.0 per image), estimated $0.24 at $0.0025/call; this run 0 live, 96 cached.
Latency: SAM per call p50 0.0 ms / p95 0.1 ms; SAM per image p50 0.1 ms / p95 0.2 ms (sequential calls); OCR + detection per image p50 1144.9 ms / p95 1511.4 ms; total per image p50 1145.0 ms / p95 1511.6 ms.

Note (LAB-1796): SAM was stubbed to return nothing, so only OCR differs between this record and its pair (fictional-ocr-muse.md / fictional-ocr-tesseract.md); the SAM call count and cost lines above are the stub, not spend. Tesseract ran live on the device.
