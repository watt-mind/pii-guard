"""Find every text in an Anthropic **Messages API** request body that must be masked.

The Messages counterpart of :mod:`pii_guard.gateway.request` (Chat Completions) and
:mod:`pii_guard.gateway.responses_request` (Responses), with the same fail-closed rule
(ADR 0006): every key of the body, of a message, of a content block and of a tool definition
is masked (free text), checked as an identifier (ids, names, enum-like settings: personal data
in one rejects the request), passed through (numbers, booleans, provider-signed blobs) or
rejected. Unknown keys, block types and tools the gateway can't mask are rejected with 400;
nothing is forwarded. docs/contracts.md ("Messages API request fields") has the same table in
prose.

What is masked:

- ``system`` (a string, or ``text`` blocks), ``stop_sequences`` and ``metadata.user_id``;
- every ``messages`` item (``user``/``assistant``; string content or blocks):
  ``text`` blocks; ``image`` blocks with an inline base64 PNG/JPEG ``source`` (the visual
  pipeline, as for chat: the masked PNG replaces it and, with placeholder labels, its
  transcript follows as a ``text`` block); ``tool_use.input`` (a JSON object: every string,
  keys included, and long numbers, as chat tool-call arguments); ``tool_result.content`` (a
  string, or ``text``/``image`` blocks); and ``thinking`` text;
- tool definitions (client tools: ``name`` checked, ``description`` masked, ``input_schema``
  walked as a JSON Schema, as for chat).

``thinking.signature`` and ``redacted_thinking.data`` are forwarded untouched: they are the
provider's own signed or encrypted reasoning from an earlier turn, produced from masked input.
The gateway requires the exact blob to have been observed upstream in the same vault session.
The masked thinking text is the text the model wrote (placeholders and all), so its signature
still matches.

Rejected: remote and file images (never fetched), ``document``, ``search_result`` and other
blocks the gateway can't mask, server tools (``web_search``, ``code_execution``, ...: they act
upstream on data the gateway never sees), ``mcp_servers`` and ``container`` (state and tools
kept upstream).
"""

from __future__ import annotations

import base64
import binascii
from typing import Any, cast

from pii_guard.gateway.request import (
    _IMAGE_SIGNATURES,
    CollectedTexts,
    ImageSlot,
    InvalidChatRequestError,
    OpaqueBlob,
    TextSlot,
    UnsupportedContentError,
    _check_json,
    _check_text,
    _collect_json,
    _collect_schema,
    _collect_tool_output,
    _reject_unknown,
    _require_scalars,
    _setter,
    _text_slot,
    remove_item,
)

__all__ = ["collect_message_texts"]

#: Top-level fields that hold only numbers, booleans or null.
_TOP_SCALAR = frozenset({"max_tokens", "stream", "temperature", "top_k", "top_p"})
#: Top-level enum-like settings: every string in them is checked, never masked.
_TOP_CHECKED = frozenset(
    {"context_management", "service_tier", "thinking", "tool_choice", "output_config"}
)
_TOP_WALKED = frozenset({"messages", "metadata", "model", "stop_sequences", "system", "tools"})
#: State or tools kept upstream: refused with an explanation.
_TOP_UPSTREAM = ("mcp_servers", "container")

_ROLES = frozenset({"user", "assistant"})
_MESSAGE_KEYS = frozenset({"role", "content"})
_CACHE = "cache_control"
_BLOCK_KEYS = {
    "text": frozenset({"type", "text", _CACHE, "citations"}),
    "image": frozenset({"type", "source", _CACHE}),
    "tool_use": frozenset({"type", "id", "name", "input", _CACHE}),
    "tool_result": frozenset({"type", "tool_use_id", "content", "is_error", _CACHE}),
    "thinking": frozenset({"type", "thinking", "signature"}),
    "redacted_thinking": frozenset({"type", "data"}),
}
#: Blocks allowed inside ``tool_result.content``.
_RESULT_BLOCKS = frozenset({"text", "image"})
_SOURCE_KEYS = frozenset({"type", "media_type", "data"})
_MEDIA_TYPES = frozenset({"image/png", "image/jpeg"})
_TOOL_KEYS = frozenset(
    {"type", "name", "description", "input_schema", _CACHE, "defer_loading", "strict"}
)
_METADATA_KEYS = frozenset({"user_id"})


