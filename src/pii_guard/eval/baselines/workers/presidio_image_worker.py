"""Presidio Image Redactor baseline worker: ``ImageAnalyzerEngine`` with Tesseract.

Runs in the environment pinned by ``../envs/presidio-image.txt``. This is the analysis half of
``ImageRedactorEngine.redact`` (which fills exactly the boxes ``ImageAnalyzerEngine.analyze``
returns): Tesseract OCR via ``TesseractOCR``, the text through a Presidio ``AnalyzerEngine``
with its predefined recognizers and default score threshold, and one box per OCR word of
each detected entity. Presidio's image redactor is text-only by design: it never masks
faces or signatures.

The one choice we make is the spaCy model per language, because Presidio ships only English
by default: ``en_core_web_lg`` (its default), ``de_core_news_lg`` and huSpaCy's
``hu_core_news_lg`` (as in the text baseline, LAB-1098). Each document is analysed in its own
language when there is a model for it, else in English. Two optional settings, both off by
default and recorded in ``info``:

- ``--ocr-lang hun+eng``: Tesseract's language list, passed through ``ocr_kwargs``
  (Presidio's documented hook); default: Tesseract's own default, ``eng``;
- ``--upscale-to 2000``: enlarge the image so its longer side is this many pixels before
  OCR (what pii-guard's OCR does) and scale the boxes back.
"""

from __future__ import annotations

import argparse
from importlib.metadata import version
from typing import Any

# The script's own directory is on sys.path, so the sibling protocol module imports.
from _image_protocol import clamp_box, protocol_stdout, quiet_logging, serve

SPACY_MODELS = {"en": "en_core_web_lg", "de": "de_core_news_lg", "hu": "hu_core_news_lg"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ocr-lang", default=None)
    parser.add_argument("--upscale-to", type=int, default=0)
    args = parser.parse_args(argv)
    out = protocol_stdout()
    quiet_logging()

    from PIL import Image
    from presidio_analyzer import AnalyzerEngine, RecognizerRegistry
    from presidio_analyzer.nlp_engine import NlpEngineProvider
    from presidio_image_redactor import ImageAnalyzerEngine, TesseractOCR

    try:  # the e-mail recognizer would fetch the public suffix list on first use
        from tldextract import tldextract

        tldextract.TLD_EXTRACTOR.suffix_list_urls = ()
    except ImportError:  # pragma: no cover
        pass

    languages = sorted(SPACY_MODELS)
    nlp_engine = NlpEngineProvider(
        nlp_configuration={
            "nlp_engine_name": "spacy",
            "models": [{"lang_code": lang, "model_name": SPACY_MODELS[lang]} for lang in languages],
        }
    ).create_engine()
    registry = RecognizerRegistry(supported_languages=languages)
    registry.load_predefined_recognizers(languages=languages, nlp_engine=nlp_engine)
    analyzer = AnalyzerEngine(
        nlp_engine=nlp_engine, registry=registry, supported_languages=languages
    )
    engine = ImageAnalyzerEngine(analyzer_engine=analyzer, ocr=TesseractOCR())
    ocr_kwargs = {"lang": args.ocr_lang} if args.ocr_lang else None

    def handle(image: Any, language: str) -> list[dict[str, Any]]:
        lang = language.split("-", 1)[0]
        lang = lang if lang in SPACY_MODELS else "en"
        scale = 1.0
        if args.upscale_to and max(image.size) < args.upscale_to:
            scale = args.upscale_to / max(image.size)
            size = (round(image.width * scale), round(image.height * scale))
            work = image.resize(size, Image.Resampling.LANCZOS)
        else:
            work = image
        results = engine.analyze(work, ocr_kwargs=ocr_kwargs, language=lang)
        regions = []
        for r in results:
            box = clamp_box(
                (
                    r.left / scale,
                    r.top / scale,
                    (r.left + r.width) / scale - 1,
                    (r.top + r.height) / scale - 1,
                ),
                image.width,
                image.height,
            )
            if box is None:
                continue
            regions.append(
                {
                    "box": box,
                    "label": r.entity_type,
                    "kind": "text",
                    "group": f"{r.start}:{r.end}:{r.entity_type}",
                    "score": round(float(r.score), 4),
                }
            )
        return regions

    info = {
        "tool": "presidio-image-redactor",
        "versions": {
            name: version(name)
            for name in ("presidio-image-redactor", "presidio-analyzer", "spacy", "pytesseract")
        },
        "models": [
            f"en_core_web_lg {version('en-core-web-lg')} (en)",
            f"de_core_news_lg {version('de-core-news-lg')} (de)",
            f"hu_core_news_lg {version('hu-core-news-lg')} (hu, huSpaCy)",
        ],
        "config": {
            "engine": "ImageAnalyzerEngine(AnalyzerEngine, TesseractOCR), the analysis "
            "ImageRedactorEngine.redact fills",
            "analyzer": "predefined recognizers, default score threshold",
            "languages": languages,
            "ocr_lang": args.ocr_lang or "tesseract default (eng)",
            "upscale_to": args.upscale_to or None,
        },
        "supports": ["text"],
    }
    return serve(out, info, handle)


if __name__ == "__main__":
    raise SystemExit(main())
