# Image baseline eka-tuned on fictional specimen-style documents (Muse Image)

24 specimen images, baseline `eka-tuned` (eka-pii-redaction). A region is a hit at IoU ≥ 0.5 with one covered box; coverage is the share of its pixels under any mask (cov ≥ 0.9 = fully covered).

| Region type | Regions | Recall@IoU≥0.5 % | Recall@cov≥0.9 % | Mean coverage % |
|---|---:|---:|---:|---:|
| portrait | 18 | 100.0 | 100.0 | 99.4 |
| signature | 15 | 86.7 | 80.0 | 83.3 |
| mrz | 6 | 0.0 | 0.0 | 57.4 |
| text | 110 | 95.5 | 90.9 | 95.1 |
| **all** | 149 | 91.3 | 87.2 | 92.9 |

| Country | Images | Regions | Recall@IoU≥0.5 % | Recall@cov≥0.9 % | Portrait IoU % | Signature IoU % | MRZ IoU % | Text IoU % |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| DE | 8 | 50 | 88.0 | 84.0 | 100.0 | 80.0 | 0.0 | 91.9 |
| GB | 8 | 49 | 95.9 | 93.9 | 100.0 | 100.0 | 0.0 | 100.0 |
| HU | 8 | 50 | 90.0 | 84.0 | 100.0 | 80.0 | 0.0 | 94.6 |

| Document type | Images | Regions | Recall@IoU≥0.5 % | Recall@cov≥0.9 % |
|---|---:|---:|---:|---:|
| badge | 3 | 12 | 100.0 | 100.0 |
| driving_licence | 3 | 15 | 86.7 | 80.0 |
| form | 3 | 27 | 96.3 | 96.3 |
| id_card | 6 | 29 | 89.7 | 82.8 |
| letter | 3 | 24 | 91.7 | 83.3 |
| member_card | 3 | 15 | 86.7 | 86.7 |
| passport | 3 | 27 | 88.9 | 85.2 |

Over-masking (covered area outside every labelled region, mean share of the image): 3.2 %. Errors: none.

Latency (the tool's own time per image, without the worker pipe): p50 1212.6 ms / p95 1403.1 ms.