def collect_message_texts(body: object) -> CollectedTexts:
    """Every text of a Messages request, as :class:`TextSlot` objects (fail closed).

    ``POST /v1/messages/count_tokens`` takes the same body without ``max_tokens``/``stream``:
    this walks it too."""
    out = CollectedTexts([], [])
    out.check_structure(body)
    if not isinstance(body, dict):
        raise InvalidChatRequestError("request body must be a JSON object")
    if not isinstance(body.get("model"), str) or not body["model"]:
        raise InvalidChatRequestError("model must be a non-empty string")
    for key in _TOP_UPSTREAM:
        if body.get(key) is not None:
            raise UnsupportedContentError(
                f"{key}: tools and state kept by the provider act on data the gateway never "
                "sees; send client tools (with input_schema) and the whole conversation instead"
            )
    allowed = _TOP_SCALAR | _TOP_CHECKED | _TOP_WALKED | frozenset(_TOP_UPSTREAM)
    _reject_unknown(body, allowed, "", "request")
    _collect_messages(body, out)
    _collect_system(body, out)
    for key in _TOP_SCALAR:
        if key in body:
            _require_scalars(body[key], key)
    for key in _TOP_CHECKED:
        if key in body:
            _check_json(body, key, key, out)
    _collect_stop_sequences(body, out)
    _collect_metadata(body, out)
    _collect_tools(body, out)
    # ``model`` goes upstream verbatim and can't carry a placeholder: checked (LAB-1563).
    _check_text(body["model"], "model", out)
    return out


# --- system, stop sequences, metadata ----------------------------------------------------


def _collect_system(body: dict[str, Any], out: CollectedTexts) -> None:
    system = body.get("system")
    if system is None:
        return
    if isinstance(system, str):
        out.slots.append(_text_slot(body, "system", "system"))
        return
    if not isinstance(system, list):
        raise InvalidChatRequestError("system must be a string or an array of text blocks")
    for i, block in enumerate(system):
        where = f"system.{i}"
        if not isinstance(block, dict) or block.get("type") != "text":
            raise UnsupportedContentError(f"{where}: only text blocks are supported in system")
        _collect_text_block(block, where, out, "system")


def _collect_stop_sequences(body: dict[str, Any], out: CollectedTexts) -> None:
    stops = body.get("stop_sequences")
    if stops is None:
        return
    if not isinstance(stops, list):
        raise InvalidChatRequestError("stop_sequences must be an array of strings")
    for i, stop in enumerate(stops):
        if not isinstance(stop, str):
            raise InvalidChatRequestError(f"stop_sequences.{i} must be a string")
        out.slots.append(TextSlot(stop, _setter(stops, i), "stop"))


def _collect_metadata(body: dict[str, Any], out: CollectedTexts) -> None:
    """``metadata: {user_id}``: free text (Claude Code sends a JSON string of its ids)."""
    metadata = body.get("metadata")
    if metadata is None:
        return
    if not isinstance(metadata, dict):
        raise InvalidChatRequestError("metadata must be an object")
    _reject_unknown(metadata, _METADATA_KEYS, "metadata", "metadata")
    user_id = metadata.get("user_id")
    if isinstance(user_id, str):
        out.slots.append(TextSlot(user_id, _setter(metadata, "user_id"), "user"))
    elif user_id is not None:
        raise InvalidChatRequestError("metadata.user_id must be a string or null")


# --- messages and content blocks ---------------------------------------------------------


