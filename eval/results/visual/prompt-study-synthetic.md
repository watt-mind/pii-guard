# SAM prompt study (SAM only, one prompt at a time)

| Type | Prompt | Targets | Regions | Recall@IoU≥0.5 % | Recall@cov≥0.9 % | Mean coverage % | Found | Stray | Errors |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| SIGNATURE | `signature` | signature | 12 | 41.7 | 0.0 | 36.3 | 5 | 0 | 0 |
| SIGNATURE | `squiggly line` | signature | 12 | 25.0 | 0.0 | 21.8 | 3 | 0 | 0 |
| SIGNATURE | `handwritten signature` | signature | 12 | 41.7 | 0.0 | 36.3 | 5 | 0 | 0 |
| SIGNATURE | `handwriting` | signature | 12 | 41.7 | 0.0 | 36.3 | 5 | 0 | 0 |
| SIGNATURE | `scribble` | signature | 12 | 16.7 | 0.0 | 14.2 | 2 | 0 | 0 |
| SIGNATURE | `cursive writing` | signature | 12 | 25.0 | 0.0 | 21.7 | 3 | 0 | 0 |
| ID_PHOTO | `photo of a person` | portrait | 6 | 66.7 | 50.0 | 62.2 | 4 | 0 | 0 |
| ID_PHOTO | `id photo` | portrait | 6 | 66.7 | 66.7 | 66.7 | 4 | 0 | 0 |
| ID_PHOTO | `passport photo` | portrait | 6 | 0.0 | 0.0 | 0.0 | 0 | 0 | 0 |
| ID_PHOTO | `portrait` | portrait | 6 | 100.0 | 100.0 | 100.0 | 6 | 0 | 0 |
| FACE | `face` | portrait | 6 | 83.3 | 0.0 | 60.6 | 6 | 0 | 0 |
| FACE | `head` | portrait | 6 | 100.0 | 16.7 | 77.0 | 6 | 0 | 0 |
| STAMP | `stamp` | stamp | 6 | 83.3 | 50.0 | 75.1 | 5 | 0 | 0 |
| STAMP | `rubber stamp` | stamp | 6 | 0.0 | 0.0 | 0.0 | 0 | 0 | 0 |
| STAMP | `seal` | stamp | 6 | 33.3 | 0.0 | 29.3 | 2 | 0 | 0 |
| STAMP | `ink stamp` | stamp | 6 | 0.0 | 0.0 | 0.0 | 0 | 0 | 0 |

## By variant

| Type | Prompt | Variant | Regions | Recall@IoU≥0.5 % | Recall@cov≥0.9 % | Mean coverage % |
|---|---|---|---:|---:|---:|---:|
| SIGNATURE | `signature` | scanned | 4 | 50.0 | 0.0 | 44.8 |
| SIGNATURE | `signature` | scribble | 4 | 75.0 | 0.0 | 64.1 |
| SIGNATURE | `signature` | script | 4 | 0.0 | 0.0 | 0.0 |
| SIGNATURE | `squiggly line` | scanned | 4 | 25.0 | 0.0 | 22.5 |
| SIGNATURE | `squiggly line` | scribble | 4 | 50.0 | 0.0 | 42.8 |
| SIGNATURE | `squiggly line` | script | 4 | 0.0 | 0.0 | 0.0 |
| SIGNATURE | `handwritten signature` | scanned | 4 | 50.0 | 0.0 | 44.8 |
| SIGNATURE | `handwritten signature` | scribble | 4 | 75.0 | 0.0 | 64.1 |
| SIGNATURE | `handwritten signature` | script | 4 | 0.0 | 0.0 | 0.0 |
| SIGNATURE | `handwriting` | scanned | 4 | 50.0 | 0.0 | 44.8 |
| SIGNATURE | `handwriting` | scribble | 4 | 75.0 | 0.0 | 64.1 |
| SIGNATURE | `handwriting` | script | 4 | 0.0 | 0.0 | 0.0 |
| SIGNATURE | `scribble` | scanned | 4 | 0.0 | 0.0 | 0.0 |
| SIGNATURE | `scribble` | scribble | 4 | 50.0 | 0.0 | 42.7 |
| SIGNATURE | `scribble` | script | 4 | 0.0 | 0.0 | 0.0 |
| SIGNATURE | `cursive writing` | scanned | 4 | 25.0 | 0.0 | 22.5 |
| SIGNATURE | `cursive writing` | scribble | 4 | 50.0 | 0.0 | 42.5 |
| SIGNATURE | `cursive writing` | script | 4 | 0.0 | 0.0 | 0.0 |
