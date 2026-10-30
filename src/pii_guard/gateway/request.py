"""Find every text in a Chat Completions request body that must be masked.

:func:`collect_texts` walks ``messages`` (every role: system, developer, user, assistant
history, tool results), ``content`` strings and text parts, refusals, assistant
``tool_calls[].function.arguments`` (and the legacy ``function_call``), and the top-level
``user`` field. It returns :class:`TextSlot` objects that write the masked text back in place.

Request metadata is masked too: tool definitions (``tools[]``, legacy ``functions[]``),
``response_format.json_schema`` and ``metadata`` values. In a JSON Schema every free-text
string (``description``, ``title``, ``enum``/``const``/``default``/``examples`` values, ...) is
masked; structural strings (``type``, ``$ref``, ``format``, ...) are checked like identifiers
(personal data in one rejects the request, LAB-1563). A custom tool's
``format.grammar.definition`` is free text: it is masked. Identifiers (function names,
``properties`` keys, ``required`` entries, ``metadata`` keys, ``model``) can't carry a
placeholder, so they are only checked: personal data in one rejects the request
(:class:`UnsupportedContentError`, naming the location, never the value).

Tool-call arguments are JSON: they are parsed and every string (keys included) is masked as
its own text, so escaped characters can't hide a value from the detectors and the result is
re-serialised as valid JSON. Arguments that are not valid JSON are masked as plain text.
Number leaves (6+ digits) are detected too: a masked number is written back as the placeholder
string, an unchanged one stays the same number (LAB-1348). In a JSON Schema, keyword numbers
(``maximum``, ...) are checked like identifiers instead.

A message ``name`` that contains detected personal data can't carry a placeholder (providers
restrict it to ``[A-Za-z0-9_-]``), so it is removed instead.

Images: ``image_url`` parts whose URL is an inline ``data:image/png|jpeg;base64,...`` URL are
returned as :class:`ImageSlot` objects; the gateway masks them with the visual pipeline and
writes a masked PNG data URL back. :meth:`ImageSlot.annotate` adds a text part right after the
image part (the masked transcript and document summary), inserted when the body is finalized.
Remote ``http(s)`` image URLs are rejected: the guard never
fetches arbitrary URLs, and an image it can't see can't be masked.

Fail closed (ADR 0006): the whole request is walked against an allow-list. Every key of the
body, of a message, of a content part, of a tool call and of the nested objects the gateway
understands is either masked (free text: ``stop``, ``prediction.content``, reasoning text,
audio transcripts, ``user``/``safety_identifier``/``prompt_cache_key``, ...), checked as an
identifier (enum-like settings, ids, names), passed through (numbers, booleans, provider-signed
blobs) or rejected. Unknown keys, content parts that can't be masked (remote images, audio,
files) and malformed bodies are rejected with 400; nothing is forwarded. The table is in
docs/contracts.md ("Gateway request fields").
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
#: JSON-Schema keywords whose string values are structure, not text: checked as identifiers,
#: never masked (a custom tool's ``format.grammar.definition`` is handled before this set).
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
    #: A JSON number leaf's literal (``8123456786``, ``8123456786.0``); ``None``: a string.
    #: The vault records it when the leaf masks to one placeholder, so a tool call that echoes
    #: that placeholder as a whole string gets the number back (LAB-1361).
    number: str | None = field(default=None, repr=False)

    def __repr__(self) -> str:  # never the text
        return f"TextSlot(kind={self.kind!r}, length={len(self.text)})"


#: A line-number gutter, as Muse Code's ``read_file`` prints file lines (``12|Jane ...``),
#: after the line's leading spaces/tabs (stripped first: no backtracking over them).
_GUTTER_RE = re.compile(r"(\d{1,7})\|")


def _gutter(line: str) -> tuple[str, int] | None:
    """The line's gutter candidate (indentation, number and ``|``) and its number, or ``None``."""
    indent = len(line) - len(line.lstrip(" \t"))
    match = _GUTTER_RE.match(line, indent)
    return (line[: match.end()], int(match.group(1))) if match else None


