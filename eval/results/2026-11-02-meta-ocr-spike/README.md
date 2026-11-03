# Spike: Meta-only OCR (LAB-1794)

Question: can Meta models replace Tesseract as the OCR step of the image path? Hackathon rule
(2026-11-02): only Meta models may run at runtime. All images are the 24 fictional specimens in
`eval/fixtures/visual/`. Every output here is a reply on fictional data.

## Result

**Muse Spark Open (Baseten Model APIs, `meta-models/muse-spark-open-1026`) works as a line-level
OCR engine. SAM 3.1 cannot place text, and Muse Spark 1.3 is too slow.**

| Engine | Text regions covered (cov ≥ 0.9, ideal detector) | Notes |
|---|---|---|
| Tesseract word boxes, pad 4 px (baseline) | 96/110 (87%) | from `ocr/tesseract.json` |
| Muse Spark Open line boxes, pad 2% | 96/110 (87%) | text matches Tesseract's in 62/69 regions Tesseract can read |
| Muse Spark Open line boxes, pad 3% | 101/110 (92%) | |
| Muse Spark Open word boxes, pad 2% | 88/110 (80%) | 2/24 refused; worse than lines |
| Muse Spark Open, span boxes interpolated inside a line | 42/69 (61%) | proportional fonts: don't split lines by character |
| SAM 3.1, prompts `text`, `word`, `line of text`, `printed text`, `name`, `date`, `number` | 0/11 on two specimens | returns no text boxes |
| Muse Spark 1.3 (Meta Model API) | n/a | 17-21 s per image, spent its 3,000-token budget on reasoning, empty reply on the ID card |

"Ideal detector" means the text detector is assumed to find the value; this measures only
whether the OCR boxes can cover it. `python3 scoreall.py` reproduces `scores.txt`.

- **Latency:** 5.4-10.2 s per image (median about 7.5 s), 6 in parallel, `reasoning_effort=low`.
- **Refusals:** 1/24 with the layout prompt (`de-member_card-front`). A prompt that names personal
  data or redaction refuses far more often: 2 of 3 in a first probe (the letter page and the ID card).
- **Prompt:** see `probe.py`. The system prompt frames the task as document layout. The user
  prompt asks for `{"lines":[{"text","box"}]}` with boxes normalized to 0-1000.

## Recommendation for the OCR engine (LAB-1796)

1. Add a `MuseOcr` engine. Each returned line is one OCR unit (one "word" box in `ocr.py`'s
   terms), so a detected span masks its whole line. Grow each line box by 2% of the image width
   on every side (the y padding uses the same pixel amount).
2. On a reply with no JSON, retry once. If it fails again, fail closed (ADR 0006): the image is
   blocked, never sent unmasked.
3. Make it the default. `PII_GUARD_OCR_ENGINE=tesseract` keeps Tesseract available.
4. **Data boundary.** The unmasked image goes to Baseten, the same way `sam-api` already sends
   images to the Meta Model API. A local-only detection profile must refuse it (`refuse_remote`),
   or point it at a self-hosted Muse Spark Open, which has open weights. The docs must say this plainly.
5. Masks are coarser on letter pages, where a whole line is covered. ID cards are unaffected,
   because each value sits on its own line.
