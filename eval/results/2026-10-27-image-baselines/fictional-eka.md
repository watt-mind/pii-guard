# Image baseline eka on fictional specimen-style documents (Muse Image)

24 specimen images, baseline `eka` (eka-pii-redaction). A region is a hit at IoU ≥ 0.5 with one covered box; coverage is the share of its pixels under any mask (cov ≥ 0.9 = fully covered).

| Region type | Regions | Recall@IoU≥0.5 % | Recall@cov≥0.9 % | Mean coverage % |
|---|---:|---:|---:|---:|
| portrait | 18 | 100.0 | 100.0 | 99.4 |
| signature | 15 | 86.7 | 80.0 | 83.2 |
| mrz | 6 | 0.0 | 0.0 | 67.7 |
| text | 110 | 91.8 | 80.0 | 89.7 |
| **all** | 149 | 88.6 | 79.2 | 89.3 |

| Country | Images | Regions | Recall@IoU≥0.5 % | Recall@cov≥0.9 % | Portrait IoU % | Signature IoU % | MRZ IoU % | Text IoU % |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| DE | 8 | 50 | 88.0 | 78.0 | 100.0 | 80.0 | 0.0 | 91.9 |
| GB | 8 | 49 | 91.8 | 79.6 | 100.0 | 100.0 | 0.0 | 94.4 |
| HU | 8 | 50 | 86.0 | 80.0 | 100.0 | 80.0 | 0.0 | 89.2 |

| Document type | Images | Regions | Recall@IoU≥0.5 % | Recall@cov≥0.9 % |
|---|---:|---:|---:|---:|
| badge | 3 | 12 | 100.0 | 100.0 |
| driving_licence | 3 | 15 | 80.0 | 80.0 |
| form | 3 | 27 | 96.3 | 77.8 |
| id_card | 6 | 29 | 79.3 | 75.9 |
| letter | 3 | 24 | 91.7 | 66.7 |
| member_card | 3 | 15 | 93.3 | 86.7 |
| passport | 3 | 27 | 85.2 | 81.5 |

Over-masking (covered area outside every labelled region, mean share of the image): 3.2 %. Errors: none.

Latency (the tool's own time per image, without the worker pipe): p50 672.3 ms / p95 880.7 ms.