def _gutters(lines: list[str]) -> dict[int, str]:
    """The line-number gutters of ``lines``, by line index (LAB-1583).

    A ``12|`` prefix is a gutter only inside a run of at least two adjacent lines whose
    numbers go up by exactly one (``11|``, ``12|``), as ``read_file`` and ``cat -n`` print
    them. A lone ``1234567|...`` (a pipe-delimited table row with an id) or rows with
    unrelated numbers stay visible to the detectors and to the outbound re-check: hiding a
    number that is not a line number would forward it unchecked.
    """
    found = {i: g for i, line in enumerate(lines) if (g := _gutter(line))}
    out: dict[int, str] = {}
    for i, (gutter, number) in found.items():
        before = found.get(i - 1)
        after = found.get(i + 1)
        if (before and before[1] + 1 == number) or (after and number + 1 == after[1]):
            out[i] = gutter
    return out


def _text_slot(holder: dict[str, Any], key: str, kind: str) -> TextSlot:
    """A message text or tool output; a line-number gutter (``12|``) is hidden from detection.

    Muse Code's ``read_file`` prints each file line after its number (``12|Jane Placeholder``),
    in tool outputs and again in the conversation its reminder observers get as a message.
    Glued to the first word, the gutter makes a name detector see ``12|Jane`` as one token and
    mask only the surname. The detectors get each gutter as spaces of the same length (offsets
    don't move); the masked text gets the gutters back. Only numbered runs count as gutters
    (:func:`_gutters`).
    """
    text: str = holder[key]
    lines = text.split("\n")
    gutters = _gutters(lines)
    if not gutters:
        return TextSlot(text, _setter(holder, key), kind)
    hidden = "\n".join(
        " " * len(gutters[i]) + line[len(gutters[i]) :] if i in gutters else line
        for i, line in enumerate(lines)
    )

    def write(masked: str) -> None:
        out = masked.split("\n")
        if len(out) == len(lines):
            for i, gutter in gutters.items():
                if out[i].startswith(" " * len(gutter)):
                    out[i] = gutter + out[i][len(gutter) :]
        # A masked value that spanned lines changes the line count: the gutters are dropped
        # (line numbers only; nothing unmasked is written back).
        holder[key] = "\n".join(out)

    return TextSlot(hidden, write, kind)


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
        """Add a text part (``text`` or ``input_text``) right after this image's part, when
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
    _collect_top_level(body, out)
    # ``model`` goes upstream verbatim and can't carry a placeholder: checked (LAB-1563).
    _check_text(body["model"], "model", out)
    return out


def _setter(container: dict[str, Any] | list[Any], key: Any) -> Callable[[str], None]:
    def write(value: str) -> None:
        container[key] = value

    return write


# --- the allow-list ----------------------------------------------------------------------
#
# Every key of the body, of a message, of a content part and of a tool call is in one of
# the tables below; anything else is rejected (fail closed, ADR 0006). docs/contracts.md
# ("Gateway request fields") is the same table in prose: keep them in step.

#: Field names shown in errors as-is; anything else (it could be a value) by position only.
_FIELD_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
#: Top-level fields that hold only numbers, booleans or null (sampling knobs, flags).
_TOP_SCALAR = frozenset(
    {
        "frequency_penalty",
        "logprobs",
        "max_completion_tokens",
        "max_tokens",
        "n",
        "parallel_tool_calls",
        "presence_penalty",
        "seed",
        "store",
        "stream",
        "temperature",
        "top_logprobs",
        "top_p",
        # Common sampling extensions of OpenAI-compatible servers (vLLM, Ollama, llama.cpp).
        "min_p",
        "repetition_penalty",
        "top_k",
    }
)
#: Top-level fields whose strings are enum-like settings: checked like identifiers (personal
#: data in one rejects the request), never masked.
_TOP_CHECKED = frozenset(
    {
        "audio",
        "function_call",
        "modalities",
        "reasoning_effort",
        "service_tier",
        "stream_options",
        "tool_choice",
        "verbosity",
    }
)
#: Top-level free-text strings that identify the end user or a cache entry: masked.
_TOP_USER_TEXT = ("user", "safety_identifier", "prompt_cache_key")
#: The other top-level fields, each with its own walker in :func:`_collect_top_level`.
_TOP_WALKED = frozenset(
    {
        "functions",
        "logit_bias",
        "messages",
        "metadata",
        "model",
        "prediction",
        "response_format",
        "stop",
        "tools",
        "web_search_options",
    }
)
#: Field names and enum values the API itself defines: never personal data, so not checked.
_STRUCTURAL_WORDS = frozenset(
    {
        "allowed_tools",
        "approximate",
        "auto",
        "cache_control",
        "content",
        "custom",
        "default",
        "description",
        "detail",
        "ephemeral",
        "flex",
        "format",
        "function",
        "high",
        "include_obfuscation",
        "include_usage",
        "json_object",
        "json_schema",
        "low",
        "mcp",
        "medium",
        "minimal",
        "mode",
        "name",
        "none",
        "parameters",
        "priority",
        "required",
        "schema",
        "strict",
        "text",
        "tools",
        "type",
        "voice",
    }
)
_ROLES = frozenset({"system", "developer", "user", "assistant", "tool", "function"})
#: Message-level string fields that carry free text besides ``content``: masked.
_TEXT_FIELDS = ("refusal", "reasoning_content", "reasoning")
#: Message-level fields that are lists of reasoning blocks (OpenRouter ``reasoning_details``,
#: LiteLLM ``thinking_blocks``): text keys are masked, provider-signed blobs passed as is.
_REASONING_LISTS = ("reasoning_details", "thinking_blocks")
_REASONING_TEXT = frozenset({"text", "summary", "thinking"})
#: Opaque, provider-issued values (signatures, encrypted reasoning): forwarded untouched.
_REASONING_OPAQUE = frozenset({"data", "signature", "encrypted_content"})
_REASONING_CHECKED = frozenset({"type", "format", "id", "index"})
_MESSAGE_KEYS = frozenset(
    {
        "annotations",
        "audio",
        "cache_control",
        "content",
        "function_call",
        "name",
        "prefix",
        "role",
        "tool_call_id",
        "tool_calls",
        *_TEXT_FIELDS,
        *_REASONING_LISTS,
    }
)
#: Allowed keys per content-part type (besides ``type``).
_PART_KEYS = {
    "text": frozenset({"text", "cache_control"}),
    "refusal": frozenset({"refusal"}),
    "image_url": frozenset({"image_url", "cache_control"}),
}
_IMAGE_URL_KEYS = frozenset({"url", "detail"})
_TOOL_CALL_KEYS = frozenset({"id", "type", "index", "function", "custom"})
_TOOL_CALL_FUNCTION_KEYS = frozenset({"name", "arguments"})
_TOOL_CALL_CUSTOM_KEYS = frozenset({"name", "input"})


def _field(where: str, key: object, position: int) -> str:
    """``where.key`` if the key looks like a field name, else ``where.#position``."""
    shown = key if isinstance(key, str) and _FIELD_NAME_RE.match(key) else f"#{position}"
    return f"{where}.{shown}" if where else str(shown)


