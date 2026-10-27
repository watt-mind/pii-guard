# OCR robustness: specimens set, turned and skewed (LAB-1210)

65 documents, OCR (Tesseract) + rules detector, no SAM. A labelled text / mrz region counts as covered when ≥ 90% of it is masked, scored after turning the cover back onto the upright document. Transforms are degrees counter-clockwise; latency is per image, OCR and detection, six images at a time on one machine.

| Transform | Regions | Covered before % | Covered after % | Lost vs upright before → after | ms p50 before → after | ms p95 before → after |
|---|---:|---:|---:|---:|---:|---:|
| 0° | 304 | 14.1 | 14.1 | 0 → 0 | 1389 → 2717 | 2134 → 5931 |
| 90° | 304 | 0.3 | 13.8 | 43 → 1 | 1730 → 6219 | 2692 → 13828 |
| 180° | 304 | 0.0 | 13.8 | 43 → 1 | 1760 → 3568 | 2690 → 5851 |
| 270° | 304 | 4.9 | 13.8 | 36 → 1 | 1979 → 4591 | 3502 → 8001 |
| 5° | 304 | 7.6 | 15.1 | 35 → 23 | 1392 → 4357 | 2660 → 10381 |
| -10° | 304 | 0.0 | 13.5 | 43 → 25 | 813 → 3863 | 1533 → 7366 |
| 15° | 304 | 0.0 | 9.9 | 43 → 28 | 700 → 3517 | 1344 → 6931 |
