# OCR robustness: fictional set, turned and skewed (LAB-1210)

24 documents, OCR (Tesseract) + rules detector, no SAM. A labelled text / mrz region counts as covered when ≥ 90% of it is masked, scored after turning the cover back onto the upright document. Transforms are degrees counter-clockwise; latency is per image, OCR and detection, six images at a time on one machine.

| Transform | Regions | Covered before % | Covered after % | Lost vs upright before → after | ms p50 before → after | ms p95 before → after |
|---|---:|---:|---:|---:|---:|---:|
| 0° | 116 | 86.2 | 86.2 | 0 → 0 | 1103 → 1139 | 1275 → 1341 |
| 90° | 116 | 0.0 | 86.2 | 100 → 0 | 1170 → 3350 | 1538 → 4221 |
| 180° | 116 | 0.0 | 86.2 | 100 → 0 | 1152 → 2266 | 1517 → 2888 |
| 270° | 116 | 31.0 | 86.2 | 64 → 0 | 1018 → 2029 | 1256 → 2665 |
| 5° | 116 | 53.4 | 84.5 | 40 → 4 | 1006 → 2246 | 1329 → 2852 |
| -10° | 116 | 10.3 | 86.2 | 89 → 2 | 657 → 1938 | 883 → 2605 |
| 15° | 116 | 3.4 | 89.7 | 97 → 1 | 666 → 1864 | 980 → 2346 |

| Screenshot | Identifiers masked before | after | ms after |
|---|---:|---:|---:|
| screenshot-2560-11px | 1/2 | 2/2 | 694 |
| screenshot-3840-13px | 2/2 | 2/2 | 909 |
| screenshot-1280-11px | 2/2 | 2/2 | 366 |