def _reject_unknown(holder: dict[str, Any], allowed: frozenset[str], where: str, what: str) -> None:
    for position, key in enumerate(holder):
        if key not in allowed:
            raise UnsupportedContentError(
                f"{_field(where, key, position)}: unsupported {what} field; the gateway only "
                "forwards fields it knows how to mask (see docs/contracts.md)"
            )


def _collect_top_level(body: dict[str, Any], out: CollectedTexts) -> None:
    allowed = _TOP_SCALAR | _TOP_CHECKED | _TOP_WALKED | frozenset(_TOP_USER_TEXT)
    _reject_unknown(body, allowed, "", "request")
    for key in _TOP_SCALAR:
        if key in body:
            _require_scalars(body[key], key)
    for key in _TOP_CHECKED:
        if key in body:
            _check_json(body, key, key, out)
    for key in _TOP_USER_TEXT:
        value = body.get(key)
        if isinstance(value, str):
            out.slots.append(TextSlot(value, _setter(body, key), "user"))
        elif value is not None:
            raise InvalidChatRequestError(f"{key} must be a string")
    _collect_stop(body, out)
    _collect_logit_bias(body.get("logit_bias"))
    _collect_prediction(body, out)
    _collect_web_search_options(body, out)
    _collect_request_metadata(body, out)


