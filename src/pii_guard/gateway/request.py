"""Find every text in a Chat Completions request body that must be masked.

:func:`collect_texts` walks ``messages`` (every role: system, developer, user, assistant
history, tool results), ``content`` strings and text parts, refusals, assistant
``tool_calls[].function.arguments`` (and the legacy ``function_call``), and the top-level
``user`` field. It returns :class:`TextSlot` objects that write the masked text back in place.

Tool-call arguments are JSON: they are parsed and every string (keys included) is masked as
its own text, so escaped characters can't hide a value from the detectors and the result is
re-serialised as valid JSON. Arguments that are not valid JSON are masked as plain text.

A message ``name`` that contains detected personal data can't carry a placeholder (providers
restrict it to ``[A-Za-z0-9_-]``), so it is removed instead.

Fail closed (ADR 0006): content parts that can't be masked yet (images, audio, files) and
malformed bodies are rejected; nothing is forwarded.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from pii_guard.types import PiiGuardError

__all__ = [
    "InvalidChatRequestError",
    "TextSlot",
    "UnsupportedContentError",
    "collect_texts",
]

#: Message-level string fields that carry free text besides ``content``.
_TEXT_FIELDS = ("refusal", "reasoning_content", "reasoning")
_TEXT_PART_TYPES = {"text": "text", "refusal": "refusal"}


class InvalidChatRequestError(PiiGuardError):
    code = "invalid_request"
    status_code = 400


class UnsupportedContentError(PiiGuardError):
    """Content the gateway can't mask yet. Rejected, never passed through."""

    code = "unsupported_content"
    status_code = 400


@dataclass(slots=True)
class TextSlot:
    """One text to detect and mask, and how to write the masked text back."""

    text: str
    write: Callable[[str], None] = field(repr=False)
    kind: str = "content"

    def __repr__(self) -> str:  # never the text
        return f"TextSlot(kind={self.kind!r}, length={len(self.text)})"


@dataclass(slots=True)
class CollectedTexts:
    slots: list[TextSlot]
    #: Run after every slot has been written (re-serialise tool-call arguments).
    finalizers: list[Callable[[], None]]

    def finalize(self) -> None:
        for finalize in self.finalizers:
            finalize()


def collect_texts(body: object) -> CollectedTexts:
    if not isinstance(body, dict):
        raise InvalidChatRequestError("request body must be a JSON object")
    messages = body.get("messages")
    if not isinstance(messages, list) or not messages:
        raise InvalidChatRequestError("messages must be a non-empty array")
    if not isinstance(body.get("model"), str) or not body["model"]:
        raise InvalidChatRequestError("model must be a non-empty string")
    out = CollectedTexts([], [])
    for index, message in enumerate(messages):
        if not isinstance(message, dict):
            raise InvalidChatRequestError(f"messages.{index} must be an object")
        _collect_message(message, index, out)
    if isinstance(body.get("user"), str):
        out.slots.append(TextSlot(body["user"], _setter(body, "user"), "user"))
    return out


def _setter(container: dict[str, Any] | list[Any], key: Any) -> Callable[[str], None]:
    def write(value: str) -> None:
        container[key] = value

    return write


def _collect_message(message: dict[str, Any], index: int, out: CollectedTexts) -> None:
    where = f"messages.{index}"
    content = message.get("content")
    if isinstance(content, str):
        out.slots.append(TextSlot(content, _setter(message, "content")))
    elif isinstance(content, list):
        for part_index, part in enumerate(content):
            _collect_part(part, f"{where}.content.{part_index}", out)
    elif content is not None:
        raise InvalidChatRequestError(f"{where}.content must be a string, an array or null")

    for name in _TEXT_FIELDS:
        if isinstance(message.get(name), str):
            out.slots.append(TextSlot(message[name], _setter(message, name), name))

    name = message.get("name")
    if isinstance(name, str) and message.get("role") != "function":
        original = name

        def write_name(masked: str, message: dict[str, Any] = message) -> None:
            if masked != original:
                message.pop("name", None)

        out.slots.append(TextSlot(name, write_name, "name"))

    tool_calls = message.get("tool_calls")
    if tool_calls is not None:
        if not isinstance(tool_calls, list):
            raise InvalidChatRequestError(f"{where}.tool_calls must be an array")
        for call_index, call in enumerate(tool_calls):
            function = call.get("function") if isinstance(call, dict) else None
            if isinstance(function, dict):
                _collect_arguments(function, out)
            elif call is not None and not isinstance(call, dict):
                raise InvalidChatRequestError(f"{where}.tool_calls.{call_index} must be an object")
    function_call = message.get("function_call")
    if isinstance(function_call, dict):
        _collect_arguments(function_call, out)


def _collect_part(part: object, where: str, out: CollectedTexts) -> None:
    if not isinstance(part, dict):
        raise InvalidChatRequestError(f"{where} must be an object")
    part_type = part.get("type")
    key = _TEXT_PART_TYPES.get(part_type) if isinstance(part_type, str) else None
    if key is None:
        shown = part_type if isinstance(part_type, str) and len(part_type) <= 32 else "unknown"
        raise UnsupportedContentError(
            f"{where}: content parts of type {shown!r} are not supported; the gateway masks "
            "text only for now and does not forward what it cannot mask"
        )
    value = part.get(key)
    if not isinstance(value, str):
        raise InvalidChatRequestError(f"{where}.{key} must be a string")
    out.slots.append(TextSlot(value, _setter(part, key)))


def _collect_arguments(function: dict[str, Any], out: CollectedTexts) -> None:
    arguments = function.get("arguments")
    if not isinstance(arguments, str):
        return
    try:
        parsed = json.loads(arguments)
    except ValueError:
        out.slots.append(TextSlot(arguments, _setter(function, "arguments"), "arguments"))
        return
    holder = [parsed]
    _collect_json(holder, 0, out)

    def reserialize() -> None:
        function["arguments"] = json.dumps(holder[0], ensure_ascii=False)

    out.finalizers.append(reserialize)


def _collect_json(container: dict[str, Any] | list[Any], key: Any, out: CollectedTexts) -> None:
    value = container[key]
    if isinstance(value, str):
        out.slots.append(TextSlot(value, _setter(container, key), "arguments"))
    elif isinstance(value, list):
        for i in range(len(value)):
            _collect_json(value, i, out)
    elif isinstance(value, dict):
        # Keys can carry values too ({"Teszt Elek": ...}): rebuild the dict with masked keys.
        items = [[k, v] for k, v in value.items()]
        for item in items:
            out.slots.append(TextSlot(item[0], _setter(item, 0), "arguments"))
            _collect_json(item, 1, out)

        def rebuild(value: dict[str, Any] = value, items: list[list[Any]] = items) -> None:
            value.clear()
            value.update((k, v) for k, v in items)

        # Inner dicts must be rebuilt before outer ones re-serialise: prepend.
        out.finalizers.insert(0, rebuild)
