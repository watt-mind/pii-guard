# 0016. Meta-only OCR: Muse Spark Open reads the text in images, Tesseract is opt-in

- **Status:** accepted
- **Date:** 2026-11-02
- **Builds on:** [ADR 0015](0015-meta-only-runtime-defaults.md) (its "OCR is not part of this
  decision"), [ADR 0006](0006-fail-closed.md)
- **Ticket:** LAB-1796 (spike: LAB-1794,
  [`eval/results/2026-11-02-meta-ocr-spike/`](../../eval/results/2026-11-02-meta-ocr-spike/README.md))

## Context

The Meta hackathon allows only Meta models at runtime, "including a local OCR model". The image
path read text with Tesseract, which is not a Meta model. The spike found that Muse Spark Open
on Baseten returns usable line boxes: padded by 2 % of the image width they cover 87 % of the
labelled text regions of the fictional specimens, as Tesseract's word boxes do. SAM 3.1 returns
no text boxes, and Muse Spark 1.3 takes 17-21 s per image.

## Decision

- **Default engine.** `PII_GUARD_OCR_ENGINE` defaults to `muse`:
  `pii_guard.visual.ocr_muse.MuseOcr` calls Muse Spark Open (`meta-models/muse-spark-open-1026`
  on Baseten Model APIs, `reasoning_effort: "low"`) with the spike's layout prompt. Each
  returned line is one OCR unit. Text regions found on a line grow by 2 % of the image width;
  the lines keep the model's box so captions and MRZ zones are found on its layout.
  `tesseract` stays available and unchanged.
- **Key.** `PII_GUARD_OCR_API_KEY`, else `BASETEN_API_KEY`. Without one there is no OCR engine:
  images are refused (`503 ocr_unavailable`) unless `PII_GUARD_IMAGE_REQUIRE_OCR=false`.
  `/v1/status` lists `ocr_key` in `images.gaps`, as it lists `sam` for the SAM key, and
  `/healthz` reports `ocr_engine` with `ocr: off`. A missing key is a configuration gap, not an
  unhealthy container. Hosted readiness fails without it while hosted images are on.
- **Fail closed (ADR 0006).** A reply without valid JSON is retried once with the same prompt;
  a second one, a timeout, an HTTP error or the image deadline raises `DetectionError`, and the
  image is refused. Nothing falls back to Tesseract.
- **Local-only profile.** `refuse_remote` applies: the `local-only` detection profile refuses
  Muse OCR unless `PII_GUARD_OCR_URL` is self-hosted (localhost, a loopback, private or
  link-local address, a single-label service name, or a `.local`/`.internal`/`.lan`/
  `.home.arpa`/`.svc` name). Such an endpoint may go keyless. Tesseract stays allowed.
- **Docker.** Neither `Dockerfile` nor `Dockerfile.hosted` installs Tesseract by default.
  `--build-arg PII_GUARD_TESSERACT=true` installs it with its language packs. The hosted image
  sets `PII_GUARD_OCR_ENGINE=muse`.

## Consequences

- **Data boundary.** With the defaults, every image's original pixels go to Baseten as well as
  to the Meta Model API (SAM 3.1): the unmasked screenshot or scan, every name and number on it
  readable. Operators who can't accept that point `PII_GUARD_OCR_URL` at their own Muse Spark
  Open (open weights) or opt back in to Tesseract.
- **Quality.** On the 24 fictional specimens, with SAM stubbed so only OCR differs, Muse covers
  84.5 % of the text regions fully (cov ≥ 0.9) against Tesseract's 85.5 %, and finds 5 of 6
  MRZ zones against 6 ([docs/models.md](../models.md#ocr-muse-spark-open)). Masks are coarser:
  a whole line is covered, so over-masking rises from 0.5 % to 6.7 % of the image.
- **Latency and cost.** About 8 s per image (p50; p95 17 s) on Baseten against about 1 s for
  Tesseract, on top of SAM's requests. One Baseten call per image (two after a refusal).
- **Refusals.** The model sometimes declines (1 of 24 in the spike). That image is refused,
  not sent unchecked. Prompts that mention personal data or redaction are refused far more
  often, so the prompt describes layout only.
- **Hosted release.** The hosted release must provide `PII_GUARD_OCR_API_KEY` (a Baseten key
  in Key Vault) before it ships an image built from this change, or set
  `PII_GUARD_OCR_ENGINE=tesseract` on an image built with `PII_GUARD_TESSERACT=true`.