def _require_scalars(value: object, where: str) -> None:
    """Numbers, booleans and null only (nested in arrays/objects with field-name keys)."""
    if value is None or isinstance(value, bool | int | float):
        return
    if isinstance(value, list):
        for i, item in enumerate(value):
            _require_scalars(item, f"{where}.{i}")
        return
    raise InvalidChatRequestError(f"{where} must be a number, a boolean or null")


def _check_json(
    container: dict[str, Any] | list[Any], key: Any, where: str, out: CollectedTexts
) -> None:
    """A structural value: every string in it (object keys too) and every long number is
    checked as an identifier."""
    value = container[key]
    if isinstance(value, str):
        _check_name(value, where, out)
    elif (number := _number_text(value)) is not None:
        _check_text(number, where, out)
    elif isinstance(value, list):
        for i in range(len(value)):
            _check_json(value, i, f"{where}.{i}", out)
    elif isinstance(value, dict):
        for position, name in enumerate(list(value)):
            at = _field(where, name, position)
            _check_name(name, at, out)
            _check_json(value, name, at, out)


def _check_name(text: str, where: str, out: CollectedTexts) -> None:
    """:func:`_check_text`, skipping the API's own field names and enum values."""
    if text not in _STRUCTURAL_WORDS:
        _check_text(text, where, out)


def _collect_stop(body: dict[str, Any], out: CollectedTexts) -> None:
    stop = body.get("stop")
    if isinstance(stop, str):
        out.slots.append(TextSlot(stop, _setter(body, "stop"), "stop"))
    elif isinstance(stop, list):
        for i, entry in enumerate(stop):
            if not isinstance(entry, str):
                raise InvalidChatRequestError(f"stop.{i} must be a string")
            out.slots.append(TextSlot(entry, _setter(stop, i), "stop"))
    elif stop is not None:
        raise InvalidChatRequestError("stop must be a string, an array of strings or null")


def _collect_logit_bias(logit_bias: object) -> None:
    """Token ids to biases: keys must be token ids, values numbers. Nothing to mask."""
    if logit_bias is None:
        return
    if not isinstance(logit_bias, dict):
        raise InvalidChatRequestError("logit_bias must be an object")
    for position, (token, bias) in enumerate(logit_bias.items()):
        if not (isinstance(token, str) and token.isascii() and token.isdigit()):
            raise InvalidChatRequestError(f"logit_bias.#{position}: keys must be token ids")
        if isinstance(bias, bool) or not isinstance(bias, int | float):
            raise InvalidChatRequestError(f"logit_bias.#{position}: values must be numbers")


def _collect_prediction(body: dict[str, Any], out: CollectedTexts) -> None:
    prediction = body.get("prediction")
    if prediction is None:
        return
    if not isinstance(prediction, dict):
        raise InvalidChatRequestError("prediction must be an object")
    _reject_unknown(prediction, frozenset({"type", "content"}), "prediction", "prediction")
    if "type" in prediction:
        _check_json(prediction, "type", "prediction.type", out)
    content = prediction.get("content")
    if isinstance(content, str):
        out.slots.append(TextSlot(content, _setter(prediction, "content"), "prediction"))
    elif isinstance(content, list):
        for i, part in enumerate(content):
            if isinstance(part, dict) and part.get("type") != "text":
                raise UnsupportedContentError("prediction.content: only text parts are supported")
            _collect_part(part, f"prediction.content.{i}", out)
    elif content is not None:
        raise InvalidChatRequestError("prediction.content must be a string or an array")


