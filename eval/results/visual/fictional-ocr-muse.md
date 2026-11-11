# OCR on fictional specimen-style documents: Muse Spark Open (LAB-1796, SAM stubbed)

24 specimen images, SAM `sam-3.1` (FACE, SIGNATURE, ID_PHOTO), OCR `muse-cached`, text detector `rules+captions` (OCR on images enlarged to 2000 px). A region is a hit at IoU ≥ 0.5 with one covered box; coverage is the share of its pixels under any mask (cov ≥ 0.9 = fully covered).

| Region type | Regions | Recall@IoU≥0.5 % | Recall@cov≥0.9 % | Mean coverage % |
|---|---:|---:|---:|---:|
| portrait | 18 | 0.0 | 0.0 | 0.0 |
| signature | 15 | 0.0 | 0.0 | 1.3 |
| mrz | 6 | 83.3 | 83.3 | 82.4 |
| text | 110 | 0.0 | 84.5 | 87.8 |
| **all** | 149 | 3.4 | 65.8 | 68.3 |

| Country | Images | Regions | Recall@IoU≥0.5 % | Recall@cov≥0.9 % | Portrait IoU % | Signature IoU % | MRZ IoU % | Text IoU % |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| DE | 8 | 50 | 4.0 | 64.0 | 0.0 | 0.0 | 100.0 | 0.0 |
| GB | 8 | 49 | 4.1 | 65.3 | 0.0 | 0.0 | 100.0 | 0.0 |
| HU | 8 | 50 | 2.0 | 68.0 | 0.0 | 0.0 | 50.0 | 0.0 |

| Document type | Images | Regions | Recall@IoU≥0.5 % | Recall@cov≥0.9 % |
|---|---:|---:|---:|---:|
| badge | 3 | 12 | 0.0 | 33.3 |
| driving_licence | 3 | 15 | 0.0 | 60.0 |
| form | 3 | 27 | 0.0 | 66.7 |
| id_card | 6 | 29 | 10.3 | 79.3 |
| letter | 3 | 24 | 0.0 | 54.2 |
| member_card | 3 | 15 | 0.0 | 73.3 |
| passport | 3 | 27 | 7.4 | 74.1 |

Over-masking (covered area outside every labelled region, mean share of the image): 6.7 %. Errors: none.

SAM: 96 calls (4.0 per image), estimated $0.24 at $0.0025/call; this run 0 live, 96 cached.
Latency: SAM per call p50 0.0 ms / p95 0.1 ms; SAM per image p50 0.1 ms / p95 0.2 ms (sequential calls); OCR + detection per image p50 120.0 ms / p95 269.1 ms; total per image p50 120.0 ms / p95 269.2 ms.

Note (LAB-1796): SAM was stubbed to return nothing, so only OCR differs between this record and its pair (fictional-ocr-muse.md / fictional-ocr-tesseract.md); the SAM call count and cost lines above are the stub, not spend. OCR words replayed from eval/fixtures/visual/ocr/muse.json (recorded live on Baseten, 2026-11-02: p50 8.2 s, p95 16.8 s per image, no image failed closed); the latency above is the replay.
