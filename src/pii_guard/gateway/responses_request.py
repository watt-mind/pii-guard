"""Find every text in an OpenAI **Responses API** request body that must be masked.

The Responses counterpart of :mod:`pii_guard.gateway.request` (Chat Completions), with the same
fail-closed rule (ADR 0006): every key of the body, of an ``input`` item, of a content part and
of a tool definition is masked (free text), checked as an identifier (ids, names, enum-like
settings: personal data in one rejects the request), passed through (numbers, booleans,
provider-signed blobs) or rejected. Unknown keys, item types and content parts the gateway
can't mask are rejected with 400; nothing is forwarded. docs/contracts.md ("Responses API
request fields") has the same table in prose.

What is masked:

- ``instructions``; ``input`` as a string, or every ``input`` item:
  ``message`` (``system``/``developer``/``user``/``assistant``; string content or
  ``input_text``/``output_text``/``refusal`` parts, their ``annotations`` and ``logprobs``),
  ``input_image`` parts with an inline base64 PNG/JPEG ``image_url`` (the visual pipeline, as
  for chat: the masked PNG replaces it and, with placeholder labels, its transcript follows as
  an ``input_text`` part; Muse Code ``--image`` sends these),
  ``function_call.arguments`` (JSON: every string, keys included, re-serialised),
  ``function_call_output.output``, ``custom_tool_call.input`` and its output, and
  ``reasoning`` summaries and reasoning text;
- tool definitions: ``function`` tools (description and JSON-Schema text, as for chat),
  ``namespace`` tools (Muse Code groups its tools in one) and ``custom`` tools;
- ``text.format`` (a JSON Schema for structured output), ``metadata`` and ``client_metadata``
  (Codex) values, and the
  ``user``/``safety_identifier``/``prompt_cache_key`` strings.

``reasoning.encrypted_content`` is forwarded untouched: it is the provider's own encrypted
reasoning from an earlier turn, produced from masked input, and nothing here can read it.

Rejected: remote and ``file_id`` images (never fetched), file and audio parts, hosted tools
(``web_search``, ``file_search``, ``mcp``, ...: they act upstream on data the gateway never
sees), ``item_reference`` items and the server-side state fields ``previous_response_id``,
``conversation`` and ``prompt`` (state kept by the upstream would hold placeholders of another
vault session; send the whole ``input`` with ``store: false``, as Muse Code does).
"""

from __future__ import annotations

from typing import Any

from pii_guard.gateway.request import (
    CollectedTexts,
    InvalidChatRequestError,
    TextSlot,
    UnsupportedContentError,
    _check_json,
    _check_text,
    _collect_arguments,
    _collect_function,
    _collect_image,
    _collect_json,
    _collect_metadata,
    _field,
    _reject_unknown,
    _require_scalars,
    _setter,
    _text_slot,
)

__all__ = ["collect_response_texts"]

#: Top-level fields that hold only numbers, booleans or null.
_TOP_SCALAR = frozenset(
    {
        "background",
        "max_output_tokens",
        "max_tool_calls",
        "parallel_tool_calls",
        "store",
        "stream",
        "temperature",
        "top_logprobs",
        "top_p",
    }
)
#: Top-level enum-like settings: every string in them is checked, never masked.
_TOP_CHECKED = frozenset(
    {"include", "reasoning", "service_tier", "stream_options", "tool_choice", "truncation"}
)
#: Top-level free-text strings that identify the end user or a cache entry: masked.
_TOP_USER_TEXT = ("user", "safety_identifier", "prompt_cache_key")
#: ``client_metadata``: Codex's per-turn ids (session, turn, installation), masked like
#: ``metadata`` (LAB-1331).
_TOP_WALKED = frozenset(
    {"client_metadata", "input", "instructions", "metadata", "model", "text", "tools"}
)
#: Server-side state: refused with an explanation (see the module docstring).
_TOP_STATE = ("previous_response_id", "conversation", "prompt")

