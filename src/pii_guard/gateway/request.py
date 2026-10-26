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

Images: ``image_url`` parts whose URL is an inline ``data:image/png|jpeg;base64,...`` URL are
returned as :class:`ImageSlot` objects; the gateway masks them with the visual pipeline and
writes a masked PNG data URL back. Remote ``http(s)`` image URLs are rejected: the guard never
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

    def __repr__(self) -> str:  # never the bytes
        return f"ImageSlot(where={self.where!r}, bytes={len(self.data)})"


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
    if part_type == "image_url":
        _collect_image(part, where, out)
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


def _collect_image(part: dict[str, Any], where: str, out: CollectedTexts) -> None:
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

    out.images.append(ImageSlot(data, write, where))


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
