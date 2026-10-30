# OCR reads through security print on ID cards (2026-10-30)

LAB-1183. On the 65 official specimen ID documents, Tesseract returned no word for many text
values. The cards are security printed: pastel guilloche, rainbow print and holograms behind
2-4 px strokes, on scans 460-1000 px wide. **Before:** rules + captions masked 15.0 % of the
274 text values at IoU >= 0.5. MRZ recall was 76.7 %, all regions 37.9 %, and over-masking
4.0 % ([before](../../eval/results/visual/specimens-captions.md)). **After:** text 20.8 %,
MRZ 83.3 %, all regions 42.4 %, over-masking 4.7 %
([after](../../eval/results/visual/specimens-security-print.md), run record
`2026-10-30-visual-specimens-rules-captions-security-print`). The ticket's 50 % text target
is not met. The rest of the gap is classification, not reading (below and LAB-1609).

- **Fix.** `TesseractOcr` takes one more pass on a page it read poorly (under 70 % of
  characters read confidently) when at least 5 % of its pixels are tinted. The pass reads the
  page as greyscale made from each pixel's brightest channel (`suppress_background`), which
  turns a pastel tint near white and keeps dark ink dark. It also reads the page as sparse
  text (`--psm 11`), because the values on a card are scattered blocks, not paragraphs. The
  reading with more confidently read characters wins. Saturated colored ink (pure red) also
  turns white in that pass, but then that pass reads worse and is dropped, so the first
  reading stays. Clean pages, screenshots and grey scans never take the extra pass.
- **What the experiments showed** (local OCR-only diagnostics, the same scorer). With the
  brightest-channel image and psm 11 on every page, the values with no OCR word at their
  centre fell from 109 to 26 of 274, and text recall rose to 22.3 %. Each change alone gave
  less: brightest channel 19.0 %, psm 11 17.9 %. Read values stay unmasked because nothing
  flags them: 137 values are read well enough to cover (their words' box has IoU >= 0.5 with
  the label), yet no rule or caption region matches them. Masking every OCR word segment would reach
  only 52.6 % at about +12 points of over-masking. So 50 % at +3 points needs a classifier for
  names and addresses printed without a readable caption. That work is LAB-1609.
- **What didn't move.** The fictional set keeps 87.3 % text recall, and its OCR-only
  over-masking is unchanged (0.49 % of the image, the same local diagnostic). Portrait and
  signature recall on the specimens are unchanged (SAM). The OCR tests pass, including the
  real-Tesseract robustness screenshots. Two orientation tests that count Tesseract calls
  now turn the new pass off.
- **Cost.** $0. Tesseract runs locally and SAM came from the existing response cache. OCR
  and detection took p50 3.3 s per specimen image, against 2.1 s before. That run was
  single-threaded on a heavily loaded machine, so the latency difference is an upper bound.
  Only poorly read, tinted pages pay for the extra pass.