_ROLES = frozenset({"system", "developer", "user", "assistant"})
_ITEM_KEYS = {
    "message": frozenset({"type", "role", "content", "id", "status", "phase"}),
    "function_call": frozenset({"type", "id", "call_id", "name", "arguments", "status"}),
    "function_call_output": frozenset({"type", "id", "call_id", "output", "status"}),
    "custom_tool_call": frozenset({"type", "id", "call_id", "name", "input", "status"}),
    "custom_tool_call_output": frozenset({"type", "id", "call_id", "output", "status"}),
    "reasoning": frozenset({"type", "id", "summary", "content", "encrypted_content", "status"}),
}
#: Item fields that are ids or enum-like values: checked as identifiers.
_ITEM_CHECKED = ("id", "call_id", "status", "phase")
#: Text content parts and the key holding their text.
_TEXT_PARTS = {"input_text": "text", "output_text": "text", "refusal": "refusal"}
_PART_KEYS = {
    "input_text": frozenset({"type", "text"}),
    "output_text": frozenset({"type", "text", "annotations", "logprobs"}),
    "refusal": frozenset({"type", "refusal"}),
}
_MEDIA_PARTS = frozenset({"input_file", "input_audio"})
_IMAGE_KEYS = frozenset({"type", "image_url", "detail", "file_id"})
_REASONING_PARTS = {"summary": "summary_text", "content": "reasoning_text"}
_TOOL_TYPES = frozenset({"function", "namespace", "custom"})
_NAMESPACE_KEYS = frozenset({"type", "name", "description", "tools"})
_TEXT_KEYS = frozenset({"format", "verbosity"})


def _validate_response_body(body: object) -> dict[str, Any]:
    if not isinstance(body, dict):
        raise InvalidChatRequestError("request body must be a JSON object")
    if not isinstance(body.get("model"), str) or not body["model"]:
        raise InvalidChatRequestError("model must be a non-empty string")
    for key in _TOP_STATE:
        if body.get(key) is not None:
            raise UnsupportedContentError(
                f"{key}: server-side conversation state is not supported; send the whole "
                "conversation in input (with store: false) so every turn can be masked"
            )
    allowed = (
        _TOP_SCALAR | _TOP_CHECKED | _TOP_WALKED | frozenset(_TOP_USER_TEXT) | frozenset(_TOP_STATE)
    )
    _reject_unknown(body, allowed, "", "request")
    return body


def _collect_top_response_fields(body: dict[str, Any], out: CollectedTexts) -> None:
    instructions = body.get("instructions")
    if isinstance(instructions, str):
        # Muse Code's instructions can quote numbered file lines: same gutters as chat system.
        out.slots.append(_text_slot(body, "instructions", "instructions"))
    elif instructions is not None:
        raise InvalidChatRequestError("instructions must be a string or null")
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


def _collect_response_metadata_fields(body: dict[str, Any], out: CollectedTexts) -> None:
    for key in ("metadata", "client_metadata"):
        metadata = body.get(key)
        if metadata is not None:
            if not isinstance(metadata, dict):
                raise InvalidChatRequestError(f"{key} must be an object")
            _collect_metadata(metadata, out)


def collect_response_texts(body: object) -> CollectedTexts:
    """Every text of a Responses request, as :class:`TextSlot` objects (fail closed)."""
    checked = _validate_response_body(body)
    out = CollectedTexts([], [])
    _collect_input(checked, out)
    _collect_top_response_fields(checked, out)
    _collect_tools(checked, out)
    _collect_text_options(checked, out)
    _collect_response_metadata_fields(checked, out)
    # ``model`` goes upstream verbatim and can't carry a placeholder: checked (LAB-1563).
    _check_text(checked["model"], "model", out)
    return out


# --- input -------------------------------------------------------------------------------


def _collect_input(body: dict[str, Any], out: CollectedTexts) -> None:
    items = body.get("input")
    if isinstance(items, str):
        out.slots.append(TextSlot(items, _setter(body, "input")))
        return
    if not isinstance(items, list) or not items:
        raise InvalidChatRequestError("input must be a string or a non-empty array")
    for index, item in enumerate(items):
        where = f"input.{index}"
        if not isinstance(item, dict):
            raise InvalidChatRequestError(f"{where} must be an object")
        # An "easy" input message has a role and no type.
        item_type = item.get("type", "message" if "role" in item else None)
        allowed = _ITEM_KEYS.get(item_type) if isinstance(item_type, str) else None
        if allowed is None or not isinstance(item_type, str):
            shown = item_type if isinstance(item_type, str) and len(item_type) <= 32 else "unknown"
            raise UnsupportedContentError(
                f"{where}: input items of type {shown!r} are not supported; the gateway forwards "
                "messages, function calls and their outputs, and reasoning items only"
            )
        _reject_unknown(item, allowed, where, f"{item_type} item")
        if "type" in item:
            _check_json(item, "type", f"{where}.type", out)
        for key in _ITEM_CHECKED:
            if item.get(key) is not None:
                _check_json(item, key, f"{where}.{key}", out)
        _collect_item(item, item_type, where, out)


