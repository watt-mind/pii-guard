# Image baseline presidio-image on fictional specimen-style documents (Muse Image)

24 specimen images, baseline `presidio-image` (presidio-image-redactor; can't mask portrait, signature). A region is a hit at IoU ≥ 0.5 with one covered box; coverage is the share of its pixels under any mask (cov ≥ 0.9 = fully covered).

| Region type | Regions | Recall@IoU≥0.5 % | Recall@cov≥0.9 % | Mean coverage % |
|---|---:|---:|---:|---:|
| mrz | 6 | 0.0 | 0.0 | 0.0 |
| text | 110 | 50.9 | 49.1 | 55.0 |
| **all** | 149 | 37.6 | 36.2 | 40.6 |

| Country | Images | Regions | Recall@IoU≥0.5 % | Recall@cov≥0.9 % | Portrait IoU % | Signature IoU % | MRZ IoU % | Text IoU % |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| DE | 8 | 50 | 40.0 | 40.0 | - | - | 0.0 | 54.0 |
| GB | 8 | 49 | 40.8 | 38.8 | - | - | 0.0 | 55.6 |
| HU | 8 | 50 | 32.0 | 30.0 | - | - | 0.0 | 43.2 |

| Document type | Images | Regions | Recall@IoU≥0.5 % | Recall@cov≥0.9 % |
|---|---:|---:|---:|---:|
| badge | 3 | 12 | 66.7 | 66.7 |
| driving_licence | 3 | 15 | 26.7 | 26.7 |
| form | 3 | 27 | 48.1 | 48.1 |
| id_card | 6 | 29 | 13.8 | 10.3 |
| letter | 3 | 24 | 58.3 | 58.3 |
| member_card | 3 | 15 | 20.0 | 20.0 |
| passport | 3 | 27 | 37.0 | 33.3 |

Over-masking (covered area outside every labelled region, mean share of the image): 1.1 %. Errors: none.

Latency (the tool's own time per image, without the worker pipe): p50 375.0 ms / p95 597.6 ms.
