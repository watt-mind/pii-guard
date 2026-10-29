"""The tool vocabulary a request declares, and the detections it rules out.

Shared by ``/v1/chat/completions`` (:class:`~pii_guard.gateway.service.Gateway`) and
``/v1/responses`` (:class:`~pii_guard.gateway.responses.ResponsesGateway`): after detection and
before masking, both drop the word-like detections (:data:`EXEMPT_TYPES`) whose whole value is a
declared tool name **in identifier slots only** (LAB-1563: the same value in message prose or
any other slot is masked as usual — a declared name must not suppress prose detections); when
the masked texts are written back, an identifier whose only rewrites are declared tool names is
written as the client sent it (:func:`identifier_keeps_tool_names`).

The exemption covers only the types a statistical detector can misread a tool word as. A
format- or checksum-validated value (a tax ID, an IBAN, ...) is personal data whatever the
client named its tools: it is masked in the texts, and a tool name that is one fails closed
(LAB-1348).
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from typing import Any

from pii_guard.detect.known import KNOWN_DETECTOR
from pii_guard.types import EntityType, Span
from pii_guard.vault.placeholders import PLACEHOLDER_RE, normalize_value

__all__ = ["EXEMPT_TYPES", "identifier_keeps_tool_names", "tool_names", "without_tool_names"]

#: The entity types a declared tool name is exempt from: the word-like types the NER (or the
#: LLM) can misread a tool vocabulary word as ("Muse" as a PERSON, LAB-1299). Every other type
#: is found by format or checksum and is personal data even when a tool is named after it: a
#: tool named after a valid tax ID used to keep that ID unmasked everywhere (LAB-1348).
EXEMPT_TYPES: frozenset[EntityType] = frozenset(
    {EntityType.PERSON, EntityType.ORGANIZATION, EntityType.ADDRESS}
)

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
    texts: list[str],
    spans: list[list[Span]],
    names: frozenset[str],
    kinds: list[str | None] | None = None,
) -> list[list[Span]]:
    """``spans`` without the tool-name detections in **identifier slots**.

    A client's tool vocabulary is not personal data, and it goes upstream as written anyway:
    tool and namespace names are identifiers, sent unmasked or the request is refused. Muse
    Code 1.4.14 says "Muse" alone in its reminder prompts; the NER read it as a PERSON, and the
    vault then masked the ``muse`` namespace (an identifier) as another occurrence of that
    value, so the request was refused (LAB-1299). Chat Completions had the same gap for
    ``tools[].function.name`` (LAB-1317).

    The exemption is restricted to identifier slots (``kinds``, one slot kind per text; a
    missing kind counts as non-identifier): a tool name is client-controlled, so exempting the
    same value in message prose let a client unmask a real name by naming a tool after it
    (LAB-1563). Prose occurrences are masked as usual; the identifier rewrite that masking
    then causes is still undone at write-back (:func:`identifier_keeps_tool_names`, LAB-1324),
    so tool-name identifiers keep working. Values the operator pre-loaded (``known``) are
    kept, and so is every detection of a type outside :data:`EXEMPT_TYPES` (LAB-1348).
    """
    if not names:
        return spans
    slot_kinds: list[str | None] = kinds if kinds is not None else [None] * len(texts)
    return [
        [
            s
            for s in found
            if kind != "identifier"
            or s.detector == KNOWN_DETECTOR
            or s.entity_type not in EXEMPT_TYPES
            or normalize_value(text[s.start : s.end]) not in names
        ]
        for text, found, kind in zip(texts, spans, slot_kinds, strict=True)
    ]


def identifier_keeps_tool_names(
    text: str,
    masked: str,
    names: frozenset[str],
    original: Callable[[str], str | None],
) -> bool:
    """Whether every placeholder in ``masked`` (an identifier ``text`` masked by the vault)
    stands for one of the declared tool ``names``, so ``text`` can go upstream as written.

    :func:`without_tool_names` drops the detections of a tool name, but the vault masks every
    occurrence of every value its session holds: a value read from an image's text (then the
    remask sweeps every text) or learned in an earlier turn that declared no tools still
    rewrote the ``muse`` identifier, and the request was refused (LAB-1324). The tool names go
    upstream as written in the tool definitions anyway, so keeping them in an identifier
    reveals nothing more. A placeholder counts only when both the text it replaced and its
    session value (``original``, ``None`` for a placeholder the session did not issue) are
    declared names and its type is one of :data:`EXEMPT_TYPES`; anything else, a real name
    glued to a tool name or a tool named after a tax ID included, fails closed (LAB-1348).
    The caller leaves the operator's pre-loaded ``known`` values out of ``names``.
    """
    if not names:
        return False
    literals = PLACEHOLDER_RE.split(masked)[:: PLACEHOLDER_RE.groups + 1]
    found = list(PLACEHOLDER_RE.finditer(masked))
    if any(m.group(1) not in EXEMPT_TYPES for m in found):
        return False
    placeholders = [m.group(0) for m in found]
    if not placeholders:
        return masked == text
    match = re.fullmatch("(.+?)".join(re.escape(part) for part in literals), text, re.DOTALL)
    if match is None:
        return False
    for surface, placeholder in zip(match.groups(), placeholders, strict=True):
        value = original(placeholder)
        if value is None or normalize_value(value) not in names:
            return False
        if normalize_value(surface) not in names:
            return False
    return True
