"""Find every text in a Chat Completions request body that must be masked.

:func:`collect_texts` walks ``messages`` (every role: system, developer, user, assistant
history, tool results), ``content`` strings and text parts, refusals, assistant
``tool_calls[].function.arguments`` (and the legacy ``function_call``), and the top-level
``user`` field. It returns :class:`TextSlot` objects that write the masked text back in place.

Request metadata is masked too: tool definitions (``tools[]``, legacy ``functions[]``),
``response_format.json_schema`` and ``metadata`` values. In a JSON Schema every free-text
string (``description``, ``title``, ``enum``/``const``/``default``/``examples`` values, ...) is
masked; structural strings (``type``, ``$ref``, ``format``, ...) are left alone. Identifiers
(function names, ``properties`` keys, ``required`` entries, ``metadata`` keys) can't carry a
placeholder, so they are only checked: personal data in one rejects the request
(:class:`UnsupportedContentError`, naming the location, never the value).

Tool-call arguments are JSON: they are parsed and every string (keys included) is masked as
its own text, so escaped characters can't hide a value from the detectors and the result is
re-serialised as valid JSON. Arguments that are not valid JSON are masked as plain text.

A message ``name`` that contains detected personal data can't carry a placeholder (providers
restrict it to ``[A-Za-z0-9_-]``), so it is removed instead.

Images: ``image_url`` parts whose URL is an inline ``data:image/png|jpeg;base64,...`` URL are
returned as :class:`ImageSlot` objects; the gateway masks them with the visual pipeline and
writes a masked PNG data URL back. :meth:`ImageSlot.annotate` adds a text part right after the
image part (the masked transcript and document summary), inserted when the body is finalized.
Remote ``http(s)`` image URLs are rejected: the guard never
fetches arbitrary URLs, and an image it can't see can't be masked.

Fail closed (ADR 0006): content parts that can't be masked (remote images, audio, files) and
malformed bodies are rejected; nothing is forwarded.
"""

from __future__ import annotations

import base64
import binascii
import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from pii_guard.types import PiiGuardError

__all__ = [
    "ImageSlot",
    "InvalidChatRequestError",
    "TextSlot",
    "UnsupportedContentError",
    "collect_texts",
]