def _collect_web_search_options(body: dict[str, Any], out: CollectedTexts) -> None:
    options = body.get("web_search_options")
    if options is None:
        return
    if not isinstance(options, dict):
        raise InvalidChatRequestError("web_search_options must be an object")
    allowed = frozenset({"search_context_size", "user_location"})
    _reject_unknown(options, allowed, "web_search_options", "web_search_options")
    if "search_context_size" in options:
        _check_json(options, "search_context_size", "web_search_options.search_context_size", out)
    if "user_location" in options:
        # A location is personal data: every string in it is masked.
        _collect_json(options, "user_location", out, "web_search")


def _collect_message(message: dict[str, Any], index: int, out: CollectedTexts) -> None:
    where = f"messages.{index}"
    _reject_unknown(message, _MESSAGE_KEYS, where, "message")
    role = message.get("role")
    if role not in _ROLES:
        raise InvalidChatRequestError(f"{where}.role must be one of {', '.join(sorted(_ROLES))}")
    content = message.get("content")
    if isinstance(content, str):
        out.slots.append(_text_slot(message, "content", "content"))
    elif isinstance(content, list):
        for part_index, part in enumerate(content):
            _collect_part(part, f"{where}.content.{part_index}", out, content)
    elif content is not None:
        raise InvalidChatRequestError(f"{where}.content must be a string, an array or null")

    for name in _TEXT_FIELDS:
        value = message.get(name)
        if isinstance(value, str):
            out.slots.append(_text_slot(message, name, name))
        elif value is not None:
            _collect_json(message, name, out, name)
    for name in _REASONING_LISTS:
        if message.get(name) is not None:
            _collect_reasoning_blocks(message, name, f"{where}.{name}", out)
    if message.get("annotations") is not None:
        _collect_json(message, "annotations", out, "annotations")
    if message.get("audio") is not None:
        _collect_message_audio(message, f"{where}.audio", out)
    for name in ("cache_control", "prefix", "tool_call_id"):
        if name in message:
            _check_json(message, name, f"{where}.{name}", out)

    name = message.get("name")
    if isinstance(name, str) and role != "function":
        original = name

        def write_name(masked: str, message: dict[str, Any] = message) -> None:
            if masked != original:
                message.pop("name", None)

        out.slots.append(TextSlot(name, write_name, "name"))
    elif isinstance(name, str):
        # A function result's name must match the call's name: it can't be dropped.
        _check_text(name, f"{where}.name", out)
    elif name is not None:
        raise InvalidChatRequestError(f"{where}.name must be a string")

    tool_calls = message.get("tool_calls")
    if tool_calls is not None:
        if not isinstance(tool_calls, list):
            raise InvalidChatRequestError(f"{where}.tool_calls must be an array")
        for call_index, call in enumerate(tool_calls):
            _collect_tool_call(call, f"{where}.tool_calls.{call_index}", out)
    function_call = message.get("function_call")
    if function_call is not None:
        if not isinstance(function_call, dict):
            raise InvalidChatRequestError(f"{where}.function_call must be an object")
        _collect_call_function(function_call, f"{where}.function_call", out)


def _collect_reasoning_blocks(
    message: dict[str, Any], name: str, where: str, out: CollectedTexts
) -> None:
    blocks = message[name]
    if not isinstance(blocks, list):
        raise InvalidChatRequestError(f"{where} must be an array")
    allowed = _REASONING_TEXT | _REASONING_OPAQUE | _REASONING_CHECKED
    for i, block in enumerate(blocks):
        at = f"{where}.{i}"
        if not isinstance(block, dict):
            raise InvalidChatRequestError(f"{at} must be an object")
        _reject_unknown(block, allowed, at, "reasoning")
        for key in list(block):
            if key in _REASONING_TEXT:
                _collect_json(block, key, out, "reasoning")
            elif key in _REASONING_CHECKED:
                _check_json(block, key, f"{at}.{key}", out)
            elif not isinstance(block[key], str | None):  # opaque blobs are strings
                raise InvalidChatRequestError(f"{at}.{key} must be a string")


