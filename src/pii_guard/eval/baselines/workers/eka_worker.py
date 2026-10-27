"""Eka PII Redaction baseline worker: ``ImagePIIRedactor`` (text + visual) on CPU.

Runs in the environment pinned by ``../envs/eka.txt`` (``eka-pii-redaction[visual]``). The
weights come from the Hugging Face repo ``ekacare/document-pii-redactor`` at a pinned
revision: a LayoutLMv3 token classifier over Tesseract words (text PII, 47 categories) and a
YOLO11m detector for visual entities (face photos, signatures, stamps, QR codes, logos,
fingerprints). ``detect`` runs both with the library defaults (all categories, visual score
threshold 0.25); every returned box is something ``redact`` would black out. Text entities
come back one box per OCR word; the client merges a category's adjacent words per line, as
Eka's own ``group_text_entities`` does.

Licences: library Apache-2.0; ``ultralytics`` and the YOLO weights AGPL-3.0; the LayoutLMv3
fine-tune CC-BY-NC-SA-4.0 (non-commercial). The weights are downloaded at run time for this
evaluation and never redistributed.

Optional settings, recorded in ``info``: ``--ocr-lang hun+eng`` (Tesseract languages, the
library's ``ocr_lang``; default Tesseract's ``eng``) and ``--upscale-to 2000`` (enlarge the
image before detection and scale the boxes back, as pii-guard's OCR does).
"""

from __future__ import annotations

import argparse
from importlib.metadata import version
from typing import Any

# The script's own directory is on sys.path, so the sibling protocol module imports.
from _image_protocol import clamp_box, protocol_stdout, quiet_logging, serve

HF_REPO = "ekacare/document-pii-redactor"
HF_REVISION = "c088fc4823f608947af224524bbb8909bed3ae7e"
#: Eka's visual categories mapped to the region kinds the eval labels.
VISUAL_KINDS = {"face_photo": "face", "signature": "signature"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ocr-lang", default=None)
    parser.add_argument("--upscale-to", type=int, default=0)
    args = parser.parse_args(argv)
    out = protocol_stdout()
    quiet_logging()

    from eka_pii_redaction import ImagePIIRedactor
    from huggingface_hub import snapshot_download
    from PIL import Image

    local = snapshot_download(
        HF_REPO, revision=HF_REVISION, allow_patterns=["image/*", "image/**/*", "config.json"]
    )
    redactor = ImagePIIRedactor(local, detect_visual=True, device="cpu", ocr_lang=args.ocr_lang)

    def handle(image: Any, language: str) -> list[dict[str, Any]]:
        scale = 1.0
        work = image
        if args.upscale_to and max(image.size) < args.upscale_to:
            scale = args.upscale_to / max(image.size)
            size = (round(image.width * scale), round(image.height * scale))
            work = image.resize(size, Image.Resampling.LANCZOS)
        regions = []
        for e in redactor.detect(work):
            x0, y0, x1, y1 = (v / scale for v in e.bbox)
            box = clamp_box((x0, y0, x1 - 1, y1 - 1), image.width, image.height)
            if box is None:
                continue
            regions.append(
                {
                    "box": box,
                    "label": e.category,
                    "kind": e.kind,
                    "group": e.category if e.kind == "text" else None,
                    "score": None if e.score is None else float(e.score),
                }
            )
        return regions

    info = {
        "tool": "eka-pii-redaction",
        "versions": {
            name: version(name)
            for name in ("eka-pii-redaction", "torch", "transformers", "ultralytics")
        },
        "models": [
            f"{HF_REPO}@{HF_REVISION[:12]} image/layoutlmv3 (text PII)",
            f"{HF_REPO}@{HF_REVISION[:12]} image/yolo/best.pt (visual entities)",
        ],
        "config": {
            "detector": "ImagePIIRedactor.detect, all categories, detect_visual=True",
            "visual_score_threshold": redactor.visual_score_threshold,
            "device": "cpu",
            "ocr_lang": args.ocr_lang or "tesseract default (eng)",
            "upscale_to": args.upscale_to or None,
        },
        "supports": ["text", "face", "signature"],
    }
    return serve(out, info, handle)


if __name__ == "__main__":
    raise SystemExit(main())
