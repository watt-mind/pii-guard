"""The tool vocabulary a request declares, and the detections it rules out.

Shared by ``/v1/chat/completions`` (:class:`~pii_guard.gateway.service.Gateway`) and
``/v1/responses`` (:class:`~pii_guard.gateway.responses.ResponsesGateway`): after detection and
before masking, both drop the detections whose whole value is a declared tool name.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from pii_guard.detect.known import KNOWN_DETECTOR
from pii_guard.types import Span
from pii_guard.vault.placeholders import normalize_value

__all__ = ["tool_names", "without_tool_names"]

#: What a tool or namespace name looks like (OpenAI: ``^[a-zA-Z0-9_-]{1,64}$``; namespaced
#: calls add ``.``). A "name" with whitespace is not a real identifier and gets no exemption: a
#: tool named ``Teszt Elek`` is still refused as personal data in an identifier.
_IDENTIFIER_RE = re.compile(r"[\w.:-]+")


def tool_names(body: Mapping[str, Any]) -> frozenset[str]:
    """The names of the tools and tool namespaces the request declares (normalized).

    Responses API: ``tools[].name`` and a namespace's ``tools[].tools[].name``. Chat
    Completions: ``tools[].function.name`` (and ``tools[].custom.name``), the flat
    ``tools[].name``, and the legacy ``functions[].name``. Only identifier-shaped names
    (no whitespace) count.
    """
    names: set[str] = set()

    def add(definition: object) -> None:
        name = definition.get("name") if isinstance(definition, dict) else None
        if isinstance(name, str) and _IDENTIFIER_RE.fullmatch(name):
            names.add(normalize_value(name))

    def walk(tools: object) -> None:
        for tool in tools if isinstance(tools, list) else []:
            if isinstance(tool, dict):
                add(tool)
                add(tool.get("function"))
                add(tool.get("custom"))
                walk(tool.get("tools"))

    walk(body.get("tools"))
    functions = body.get("functions")
    for function in functions if isinstance(functions, list) else []:
        add(function)
    return frozenset(names)


def without_tool_names(
    texts: list[str], spans: list[list[Span]], names: frozenset[str]
) -> list[list[Span]]:
    """``spans`` without the detections whose whole value is one of the declared tool ``names``.

    A client's tool vocabulary is not personal data, and it goes upstream as written anyway:
    tool and namespace names are identifiers, sent unmasked or the request is refused. Masking
    the same word elsewhere does harm only. Muse Code 1.4.14 says "Muse" alone in its reminder
    prompts; the NER read it as a PERSON, and the vault then masked the ``muse`` namespace (an
    identifier) as another occurrence of that value, so the request was refused (LAB-1299).
    Chat Completions had the same gap for ``tools[].function.name`` (LAB-1317). Values the
    operator pre-loaded (``known``) are kept.
    """
    if not names:
        return spans
    return [
        [
            s
            for s in found
            if s.detector == KNOWN_DETECTOR or normalize_value(text[s.start : s.end]) not in names
        ]
        for text, found in zip(texts, spans, strict=True)
    ]
