"""Microsoft Presidio baseline, in-process (``uv sync --extra baselines``).

Default configuration: ``AnalyzerEngine`` with Presidio's predefined recognizers and its
default score threshold (0), ``AnonymizerEngine`` with its default operator (replace each
entity with ``<ENTITY_TYPE>``). The only choice we make is the spaCy model per language,
because Presidio ships none for Hungarian:

- ``en``: ``en_core_web_lg`` (Presidio's own default model).
- ``hu``: ``hu_core_news_lg`` (huSpaCy), the strongest spaCy pipeline for Hungarian.
- ``de``: ``de_core_news_lg``, the standard German spaCy pipeline. The
  predefined recognizers that Presidio registers for a non-English language are the
  language-independent ones (email, IBAN, phone, IP, URL, date, crypto, ...); the
  US-specific ones are English only. It is not a package dependency: ``pii-guard baselines
  download`` fetches the pinned wheel once (:mod:`pii_guard.eval.baselines.models`, LAB-1249).

Any other language falls back to the English pipeline.
"""

from __future__ import annotations

import re
import time
from importlib import metadata
from typing import Any

from pii_guard.eval.baselines.base import BaselineOutput, BaselineUnavailable
from pii_guard.eval.baselines.mapping import to_spans
from pii_guard.eval.baselines.models import HU_CORE_NEWS_LG, import_model

__all__ = ["SPACY_MODELS", "PresidioBaseline"]

SPACY_MODELS = {"en": "en_core_web_lg", "de": "de_core_news_lg", "hu": "hu_core_news_lg"}
_EXTRA_HINT = "install the extra: uv sync --extra baselines"


def _version(dist: str) -> str | None:
    try:
        return metadata.version(dist)
    except metadata.PackageNotFoundError:
        return None


class PresidioBaseline:
    name = "presidio"
    reversible = False  # the default "replace" operator keeps no mapping
    placeholder_re = re.compile(r"<[A-Z][A-Z0-9_]*>")

    def __init__(self) -> None:
        try:
            import spacy
            from presidio_analyzer import AnalyzerEngine, RecognizerRegistry
            from presidio_analyzer.nlp_engine import NlpEngineProvider
            from presidio_anonymizer import AnonymizerEngine
        except ImportError:
            raise BaselineUnavailable(f"presidio is not installed ({_EXTRA_HINT})") from None
        if not spacy.util.is_package(SPACY_MODELS["en"]):
            raise BaselineUnavailable(
                f"spaCy model {SPACY_MODELS['en']} not installed ({_EXTRA_HINT})"
            )
        # huSpaCy loads from its unpacked, pinned wheel, by path (LAB-1249).
        model_paths = {
            "en": SPACY_MODELS["en"],
            "de": SPACY_MODELS["de"],
            "hu": str(import_model(HU_CORE_NEWS_LG)),
        }
        _no_suffix_list_download()

        languages = sorted(SPACY_MODELS)
        nlp_engine = NlpEngineProvider(
            nlp_configuration={
                "nlp_engine_name": "spacy",
                "models": [
                    {"lang_code": lang, "model_name": model_paths[lang]} for lang in languages
                ],
            }
        ).create_engine()
        registry = RecognizerRegistry(supported_languages=languages)
        registry.load_predefined_recognizers(languages=languages, nlp_engine=nlp_engine)
        self._analyzer = AnalyzerEngine(
            nlp_engine=nlp_engine, registry=registry, supported_languages=languages
        )
        self._anonymizer = AnonymizerEngine()
        self.info: dict[str, Any] = {
            "tool": "presidio",
            "versions": {
                name: _version(name)
                for name in ("presidio-analyzer", "presidio-anonymizer", "spacy")
            },
            "models": [
                f"{SPACY_MODELS['en']} {_version('en-core-web-lg')} (en)",
                f"{SPACY_MODELS['de']} {_version('de-core-news-lg')} (de)",
                f"{SPACY_MODELS['hu']} {HU_CORE_NEWS_LG.version} (hu, huSpaCy)",
            ],
            "config": {
                "analyzer": "AnalyzerEngine, predefined recognizers, default score threshold",
                "anonymizer": "AnonymizerEngine, default operator (replace with <ENTITY_TYPE>)",
                "recognizers": {
                    lang: sorted(r.name for r in registry.get_recognizers(lang, all_fields=True))
                    for lang in languages
                },
            },
        }
        self.process("warm up: Jane Doe, jane.doe@example.com", "en")

    def _language(self, language: str) -> str:
        primary = language.split("-", 1)[0]
        return primary if primary in SPACY_MODELS else "en"

    def process(self, text: str, language: str) -> BaselineOutput:
        started = time.perf_counter()
        results = self._analyzer.analyze(text=text, language=self._language(language))
        detected = time.perf_counter()
        masked = self._anonymizer.anonymize(text=text, analyzer_results=results).text
        done = time.perf_counter()
        raw = [(r.start, r.end, r.entity_type, r.score) for r in results]
        spans, unmapped = to_spans(text, raw, self.name)
        return BaselineOutput(
            spans=tuple(spans),
            masked_text=masked,
            restored_text=None,
            detect_ms=(detected - started) * 1000,
            mask_ms=(done - detected) * 1000,
            unmapped=unmapped,
        )

    def close(self) -> None:
        return None


def _no_suffix_list_download() -> None:
    """Presidio's email recognizer would fetch the public suffix list on first use."""
    try:
        from tldextract import tldextract
    except ImportError:  # pragma: no cover - presidio depends on it
        return
    tldextract.TLD_EXTRACTOR.suffix_list_urls = ()