def _collect_message_audio(message: dict[str, Any], where: str, out: CollectedTexts) -> None:
    """An assistant's earlier audio reply, referenced by id; its transcript is masked."""
    audio = message["audio"]
    if not isinstance(audio, dict):
        raise InvalidChatRequestError(f"{where} must be an object")
    _reject_unknown(audio, frozenset({"id", "transcript", "expires_at"}), where, "audio")
    if "id" in audio:
        _check_json(audio, "id", f"{where}.id", out)
    if "expires_at" in audio:
        _require_scalars(audio["expires_at"], f"{where}.expires_at")
    transcript = audio.get("transcript")
    if isinstance(transcript, str):
        out.slots.append(TextSlot(transcript, _setter(audio, "transcript"), "audio"))
    elif transcript is not None:
        raise InvalidChatRequestError(f"{where}.transcript must be a string")


def _collect_tool_call(call: object, where: str, out: CollectedTexts) -> None:
    if call is None:
        return
    if not isinstance(call, dict):
        raise InvalidChatRequestError(f"{where} must be an object")
    _reject_unknown(call, _TOOL_CALL_KEYS, where, "tool call")
    for key in ("id", "type"):
        if key in call:
            _check_json(call, key, f"{where}.{key}", out)
    if "index" in call:
        _require_scalars(call["index"], f"{where}.index")
    function = call.get("function")
    if function is not None:
        if not isinstance(function, dict):
            raise InvalidChatRequestError(f"{where}.function must be an object")
        _collect_call_function(function, f"{where}.function", out)
    custom = call.get("custom")
    if custom is not None:
        if not isinstance(custom, dict):
            raise InvalidChatRequestError(f"{where}.custom must be an object")
        _reject_unknown(custom, _TOOL_CALL_CUSTOM_KEYS, f"{where}.custom", "tool call")
        _check_identifier(custom, "name", f"{where}.custom.name", out)
        if custom.get("input") is not None:
            _collect_json(custom, "input", out, "arguments")


def _collect_call_function(function: dict[str, Any], where: str, out: CollectedTexts) -> None:
    """``{"name": ..., "arguments": ...}`` of a tool call: name checked, arguments masked."""
    _reject_unknown(function, _TOOL_CALL_FUNCTION_KEYS, where, "tool call")
    name = function.get("name")
    if isinstance(name, str):
        _check_text(name, f"{where}.name", out)
    elif name is not None:
        raise InvalidChatRequestError(f"{where}.name must be a string")
    _collect_arguments(function, where, out)


def _collect_part(
    part: object, where: str, out: CollectedTexts, content: list[Any] | None = None
) -> None:
    if not isinstance(part, dict):
        raise InvalidChatRequestError(f"{where} must be an object")
    part_type = part.get("type")
    allowed = _PART_KEYS.get(part_type) if isinstance(part_type, str) else None
    if allowed is None:
        shown = part_type if isinstance(part_type, str) and len(part_type) <= 32 else "unknown"
        raise UnsupportedContentError(
            f"{where}: content parts of type {shown!r} are not supported; the gateway masks "
            "text and inline images only and does not forward what it cannot mask"
        )
    _reject_unknown(part, allowed | {"type"}, where, "content part")
    if "cache_control" in part:
        _check_json(part, "cache_control", f"{where}.cache_control", out)
    if part_type == "image_url":
        _collect_image(part, where, out, content)
        return
    key = _TEXT_PART_TYPES[part_type]
    value = part.get(key)
    if not isinstance(value, str):
        raise InvalidChatRequestError(f"{where}.{key} must be a string")
    out.slots.append(_text_slot(part, key, "content"))


def _collect_image(
    part: dict[str, Any],
    where: str,
    out: CollectedTexts,
    content: list[Any] | None = None,
    *,
    text_type: str = "text",
) -> None:
    """An inline PNG/JPEG data URL (``image_url`` as an object with ``url`` or as a string),
    queued for the visual pipeline. ``text_type`` is the part type of the transcript added
    after it (``"text"`` for Chat Completions, ``"input_text"`` for the Responses API)."""
    image_url = part.get("image_url")
    holder: dict[str, Any]
    if isinstance(image_url, dict) and isinstance(image_url.get("url"), str):
        _reject_unknown(image_url, _IMAGE_URL_KEYS, f"{where}.image_url", "image_url")
        if "detail" in image_url:
            _check_json(image_url, "detail", f"{where}.image_url.detail", out)
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
                container.insert(index + 1, {"type": text_type, "text": text})

            out.finalizers.append(insert)

    out.images.append(ImageSlot(data, write, where, annotate_with))