def _collect_item(item: dict[str, Any], item_type: str, where: str, out: CollectedTexts) -> None:
    if item_type == "message":
        _collect_message(item, where, out)
    elif item_type in ("function_call", "custom_tool_call"):
        name = item.get("name")
        if not isinstance(name, str):
            raise InvalidChatRequestError(f"{where}.name must be a string")
        _check_text(name, f"{where}.name", out)
        if item_type == "function_call":
            _collect_arguments(item, where, out)
        else:
            _collect_string(item, "input", where, out, "arguments")
    elif item_type in ("function_call_output", "custom_tool_call_output"):
        _collect_output(item, where, out)
    else:
        _collect_reasoning(item, where, out)


def _collect_message(item: dict[str, Any], where: str, out: CollectedTexts) -> None:
    if item.get("role") not in _ROLES:
        raise InvalidChatRequestError(f"{where}.role must be one of {', '.join(sorted(_ROLES))}")
    content = item.get("content")
    if isinstance(content, str):
        out.slots.append(_text_slot(item, "content", "content"))
    elif isinstance(content, list):
        for i, part in enumerate(content):
            _collect_part(part, f"{where}.content.{i}", out, content)
    else:
        raise InvalidChatRequestError(f"{where}.content must be a string or an array")


def _collect_part(part: object, where: str, out: CollectedTexts, parts: list[Any]) -> None:
    if not isinstance(part, dict):
        raise InvalidChatRequestError(f"{where} must be an object")
    part_type = part.get("type")
    if part_type == "input_image":
        _collect_input_image(part, where, out, parts)
        return
    if part_type in _MEDIA_PARTS:
        raise UnsupportedContentError(
            f"{where}: {part_type} parts are not masked on /v1/responses; send text, or images "
            "inline as input_image data URLs"
        )
    allowed = _PART_KEYS.get(part_type) if isinstance(part_type, str) else None
    if allowed is None or not isinstance(part_type, str):
        shown = part_type if isinstance(part_type, str) and len(part_type) <= 32 else "unknown"
        raise UnsupportedContentError(
            f"{where}: content parts of type {shown!r} are not supported; the gateway masks "
            "text parts only and does not forward what it cannot mask"
        )
    _reject_unknown(part, allowed, where, "content part")
    key = _TEXT_PARTS[part_type]
    value = part.get(key)
    if not isinstance(value, str):
        raise InvalidChatRequestError(f"{where}.{key} must be a string")
    out.slots.append(_text_slot(part, key, "content"))
    for name in ("annotations", "logprobs"):
        if part.get(name) is not None:
            _collect_json(part, name, out, name)


def _collect_input_image(
    part: dict[str, Any], where: str, out: CollectedTexts, parts: list[Any]
) -> None:
    """``{"type": "input_image", "image_url": "data:image/png;base64,...", "detail": ...}``:
    masked by the chat image path (:func:`~pii_guard.gateway.request._collect_image`)."""
    _reject_unknown(part, _IMAGE_KEYS, where, "input_image part")
    if part.get("file_id") is not None:
        raise UnsupportedContentError(
            f"{where}: input_image file_id references are not fetched; send the image inline "
            "as a base64 data URL (data:image/png;base64,...) so it can be masked"
        )
    if "detail" in part:
        _check_json(part, "detail", f"{where}.detail", out)
    if not isinstance(part.get("image_url"), str):
        raise UnsupportedContentError(f"{where}: input_image parts need an inline data URL")
    _collect_image(part, where, out, parts, text_type="input_text")


def _collect_output(item: dict[str, Any], where: str, out: CollectedTexts) -> None:
    """A tool result: a string, or text parts (``input_text`` / ``output_text``)."""
    output = item.get("output")
    if isinstance(output, str):
        out.slots.append(_text_slot(item, "output", "tool"))
    elif isinstance(output, list):
        for i, part in enumerate(output):
            _collect_part(part, f"{where}.output.{i}", out, output)
    else:
        raise InvalidChatRequestError(f"{where}.output must be a string or an array")


