# SAM prompt study (SAM only, one prompt at a time)

| Type | Prompt | Targets | Regions | Recall@IoU≥0.5 % | Recall@cov≥0.9 % | Mean coverage % | Found | Stray | Errors |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| FACE | `face` | portrait | 37 | 75.7 | 16.2 | 66.0 | 40 | 3 | 0 |
| FACE | `portrait` | portrait | 37 | 64.9 | 67.6 | 72.1 | 27 | 0 | 0 |
| FACE | `head` | portrait | 37 | 86.5 | 51.3 | 85.0 | 40 | 3 | 0 |
| ID_PHOTO | `id photo` | portrait | 37 | 0.0 | 0.0 | 0.0 | 0 | 0 | 0 |
| ID_PHOTO | `photo of a person` | portrait | 37 | 89.2 | 51.3 | 83.9 | 40 | 3 | 0 |
| ID_PHOTO | `passport photo` | portrait | 37 | 0.0 | 0.0 | 0.0 | 0 | 0 | 0 |
| SIGNATURE | `signature` | signature | 30 | 90.0 | 40.0 | 81.0 | 29 | 1 | 0 |
| SIGNATURE | `squiggly line` | signature | 30 | 0.0 | 0.0 | 0.0 | 6 | 6 | 0 |
| SIGNATURE | `handwriting` | signature | 30 | 40.0 | 23.3 | 37.3 | 14 | 0 | 0 |
| SIGNATURE | `handwritten signature` | signature | 30 | 63.3 | 30.0 | 56.5 | 19 | 0 | 0 |
| SIGNATURE | `scribble` | signature | 30 | 0.0 | 0.0 | 0.0 | 0 | 0 | 0 |
