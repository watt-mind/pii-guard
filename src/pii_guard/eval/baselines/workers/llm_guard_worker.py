"""LLM Guard baseline worker: the ``Anonymize`` input scanner with its default settings.

Runs in the environment pinned by ``../envs/llm-guard.txt``. Each document gets a fresh
``Vault``, as one request would; the masked text is exactly what ``Anonymize.scan`` returns
and ``restored`` is what ``Deanonymize.scan`` makes of it. The spans are the entities
``scan`` passed to its own replacement step (captured, not recomputed).
"""

from __future__ import annotations

import sys
import time
from importlib.metadata import version
from typing import Any

# The script's own directory is on sys.path, so the sibling protocol module imports.
from _protocol import ms_since, protocol_stdout, quiet_logging, serve


def main() -> int:
    out = protocol_stdout()
    quiet_logging()

    from llm_guard.input_scanners import Anonymize
    from llm_guard.input_scanners.anonymize_helpers import DEBERTA_AI4PRIVACY_v2_CONF
    from llm_guard.output_scanners import Deanonymize
    from llm_guard.util import configure_logger
    from llm_guard.vault import Vault

    configure_logger("ERROR", stream=sys.stderr)  # its warnings carry the detected values

    vault = Vault()
    scanner = Anonymize(vault)  # defaults: DeBERTa ai4privacy v2, threshold 0.5, language "en"

    captured: dict[str, Any] = {}
    replace = Anonymize._anonymize

    def capturing(prompt: str, pii_entities: list[Any], vault: Any, use_faker: bool) -> Any:
        captured["entities"] = [(e.start, e.end, e.entity_type, e.score) for e in pii_entities]
        started = time.perf_counter()
        result = replace(prompt, pii_entities, vault, use_faker)
        captured["mask_ms"] = ms_since(started)
        return result

    Anonymize._anonymize = staticmethod(capturing)  # type: ignore[method-assign]

    def handle(text: str, language: str) -> tuple[list[list[Any]], str, str | None, float, float]:
        doc_vault = Vault()
        scanner._vault = doc_vault
        captured.clear()
        started = time.perf_counter()
        masked, _valid, _score = scanner.scan(text)
        total_ms = ms_since(started)
        entities = captured.get("entities", [])
        mask_ms = captured.get("mask_ms", 0.0)
        restored, _ok, _ = Deanonymize(doc_vault).scan("", masked)
        spans = [[s, e, label, float(score)] for s, e, label, score in entities if e > s]
        return spans, masked, restored, total_ms - mask_ms, mask_ms

    model = DEBERTA_AI4PRIVACY_v2_CONF["DEFAULT_MODEL"]
    info = {
        "tool": "llm-guard",
        "versions": {
            name: version(name)
            for name in ("llm-guard", "presidio-analyzer", "transformers", "torch", "spacy")
        },
        "models": [
            f"{model.path}@{model.revision}",
            f"en_core_web_sm {version('en-core-web-sm')}",
            f"zh_core_web_sm {version('zh-core-web-sm')}",
        ],
        "config": {
            "scanner": "Anonymize(vault) with defaults",
            "language": scanner._language,
            "threshold": scanner._threshold,
            "entity_types": list(scanner._entity_types),
            "use_onnx": False,
        },
    }
    return serve(out, info, handle)


if __name__ == "__main__":
    raise SystemExit(main())