def _collect_reasoning(item: dict[str, Any], where: str, out: CollectedTexts) -> None:
    for key, part_type in _REASONING_PARTS.items():
        parts = item.get(key)
        if parts is None:
            continue
        if not isinstance(parts, list):
            raise InvalidChatRequestError(f"{where}.{key} must be an array")
        for i, part in enumerate(parts):
            at = f"{where}.{key}.{i}"
            if not isinstance(part, dict) or part.get("type") != part_type:
                raise UnsupportedContentError(f"{at}: only {part_type!r} parts are supported")
            _reject_unknown(part, frozenset({"type", "text"}), at, "reasoning part")
            text = part.get("text")
            if isinstance(text, str):  # gutters as for chat reasoning (LAB-1583)
                out.slots.append(_text_slot(part, "text", "reasoning"))
            elif text is not None:
                raise InvalidChatRequestError(f"{at}.text must be a string")
    blob = item.get("encrypted_content")
    if blob is not None and not isinstance(blob, str):  # opaque, forwarded untouched
        raise InvalidChatRequestError(f"{where}.encrypted_content must be a string or null")


def _collect_string(
    holder: dict[str, Any], key: str, where: str, out: CollectedTexts, kind: str
) -> None:
    value = holder.get(key)
    if isinstance(value, str):
        out.slots.append(TextSlot(value, _setter(holder, key), kind))
    elif value is not None:
        raise InvalidChatRequestError(f"{where}.{key} must be a string")


# --- tools and output format -------------------------------------------------------------


def _collect_tools(body: dict[str, Any], out: CollectedTexts) -> None:
    tools = body.get("tools")
    if tools is None:
        return
    if not isinstance(tools, list):
        raise InvalidChatRequestError("tools must be an array")
    for index, tool in enumerate(tools):
        _collect_tool(tool, f"tools.{index}", out, nested=False)


def _collect_tool(tool: object, where: str, out: CollectedTexts, *, nested: bool) -> None:
    if not isinstance(tool, dict):
        raise InvalidChatRequestError(f"{where} must be an object")
    tool_type = tool.get("type")
    if tool_type not in _TOOL_TYPES or (nested and tool_type == "namespace"):
        shown = tool_type if isinstance(tool_type, str) and len(tool_type) <= 32 else "unknown"
        raise UnsupportedContentError(
            f"{where}: tools of type {shown!r} are not supported; hosted tools act upstream "
            "on data the gateway never sees (function, custom and namespace tools are)"
        )
    if tool_type != "namespace":
        # name checked, description and JSON-Schema text masked, as for chat (request.py).
        _collect_function(tool, where, out)
        return
    _reject_unknown(tool, _NAMESPACE_KEYS, where, "namespace tool")
    if not isinstance(tool.get("name"), str):
        raise InvalidChatRequestError(f"{where}.name must be a string")
    _check_text(tool["name"], f"{where}.name", out)
    _collect_string(tool, "description", where, out, "tools")
    inner = tool.get("tools")
    if not isinstance(inner, list):
        raise InvalidChatRequestError(f"{where}.tools must be an array")
    for i, sub in enumerate(inner):
        _collect_tool(sub, f"{where}.tools.{i}", out, nested=True)


def _collect_text_options(body: dict[str, Any], out: CollectedTexts) -> None:
    """``text: {format: {type, name, schema, ...}, verbosity}`` (structured output)."""
    text = body.get("text")
    if text is None:
        return
    if not isinstance(text, dict):
        raise InvalidChatRequestError("text must be an object")
    _reject_unknown(text, _TEXT_KEYS, "text", "text")
    if "verbosity" in text:
        _check_json(text, "verbosity", "text.verbosity", out)
    fmt = text.get("format")
    if isinstance(fmt, dict):
        for position, key in enumerate(fmt):
            if key not in ("type", "name", "schema", "description", "strict"):
                raise UnsupportedContentError(
                    f"{_field('text.format', key, position)}: unsupported text format field"
                )
        _collect_function(fmt, "text.format", out)
    elif fmt is not None:
        raise InvalidChatRequestError("text.format must be an object")
