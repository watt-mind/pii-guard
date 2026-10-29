# Image baseline presidio-image-tuned on fictional specimen-style documents (Muse Image)

24 specimen images, baseline `presidio-image-tuned` (presidio-image-redactor; can't mask portrait, signature). A region is a hit at IoU ≥ 0.5 with one covered box; coverage is the share of its pixels under any mask (cov ≥ 0.9 = fully covered).

| Region type | Regions | Recall@IoU≥0.5 % | Recall@cov≥0.9 % | Mean coverage % |
|---|---:|---:|---:|---:|
| mrz | 6 | 0.0 | 0.0 | 1.0 |
| text | 110 | 50.9 | 47.3 | 54.5 |
| **all** | 149 | 38.3 | 35.6 | 40.9 |

| Country | Images | Regions | Recall@IoU≥0.5 % | Recall@cov≥0.9 % | Portrait IoU % | Signature IoU % | MRZ IoU % | Text IoU % |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| DE | 8 | 50 | 38.0 | 36.0 | - | - | 0.0 | 51.3 |
| GB | 8 | 49 | 40.8 | 40.8 | - | - | 0.0 | 52.8 |
| HU | 8 | 50 | 36.0 | 30.0 | - | - | 0.0 | 48.6 |

| Document type | Images | Regions | Recall@IoU≥0.5 % | Recall@cov≥0.9 % |
|---|---:|---:|---:|---:|
| badge | 3 | 12 | 66.7 | 66.7 |
| driving_licence | 3 | 15 | 26.7 | 26.7 |
| form | 3 | 27 | 51.8 | 48.1 |
| id_card | 6 | 29 | 20.7 | 20.7 |
| letter | 3 | 24 | 54.2 | 45.8 |
| member_card | 3 | 15 | 20.0 | 20.0 |
| passport | 3 | 27 | 33.3 | 29.6 |

Over-masking (covered area outside every labelled region, mean share of the image): 1.1 %. Errors: none.

Latency (the tool's own time per image, without the worker pipe): p50 942.6 ms / p95 1163.7 ms.