#: Message-level string fields that carry free text besides ``content``.
_TEXT_FIELDS = ("refusal", "reasoning_content", "reasoning")
_TEXT_PART_TYPES = {"text": "text", "refusal": "refusal"}
_IMAGE_SIGNATURES = (b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff")
_DATA_URL_RE = re.compile(r"^data:(image/(?:png|jpeg|jpg));base64,", re.IGNORECASE)
#: JSON-Schema keywords whose string values are structure, not text: never masked.
_SCHEMA_STRUCTURAL = frozenset({"type", "$ref", "$schema", "$id", "$anchor", "format"})
#: JSON-Schema keywords whose values are data (any JSON): every string in them is masked.
_SCHEMA_DATA = frozenset({"enum", "const", "default", "examples"})
#: JSON-Schema keywords mapping identifiers (checked, not masked) to sub-schemas.
_SCHEMA_NAMED = frozenset({"properties", "patternProperties", "$defs", "definitions"})
#: Every keyword above plus the common ones whose keys are structure (not checked).
_SCHEMA_KEYWORDS = (
    _SCHEMA_STRUCTURAL
    | _SCHEMA_DATA
    | _SCHEMA_NAMED
    | frozenset(
        {
            "$comment",
            "additionalItems",
            "additionalProperties",
            "allOf",
            "anyOf",
            "contains",
            "contentEncoding",
            "contentMediaType",
            "dependentRequired",
            "dependentSchemas",
            "description",
            "else",
            "exclusiveMaximum",
            "exclusiveMinimum",
            "if",
            "items",
            "maxContains",
            "maxItems",
            "maxLength",
            "maxProperties",
            "maximum",
            "minContains",
            "minItems",
            "minLength",
            "minProperties",
            "minimum",
            "multipleOf",
            "not",
            "nullable",
            "oneOf",
            "pattern",
            "prefixItems",
            "propertyNames",
            "readOnly",
            "required",
            "strict",
            "then",
            "title",
            "unevaluatedItems",
            "unevaluatedProperties",
            "uniqueItems",
            "writeOnly",
        }
    )
)


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
class ImageSlot:
    """One inline image to mask, and how to write the masked PNG back as a data URL."""

    data: bytes = field(repr=False)
    write: Callable[[str], None] = field(repr=False)
    where: str = ""
    #: Adds a text part after the image part (``None``: the image is not in a content array).
    annotate_with: Callable[[str], None] | None = field(default=None, repr=False)

    def __repr__(self) -> str:  # never the bytes
        return f"ImageSlot(where={self.where!r}, bytes={len(self.data)})"

    def annotate(self, text: str) -> bool:
        """Add a ``{"type": "text", "text": text}`` part right after this image's part, when
        the body is finalized. ``False`` if the image is not in a content array."""
        if self.annotate_with is None:
            return False
        self.annotate_with(text)
        return True


@dataclass(slots=True)
class CollectedTexts:
    slots: list[TextSlot]
    #: Run after every slot has been written (re-serialise tool-call arguments).
    finalizers: list[Callable[[], None]]
    images: list[ImageSlot] = field(default_factory=list)

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
    _collect_request_metadata(body, out)
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
            _collect_part(part, f"{where}.content.{part_index}", out, content)
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


def _collect_part(
    part: object, where: str, out: CollectedTexts, content: list[Any] | None = None
) -> None:
    if not isinstance(part, dict):
        raise InvalidChatRequestError(f"{where} must be an object")
    part_type = part.get("type")
    if part_type == "image_url":
        _collect_image(part, where, out, content)
        return
    key = _TEXT_PART_TYPES.get(part_type) if isinstance(part_type, str) else None
    if key is None:
        shown = part_type if isinstance(part_type, str) and len(part_type) <= 32 else "unknown"
        raise UnsupportedContentError(
            f"{where}: content parts of type {shown!r} are not supported; the gateway masks "
            "text and inline images only and does not forward what it cannot mask"
        )
    value = part.get(key)
    if not isinstance(value, str):
        raise InvalidChatRequestError(f"{where}.{key} must be a string")
    out.slots.append(TextSlot(value, _setter(part, key)))


def _collect_image(
    part: dict[str, Any], where: str, out: CollectedTexts, content: list[Any] | None = None
) -> None:
    image_url = part.get("image_url")
    holder: dict[str, Any]
    if isinstance(image_url, dict) and isinstance(image_url.get("url"), str):
        holder, key = image_url, "url"
    elif isinstance(image_url, str):
        holder, key = part, "image_url"
    else:
        raise UnsupportedContentError(f"{where}: image_url parts need an inline data URL")
    url: str = holder[key]
    match = _DATA_URL_RE.match(url)
    if match is None:
        if url.startswith("data:"):
            raise UnsupportedContentError(
                f"{where}: only base64 PNG and JPEG data URLs can be masked"
            )
        raise UnsupportedContentError(
            f"{where}: remote image URLs are not fetched; send the image inline as a "
            "base64 data URL (data:image/png;base64,...) so it can be masked"
        )
    try:
        data = base64.b64decode("".join(url[match.end() :].split()), validate=True)
    except (binascii.Error, ValueError):
        raise InvalidChatRequestError(f"{where}: image data URL is not valid base64") from None
    if not data.startswith(_IMAGE_SIGNATURES):
        raise UnsupportedContentError(f"{where}: the inline image is not a PNG or JPEG image")

    def write(masked_url: str) -> None:
        holder[key] = masked_url

    annotate_with: Callable[[str], None] | None = None
    if content is not None:
        container = content

        def annotate_with(text: str) -> None:
            def insert() -> None:
                index = next(i for i, p in enumerate(container) if p is part)
                container.insert(index + 1, {"type": "text", "text": text})

            out.finalizers.append(insert)

    out.images.append(ImageSlot(data, write, where, annotate_with))


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


def _collect_json(
    container: dict[str, Any] | list[Any], key: Any, out: CollectedTexts, kind: str = "arguments"
) -> None:
    value = container[key]
    if isinstance(value, str):
        out.slots.append(TextSlot(value, _setter(container, key), kind))
    elif isinstance(value, list):
        for i in range(len(value)):
            _collect_json(value, i, out, kind)
    elif isinstance(value, dict):
        # Keys can carry values too ({"Teszt Elek": ...}): rebuild the dict with masked keys.
        items = [[k, v] for k, v in value.items()]
        for item in items:
            out.slots.append(TextSlot(item[0], _setter(item, 0), kind))
            _collect_json(item, 1, out, kind)

        def rebuild(value: dict[str, Any] = value, items: list[list[Any]] = items) -> None:
            value.clear()
            value.update((k, v) for k, v in items)

        # Inner dicts must be rebuilt before outer ones re-serialise: prepend.
        out.finalizers.insert(0, rebuild)


# --- request metadata: tool definitions, response_format, metadata ---------------------


def _collect_request_metadata(body: dict[str, Any], out: CollectedTexts) -> None:
    tools = body.get("tools")
    if isinstance(tools, list):
        for index, tool in enumerate(tools):
            if not isinstance(tool, dict):
                continue
            if "name" in tool or "parameters" in tool:
                # A flat definition: {"type": "function", "name": ..., "parameters": ...}.
                _collect_function(tool, f"tools.{index}", out)
                continue
            # {"type": "function", "function": {...}} (or another tool type's own object).
            for key, value in tool.items():
                if key != "type" and isinstance(value, dict):
                    _collect_function(value, f"tools.{index}.{key}", out)
    functions = body.get("functions")
    if isinstance(functions, list):
        for index, function in enumerate(functions):
            if isinstance(function, dict):
                _collect_function(function, f"functions.{index}", out)
    tool_choice = body.get("tool_choice")
    if isinstance(tool_choice, dict) and isinstance(tool_choice.get("function"), dict):
        _check_identifier(tool_choice["function"], "name", "tool_choice.function.name", out)
    function_call = body.get("function_call")
    if isinstance(function_call, dict):
        _check_identifier(function_call, "name", "function_call.name", out)
    response_format = body.get("response_format")
    if isinstance(response_format, dict) and isinstance(response_format.get("json_schema"), dict):
        _collect_function(response_format["json_schema"], "response_format.json_schema", out)
    metadata = body.get("metadata")
    if isinstance(metadata, dict):
        _collect_metadata(metadata, out)


def _collect_function(function: dict[str, Any], where: str, out: CollectedTexts) -> None:
    """A function (or json_schema) definition: ``name`` checked, schemas walked, text masked."""
    for key, value in function.items():
        if key in _SCHEMA_STRUCTURAL:
            continue
        if key == "name":
            _check_identifier(function, key, f"{where}.name", out)
        elif key in ("parameters", "schema"):
            _collect_schema(function, key, f"{where}.{key}", out)
        elif isinstance(value, str | list | dict):
            _collect_json(function, key, out, "tools")


def _collect_schema(
    container: dict[str, Any] | list[Any], key: Any, where: str, out: CollectedTexts
) -> None:
    value = container[key]
    if isinstance(value, str):
        out.slots.append(TextSlot(value, _setter(container, key), "tools"))
    elif isinstance(value, list):
        for i in range(len(value)):
            _collect_schema(value, i, f"{where}.{i}", out)
    elif isinstance(value, dict):
        for position, (name, sub) in enumerate(value.items()):
            if name in _SCHEMA_KEYWORDS:
                at = f"{where}.{name}"
            else:  # not a keyword: the key itself could be a value; check it, never name it
                at = f"{where}.{position}"
                _check_text(name, at, out)
            if name in _SCHEMA_STRUCTURAL:
                continue
            if name in _SCHEMA_DATA:
                _collect_json(value, name, out, "tools")
            elif name in _SCHEMA_NAMED and isinstance(sub, dict):
                for i, prop in enumerate(list(sub)):
                    _check_text(prop, f"{at}.{i}", out)
                    _collect_schema(sub, prop, f"{at}.{i}", out)
            elif name == "required" and isinstance(sub, list):
                for i, entry in enumerate(sub):
                    if isinstance(entry, str):
                        _check_text(entry, f"{at}.{i}", out)
            else:
                _collect_schema(value, name, at, out)


def _collect_metadata(metadata: dict[str, Any], out: CollectedTexts) -> None:
    for i, key in enumerate(list(metadata)):
        if isinstance(key, str):
            _check_text(key, f"metadata.{i}", out)
        _collect_json(metadata, key, out, "metadata")


def _check_identifier(holder: dict[str, Any], key: str, where: str, out: CollectedTexts) -> None:
    value = holder.get(key)
    if isinstance(value, str):
        _check_text(value, where, out)


def _check_text(text: str, where: str, out: CollectedTexts) -> None:
    """An identifier: masked text can't be written back, so personal data in it fails closed."""

    def check(masked: str) -> None:
        if masked != text:
            raise UnsupportedContentError(
                f"{where}: personal data detected in an identifier; identifiers can't carry "
                "a placeholder, so the request is not forwarded"
            )

    out.slots.append(TextSlot(text, check, "identifier"))
