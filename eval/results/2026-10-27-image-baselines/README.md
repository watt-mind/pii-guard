# pii-guard vs Presidio Image Redactor and Eka PII Redaction on images (2026-10-27)

The same images and the same scorer as pii-guard's visual eval
([docs/evaluation.md](../../../docs/evaluation.md#image-redaction-baselines)). Each tool returns
the boxes it would black out. A labelled region counts as a hit when one box overlaps it with
IoU ≥ 0.5. Coverage is the share of the region's pixels under any box. Over-masking is the
covered area outside every labelled region, as a share of the image. These files contain
image ids and numbers only, never images or recognised text.

| | |
|---|---|
| Code | commit `b9b2b435d923` (the harness, workers and pinned environments of LAB-1164) |
| Sets | `fictional-specimens`: 24 committed Muse Image documents (`eval/fixtures/visual/`; HU, DE and GB, 149 regions). `specimens`: 65 official specimen ID documents from 24 EU countries (406 regions), fetched by `eval/visual/fetch_specimens.py` into a gitignored directory and never committed. All 65 matched the committed SHA-256s. |
| Host | Apple M1 Max, macOS, 10 CPUs, CPU only, Tesseract 5.5.3 (`eng`, `hun`), one image at a time |
| pii-guard | SAM 3.1 (Meta Model API) for portraits and signatures, plus Tesseract `hun+eng` on images enlarged to 2000 px, the text detectors, field captions and MRZ layout. Two modes: `rules`, and `rules,llm` with Muse Spark Open on Baseten (`reasoning_effort=low`). |
| Presidio | presidio-image-redactor 0.0.62, presidio-analyzer 2.2.365, spaCy 3.8, `en_core_web_lg` / `de_core_news_lg` 3.8.0 and huSpaCy `hu_core_news_lg` 3.8.1. Each document is analysed in its own language: hu, de, or en for everything else. `ImageAnalyzerEngine` (the analysis that `ImageRedactorEngine.redact` fills) uses predefined recognizers at the default threshold. *Defaults*: Tesseract's default `eng`, the image as given. *Tuned*: `ocr_kwargs={"lang": "hun+eng"}` on images enlarged to 2000 px, i.e. pii-guard's OCR input. |
| Eka | eka-pii-redaction[visual] 0.7.0 (torch 2.14.1, transformers 5.21.0, ultralytics 8.4.190), weights `ekacare/document-pii-redactor@c088fc4823f6`: a LayoutLMv3 token classifier over Tesseract words, plus a YOLO11m detector for faces, signatures, stamps, QR codes and logos. `ImagePIIRedactor.detect` runs with all categories, visual threshold 0.25, on CPU. *Defaults* and *tuned* are set up as for Presidio. |
| LeakageBench | **Skipped.** The paper (arXiv 2609.02207, 2026-09-02) says the images and annotations "will be made available for research use" under a Data Use Agreement. No public download or open licence exists (checked on 2026-10-27, including Hugging Face and GitHub), so no data was fetched. |

Each tool's pinned environment is in `src/pii_guard/eval/baselines/envs/`
(`presidio-image.txt`, `eka.txt`), and its worker is in `.../workers/`.

## Results

Recall@IoU ≥ 0.5 in %. MRZ shows IoU / coverage ≥ 0.9. Text shows IoU / mean coverage. "All" is
every labelled region, including the types a tool can't mask. Latency is ms per image, p50 / p95.

### Fictional specimen-style documents (24 images)

| System | Portrait (18) | Signature (15) | MRZ (6) | Text values (110) | All (149) | Over-masking | Latency p50 / p95 |
|---|---:|---:|---:|---:|---:|---:|---:|
| pii-guard rules | 100.0 | 100.0 | 100.0 / 100.0 | 87.3 / 87.2 | 90.6 | 1.2 | 6,385 / 9,566 |
| **pii-guard rules + LLM** | **100.0** | **100.0** | **100.0 / 100.0** | **100.0 / 99.6** | **100.0** | 1.2 | 8,351 / 11,642 |
| Presidio (defaults) | n/a | n/a | 0.0 / 0.0 | 50.9 / 55.0 | 37.6 | 1.1 | 375 / 598 |
| Presidio (tuned) | n/a | n/a | 0.0 / 0.0 | 50.9 / 54.5 | 38.3 | 1.1 | 943 / 1,164 |
| Eka (defaults) | 100.0 | 86.7 | 0.0 / 0.0 | 91.8 / 89.7 | 88.6 | 3.2 | 672 / 881 |
| Eka (tuned) | 100.0 | 86.7 | 0.0 / 0.0 | 95.5 / 95.1 | 91.3 | 3.2 | 1,213 / 1,403 |

### Official specimen ID documents (65 images, 24 countries)

| System | Portrait (65) | Signature (37) | MRZ (30) | Text values (274) | All (406) | Over-masking | Latency p50 / p95 |
|---|---:|---:|---:|---:|---:|---:|---:|
| pii-guard rules | **90.8** | **83.8** | 76.7 / 60.0 | 15.0 / 21.3 | 37.9 | 4.0 | 8,022 / 12,604 |
| **pii-guard rules + LLM** | **90.8** | **83.8** | **80.0 / 60.0** | 30.3 / 39.1 | **48.5** | 4.7 | 9,504 / 12,309 |
| Presidio (defaults) | n/a | n/a | 0.0 / 0.0 | 19.7 / 24.1 | 13.3 | 3.4 | 280 / 574 |
| Presidio (tuned) | n/a | n/a | 0.0 / 0.0 | 17.5 / 25.4 | 12.3 | 3.9 | 1,171 / 1,923 |
| Eka (defaults) | 56.9 | 46.0 | 6.7 / 13.3 | **32.5** / 41.9 | 35.7 | 10.8 | 598 / 915 |
| Eka (tuned) | 55.4 | 48.6 | 10.0 / 16.7 | **32.5 / 47.5** | 36.0 | 12.0 | 1,616 / 2,295 |

## What the numbers say

- **pii-guard masks the most personal data on both sets**: 100.0 % and 48.5 % of all labelled
  regions with the LLM, compared with Eka's best 91.3 % and 36.0 % and Presidio's 38.3 % and
  13.3 %. Most of the lead comes from portraits, signatures and MRZ. On the official specimens,
  SAM 3.1 finds 90.8 % of portraits, while Eka's YOLO finds 55–57 %. pii-guard finds 83.8 % of
  signatures and Eka 46–49 %. Both tools also find 100 % of portraits on the cleaner fictional
  cards.
- **Eka beats pii-guard on specimen text.** Eka's layout-aware classifier hits 32.5 % of the
  274 specimen text values (47.5 % mean coverage, tuned), and pii-guard rules + LLM hits
  30.3 % (39.1 %). Eka pays for that with about 2.5× the over-masking: 12.0 % of the image,
  against 4.7 %. pii-guard's rules alone hit 15.0 %, below both. On the fictional set,
  pii-guard with the LLM leads (100.0 % against 95.5 %), and the rules alone trail Eka (87.3 %
  against 91.8–95.5 %).
- **Presidio Image Redactor is text-only by design.** It has no face, signature or MRZ
  detection, so those columns read n/a, and its overall score counts them as missed. On text
  values it hits 50.9 % (fictional) and 17.5–19.7 % (specimens). Giving it pii-guard's OCR
  input (`hun+eng`, enlarged images) doesn't help: 50.9 % again on the fictional set, and
  17.5 % against 19.7 % on the specimens.
- **MRZ**: pii-guard masks each zone as one box from its layout. Both baselines return word or
  line boxes, so they rarely reach IoU 0.5 against a two- or three-line zone. Coverage ≥ 0.9,
  which doesn't depend on box shape, tells the same story: 60 % for pii-guard and 0–17 % for
  the others.
- **Latency is not like for like.** pii-guard's time includes SAM 3.1 as a remote API, four
  sequential calls per image (p50 4.9–5.3 s), as recorded when each response was first
  fetched. Without SAM, pii-guard's local OCR + detection takes 1.4–1.9 s p50 for rules and
  3.7–4.2 s with the LLM. The baselines run entirely on the local CPU, at 0.3–1.6 s p50.

## Caveats

- Text tools return one box per OCR word. Before scoring, the words of one detected entity
  are merged per text line: Presidio's words by entity, and Eka's adjacent words of one
  category, which is Eka's own grouping rule. pii-guard applies the same rule to its own
  spans. Every box a tool returns is counted as masked, whatever its label.
- Eka's models are trained on Indian documents (names, IDs, medical forms), not EU ID cards.
  Presidio has no Hungarian recognizers beyond the language-independent ones. Both facts are
  part of what this comparison measures. Neither tool was configured beyond the documented
  options above.
- Region labels: one box per value, MRZ zone, portrait and signature. Stamps and overprints are
  unscored on the fictional set, so a tool that masks them (Eka does) pays in over-masking.
- The LLM detector is not deterministic. These pii-guard numbers reproduce LAB-1125's
  (milestone 22) within 1.1 points.
- Licences: Presidio is MIT. The Eka library is Apache-2.0, `ultralytics` and the YOLO weights
  are AGPL-3.0, and the LayoutLMv3 fine-tune is CC-BY-NC-SA-4.0 (non-commercial). The weights
  were downloaded at run time for this evaluation only and are not redistributed here.

## Cost

- SAM 3.1: 96 + 260 live calls, an estimated **$0.89** at $0.0025 per call. The response cache
  was empty on this machine, so the `rules` runs fetched once and the `rules + LLM` runs used
  the cache.
- Baseten: 89 LLM detector requests, one OCR text per image. The harness doesn't meter tokens.
  At the $3.6–4.9 per 1,000 documents measured in milestone 15, that is about **$0.3–0.5**.
- Presidio and Eka: local CPU only. No Modal app was started.

## Reproduce

```bash
uv sync --extra ocr
uv run python eval/visual/fetch_specimens.py --manifest /tmp/manifest.json   # images -> data/specimens
F=eval/fixtures/visual
for b in presidio-image presidio-image-tuned eka eka-tuned; do      # first run downloads the envs and models
  uv run pii-guard eval visual --specimens $F/images --manifest $F/manifest.json --labels $F/labels.json \
      --baseline $b --json fictional-$b.json --markdown fictional-$b.md
  uv run pii-guard eval visual --specimens data/specimens --baseline $b \
      --json specimens-$b.json --markdown specimens-$b.md
done
# pii-guard: the same commands with --detectors rules or --detectors rules,llm instead of --baseline
# (PII_GUARD_LLM_DETECTOR_API_KEY=$BASETEN_API_KEY, PII_GUARD_LLM_DETECTOR_REASONING_EFFORT=low)
```

Files: `<set>-<system>.{json,md}` are the full reports (per region type, country, document
type and image id). The run records are `eval/results/runs/2026-10-27-image-baselines-*.json`,
and they appear in [benchmarks.md](../../../docs/benchmarks.md).