def _collect_arguments(function: dict[str, Any], where: str, out: CollectedTexts) -> None:
    """Tool-call arguments: a JSON string (parsed, masked, re-serialised), a JSON value
    (LiteLLM/Ollama send an object; masked in place) or absent. Anything else is rejected."""
    arguments = function.get("arguments")
    if arguments is None:
        return
    if isinstance(arguments, dict | list):
        _collect_json(function, "arguments", out)
        return
    if not isinstance(arguments, str):
        raise InvalidChatRequestError(f"{where}.arguments must be a JSON string or object")
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


#: A bare number with fewer digits than this is never personal data on its own (the shortest
#: numeric types, TAJ and tax IDs, have 9 and 10 digits; phone and account numbers more).
_MIN_NUMBER_DIGITS = 6


def _number_text(value: object) -> str | None:
    """The text a JSON number leaf is detected as (``None``: not a number, or too short).

    ``bool`` is an ``int`` in Python but not a number in JSON. An integral float
    (``8123456786.0``) is detected in its integer form, as the detectors read digits."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    if isinstance(value, float) and value.is_integer() and abs(value) < 1e16:
        text = str(int(value))
    else:
        text = json.dumps(value)
    return text if sum(ch.isdigit() for ch in text) >= _MIN_NUMBER_DIGITS else None


def _number_setter(container: dict[str, Any] | list[Any], key: Any) -> Callable[[str], None]:
    """Write a masked number back: unchanged, it stays the original number; masked, it
    becomes the placeholder string (a JSON number can't carry one, LAB-1348)."""
    text = _number_text(container[key])

    def write(masked: str) -> None:
        if masked != text:
            container[key] = masked

    return write


def _collect_json(
    container: dict[str, Any] | list[Any], key: Any, out: CollectedTexts, kind: str = "arguments"
) -> None:
    value = container[key]
    if isinstance(value, str):
        out.slots.append(TextSlot(value, _setter(container, key), kind))
    elif (number := _number_text(value)) is not None:
        # Numeric JSON fields can hold identifiers; a masked number becomes a string.
        literal = json.dumps(value)
        out.slots.append(TextSlot(number, _number_setter(container, key), kind, literal))
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
            # Distinct spellings can share a vault placeholder (case/Unicode folding).
            # Fail closed before replacing the object: merging loses arguments, while
            # inventing placeholders would break reversible vault mappings (LAB-1568).
            rebuilt = dict(items)
            if len(rebuilt) != len(items):
                raise InvalidChatRequestError(
                    "masking JSON object keys produced a collision; request not forwarded"
                )
            value.clear()
            value.update(rebuilt)

        # Inner dicts must be rebuilt before outer ones re-serialise: prepend.
        out.finalizers.insert(0, rebuild)


# --- request metadata: tool definitions, response_format, metadata ---------------------


def _collect_request_metadata(body: dict[str, Any], out: CollectedTexts) -> None:
    tools = body.get("tools")
    if tools is not None:
        if not isinstance(tools, list):
            raise InvalidChatRequestError("tools must be an array")
        for index, tool in enumerate(tools):
            if not isinstance(tool, dict):
                raise InvalidChatRequestError(f"tools.{index} must be an object")
            if "name" in tool or "parameters" in tool:
                # A flat definition: {"type": "function", "name": ..., "parameters": ...}.
                _collect_function(tool, f"tools.{index}", out)
                continue
            # {"type": "function", "function": {...}} or another tool type (MCP, custom...):
            # nested objects are definitions, every other string is free text.
            for position, (key, value) in enumerate(list(tool.items())):
                at = _field(f"tools.{index}", key, position)
                _check_name(key, at, out)
                if key == "type":
                    _check_json(tool, key, at, out)
                elif isinstance(value, dict):
                    _collect_function(value, at, out)
                elif isinstance(value, str | list) or _number_text(value) is not None:
                    # A direct numeric leaf is a number slot, as in _collect_json (LAB-1563).
                    _collect_json(tool, key, out, "tools")
    functions = body.get("functions")
    if functions is not None:
        if not isinstance(functions, list):
            raise InvalidChatRequestError("functions must be an array")
        for index, function in enumerate(functions):
            if not isinstance(function, dict):
                raise InvalidChatRequestError(f"functions.{index} must be an object")
            _collect_function(function, f"functions.{index}", out)
    response_format = body.get("response_format")
    if response_format is not None:
        _collect_response_format(response_format, out)
    metadata = body.get("metadata")
    if metadata is not None:
        if not isinstance(metadata, dict):
            raise InvalidChatRequestError("metadata must be an object")
        _collect_metadata(metadata, out)


def _collect_response_format(response_format: object, out: CollectedTexts) -> None:
    where = "response_format"
    if not isinstance(response_format, dict):
        raise InvalidChatRequestError(f"{where} must be an object")
    _reject_unknown(response_format, frozenset({"type", "json_schema"}), where, where)
    if "type" in response_format:
        _check_json(response_format, "type", f"{where}.type", out)
    json_schema = response_format.get("json_schema")
    if isinstance(json_schema, dict):
        _collect_function(json_schema, f"{where}.json_schema", out)
    elif json_schema is not None:
        raise InvalidChatRequestError(f"{where}.json_schema must be an object")


def _collect_function(function: dict[str, Any], where: str, out: CollectedTexts) -> None:
    """A function (or json_schema) definition: ``name`` checked, schemas walked, text masked."""
    for position, key in enumerate(list(function)):
        if key == "format":
            # A custom tool's format: its grammar definition is free text (LAB-1563).
            _collect_tool_format(function, key, f"{where}.format", out)
            continue
        if key in _SCHEMA_STRUCTURAL:
            # Structural values are checked like identifiers, never skipped (LAB-1563).
            _check_json(function, key, _field(where, key, position), out)
            continue
        _check_name(key, _field(where, key, position), out)
        if key == "name":
            _check_identifier(function, key, f"{where}.name", out)
        elif key in ("parameters", "schema"):
            _collect_schema(function, key, f"{where}.{key}", out)
        else:
            # _collect_json also makes number slots for direct numeric leaves (LAB-1563);
            # booleans and null collect nothing there.
            _collect_json(function, key, out, "tools")


def _collect_tool_format(
    container: dict[str, Any] | list[Any], key: Any, where: str, out: CollectedTexts
) -> None:
    """A custom tool's ``format``: a ``grammar.definition`` string at any depth is free text
    and masked; every other leaf (``type``, ``syntax``, numbers) is checked like an
    identifier. A plain-string format (a schema ``format`` at this level) is checked too."""
    value = container[key]
    if isinstance(value, dict):
        for position, (name, sub) in enumerate(list(value.items())):
            at = _field(where, name, position)
            _check_name(name, at, out)
            if name == "definition" and isinstance(sub, str):
                out.slots.append(TextSlot(sub, _setter(value, name), "tools"))
            elif isinstance(sub, dict | list):
                _collect_tool_format(value, name, at, out)
            else:
                _check_json(value, name, at, out)
    elif isinstance(value, list):
        for i in range(len(value)):
            _collect_tool_format(value, i, f"{where}.{i}", out)
    else:
        _check_json(container, key, where, out)


def _collect_schema(
    container: dict[str, Any] | list[Any], key: Any, where: str, out: CollectedTexts
) -> None:
    value = container[key]
    if isinstance(value, str):
        out.slots.append(TextSlot(value, _setter(container, key), "tools"))
    elif (number := _number_text(value)) is not None:
        # A keyword number (maximum, minLength, ...) is structure: checked, never rewritten.
        _check_text(number, where, out)
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
                # Checked like identifiers, never skipped unchecked (LAB-1563).
                _check_json(value, name, at, out)
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