def _collect_messages(body: dict[str, Any], out: CollectedTexts) -> None:
    messages = body.get("messages")
    if not isinstance(messages, list) or not messages:
        raise InvalidChatRequestError("messages must be a non-empty array")
    for index, message in enumerate(messages):
        where = f"messages.{index}"
        if not isinstance(message, dict):
            raise InvalidChatRequestError(f"{where} must be an object")
        _reject_unknown(message, _MESSAGE_KEYS, where, "message")
        if message.get("role") not in _ROLES:
            raise InvalidChatRequestError(f"{where}.role must be one of assistant, user")
        content = message.get("content")
        if isinstance(content, str):
            out.slots.append(_text_slot(message, "content", "content"))
        elif isinstance(content, list):
            for i, block in enumerate(content):
                _collect_block(block, f"{where}.content.{i}", out, content, _BLOCK_KEYS)
        else:
            raise InvalidChatRequestError(f"{where}.content must be a string or an array")


def _block_type(
    block: object, where: str, allowed: dict[str, frozenset[str]] | frozenset[str]
) -> str:
    if not isinstance(block, dict):
        raise InvalidChatRequestError(f"{where} must be an object")
    block_type = block.get("type")
    if not isinstance(block_type, str) or block_type not in allowed:
        raise UnsupportedContentError(
            f"{where}: unsupported content block type; the gateway masks "
            "text, inline images, tool use and results, and thinking, and does not forward "
            "what it cannot mask"
        )
    return block_type


def _collect_block(
    block: object,
    where: str,
    out: CollectedTexts,
    content: list[Any],
    allowed: dict[str, frozenset[str]] | frozenset[str],
    text_kind: str = "content",
) -> None:
    block_type = _block_type(block, where, allowed)
    block = cast(dict[str, Any], block)
    _reject_unknown(block, _BLOCK_KEYS[block_type], where, f"{block_type} block")
    if _CACHE in block:
        _check_json(block, _CACHE, f"{where}.{_CACHE}", out)
    if block_type == "text":
        _collect_text_block(block, where, out, text_kind)
    elif block_type == "image":
        _collect_image_block(block, where, out, content)
    elif block_type == "tool_use":
        for key in ("id", "name"):
            if not isinstance(block.get(key), str):
                raise InvalidChatRequestError(f"{where}.{key} must be a string")
            _check_text(block[key], f"{where}.{key}", out)
        if not isinstance(block.get("input"), dict):
            raise InvalidChatRequestError(f"{where}.input must be an object")
        # Every string (keys too) and long number masked, as chat tool-call arguments.
        _collect_json(block, "input", out, "arguments")
    elif block_type == "tool_result":
        _collect_tool_result(block, where, out)
    elif block_type == "thinking":
        thinking = block.get("thinking")
        if not isinstance(thinking, str):
            raise InvalidChatRequestError(f"{where}.thinking must be a string")
        out.slots.append(_text_slot(block, "thinking", "reasoning"))
        _opaque(block, "signature", where, out, content)
    else:  # redacted_thinking: the provider's encrypted reasoning, forwarded as is
        _opaque(block, "data", where, out, content)


def _opaque(
    block: dict[str, Any], key: str, where: str, out: CollectedTexts, content: list[Any]
) -> None:
    value = block.get(key)
    if value is not None and not isinstance(value, str):
        raise InvalidChatRequestError(f"{where}.{key} must be a string")
    if isinstance(value, str):
        # Unverified, the whole block is dropped: signed thinking text is not forwarded alone.
        out.opaque.append(OpaqueBlob(key, value, remove_item(content, block)))


def _collect_text_block(block: dict[str, Any], where: str, out: CollectedTexts, kind: str) -> None:
    if kind == "system":  # content blocks are checked in _collect_block
        _reject_unknown(block, _BLOCK_KEYS["text"], where, "text block")
        if _CACHE in block:
            _check_json(block, _CACHE, f"{where}.{_CACHE}", out)
    if not isinstance(block.get("text"), str):
        raise InvalidChatRequestError(f"{where}.text must be a string")
    citations = block.get("citations")
    if citations not in (None, []):
        raise UnsupportedContentError(
            f"{where}.citations: citations point into documents the gateway does not forward"
        )
    if kind == "tool":
        _collect_tool_output(block, "text", out)
    else:
        out.slots.append(_text_slot(block, "text", kind))


