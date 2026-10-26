"""PrivAiTe baseline worker: the proxy's PII engine in-process, with its shipped config.

Runs in the environment pinned by ``../envs/privaite.txt``. The configuration is the
``pii`` section of PrivAiTe's shipped ``config/privaite.openai.yaml`` (v0.7.3): the
default ``onnx`` preset (Presidio with French and English spaCy models plus the ONNX
``openai/privacy-filter`` model), placeholder anonymization, cards masked and secrets
redacted. Each document is sent as one user message through ``PIIEngine.process_request``,
the same call the proxy makes; the spans are the entities that call handed to its
anonymizer (captured, not recomputed) and ``restored`` is ``process_response`` on the
masked text.
"""

from __future__ import annotations

import asyncio
import time
from importlib.metadata import version
from typing import Any

# The script's own directory is on sys.path, so the sibling protocol module imports.
from _protocol import ms_since, protocol_stdout, quiet_logging, serve

#: The ``pii`` section of PrivAiTe v0.7.3 ``config/privaite.openai.yaml``, comments dropped.
SHIPPED_PII_CONFIG: dict[str, Any] = {
    "enabled": True,
    "preset": "onnx",
    "detectors": {
        "presidio": {"enabled": True, "languages": ["fr", "en"], "score_threshold": 0.4},
        "bert_ner": {"enabled": False},
        "mlmodel": {"enabled": False},
        "gliner": {"enabled": False},
    },
    "merge_strategy": "union",
    "overlap_resolution": "highest_score",
    "on_error": "block",
    "block_entities": [],
    "anonymization": {
        "method": "placeholder",
        "faker_locale": ["fr_FR", "en_US"],
        "entity_overrides": {
            "CREDIT_CARD": {"method": "mask", "masking_char": "*"},
            "SECRET": {"method": "redact"},
        },
    },
    "deanonymization": {"enabled": True, "fuzzy_matching": False, "fuzzy_threshold": 0.85},
    "inspect": {"enabled": False},
    "passthrough": {"system_messages": False, "tool_calls": False},
}


def main() -> int:
    out = protocol_stdout()
    quiet_logging()

    from privaite.config.schema import PIIConfig
    from privaite.pii.engine import PIIEngine

    config = PIIConfig.model_validate(SHIPPED_PII_CONFIG)
    engine = PIIEngine(config)
    loop = asyncio.new_event_loop()
    loop.run_until_complete(engine.initialize())

    captured: dict[str, Any] = {}
    anonymize = engine.anonymizer.anonymize

    def capturing(text: str, entities: list[Any], mapping: Any) -> str:
        captured["entities"] = [(e.start, e.end, e.entity_type, e.score) for e in entities]
        started = time.perf_counter()
        result = anonymize(text, entities, mapping)
        captured["mask_ms"] = ms_since(started)
        return result

    engine.anonymizer.anonymize = capturing  # type: ignore[method-assign]

    def handle(text: str, language: str) -> tuple[list[list[Any]], str, str | None, float, float]:
        captured.clear()
        started = time.perf_counter()
        messages, mapping = loop.run_until_complete(
            engine.process_request([{"role": "user", "content": text}])
        )
        total_ms = ms_since(started)
        masked = messages[0]["content"]
        restored = loop.run_until_complete(engine.process_response(masked, mapping))
        mask_ms = captured.get("mask_ms", 0.0)
        spans = [[s, e, label, float(score)] for s, e, label, score in captured.get("entities", [])]
        return spans, masked, restored, total_ms - mask_ms, mask_ms

    onnx = config.detectors.onnx
    info = {
        "tool": "privaite",
        "versions": {
            name: version(name)
            for name in ("privaite", "presidio-analyzer", "onnxruntime", "transformers", "spacy")
        },
        "models": [
            f"{onnx.model_name}@{onnx.revision} ({onnx.onnx_variant})",
            f"en_core_web_lg {version('en-core-web-lg')}",
            f"fr_core_news_md {version('fr-core-news-md')}",
        ],
        "config": {
            "source": "pii section of config/privaite.openai.yaml (v0.7.3)",
            "preset": config.preset,
            "presidio_languages": list(config.detectors.presidio.languages),
            "presidio_entities": list(config.detectors.presidio.entities or []),
            "presidio_score_threshold": config.detectors.presidio.score_threshold,
            "onnx_score_threshold": onnx.score_threshold,
        },
    }
    return serve(out, info, handle)


if __name__ == "__main__":
    raise SystemExit(main())