def _collect_tool_result(block: dict[str, Any], where: str, out: CollectedTexts) -> None:
    if not isinstance(block.get("tool_use_id"), str):
        raise InvalidChatRequestError(f"{where}.tool_use_id must be a string")
    _check_text(block["tool_use_id"], f"{where}.tool_use_id", out)
    if "is_error" in block:
        _require_scalars(block["is_error"], f"{where}.is_error")
    content = block.get("content")
    if content is None:
        return
    if isinstance(content, str):
        _collect_tool_output(block, "content", out)
        return
    if not isinstance(content, list):
        raise InvalidChatRequestError(f"{where}.content must be a string or an array")
    for i, inner in enumerate(content):
        _collect_block(inner, f"{where}.content.{i}", out, content, _RESULT_BLOCKS, "tool")


def _collect_image_block(
    block: dict[str, Any], where: str, out: CollectedTexts, content: list[Any]
) -> None:
    """``{"type": "image", "source": {"type": "base64", "media_type", "data"}}``: masked by
    the visual pipeline; the masked PNG goes back as a base64 source."""
    source = block.get("source")
    if not isinstance(source, dict) or source.get("type") != "base64":
        raise UnsupportedContentError(
            f"{where}: only inline base64 images can be masked; URL and file images are "
            "never fetched"
        )
    _reject_unknown(source, _SOURCE_KEYS, f"{where}.source", "image source")
    if source.get("media_type") not in _MEDIA_TYPES:
        raise UnsupportedContentError(f"{where}: only PNG and JPEG images can be masked")
    data = source.get("data")
    if not isinstance(data, str):
        raise InvalidChatRequestError(f"{where}.source.data must be a string")
    try:
        raw = base64.b64decode("".join(data.split()), validate=True)
    except (binascii.Error, ValueError):
        raise InvalidChatRequestError(f"{where}: image data is not valid base64") from None
    if not raw.startswith(_IMAGE_SIGNATURES):
        raise UnsupportedContentError(f"{where}: the inline image is not a PNG or JPEG image")

    def write(masked_url: str) -> None:
        # The image pipeline writes a ``data:image/png;base64,...`` URL.
        head, _, payload = masked_url.partition(";base64,")
        block["source"] = {"type": "base64", "media_type": head[5:], "data": payload}

    def annotate_with(text: str) -> None:
        def insert() -> None:
            index = next(i for i, b in enumerate(content) if b is block)
            content.insert(index + 1, {"type": "text", "text": text})

        out.finalizers.append(insert)

    out.images.append(ImageSlot(raw, write, where, annotate_with))


# --- tools -------------------------------------------------------------------------------


def _collect_one_tool(tool: Any, where: str, out: CollectedTexts) -> None:
    if not isinstance(tool, dict):
        raise InvalidChatRequestError(f"{where} must be an object")
    tool_type = tool.get("type", "custom")
    if tool_type != "custom":
        raise UnsupportedContentError(
            f"{where}: unsupported tool type; server tools act upstream "
            "on data the gateway never sees (client tools with an input_schema are)"
        )
    _reject_unknown(tool, _TOOL_KEYS, where, "tool")
    if not isinstance(tool.get("name"), str):
        raise InvalidChatRequestError(f"{where}.name must be a string")
    _check_text(tool["name"], f"{where}.name", out)
    description = tool.get("description")
    if isinstance(description, str):
        out.slots.append(TextSlot(description, _setter(tool, "description"), "tools"))
    elif description is not None:
        raise InvalidChatRequestError(f"{where}.description must be a string")
    if not isinstance(tool.get("input_schema"), dict):
        raise InvalidChatRequestError(f"{where}.input_schema must be an object")
    _collect_schema(tool, "input_schema", f"{where}.input_schema", out)
    for key in ("defer_loading", "strict"):
        if key in tool:
            _require_scalars(tool[key], f"{where}.{key}")
    if _CACHE in tool:
        _check_json(tool, _CACHE, f"{where}.{_CACHE}", out)


def _collect_tools(body: dict[str, Any], out: CollectedTexts) -> None:
    tools = body.get("tools")
    if tools is None:
        return
    if not isinstance(tools, list):
        raise InvalidChatRequestError("tools must be an array")
    for index, tool in enumerate(tools):
        _collect_one_tool(tool, f"tools.{index}", out)
