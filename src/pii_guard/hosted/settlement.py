"""Hosted admission settlement and provider-billed tool inspection."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from pii_guard.gateway.meter import UpstreamMeter
from pii_guard.hosted.quotas import Reservation

__all__ = [
    "MAX_TOOL_DEFINITIONS",
    "_ALLOWED_TOOLS_CHOICE",
    "_CLIENT_TOOL_CHOICES",
    "_CLIENT_TOOL_TYPES",
    "_NAMESPACE_TOOL_TYPE",
    "_NestedNamespaceError",
    "_Settlement",
    "_ToolWalkLimitError",
    "_classify_tool_entry",
    "_provider_billed_tools",
    "_provider_tool_choice",
    "_walk_tools",
    "settled_tokens",
    "settlement_logger",
]

settlement_logger = logging.getLogger("pii_guard.hosted.settlement")


@dataclass(slots=True)
class _Settlement:
    """One paid admission, settled once its response has closed (LAB-1662)."""

    request_id: str
    route: str
    user: str
    reservation: Reservation
    input_tokens: int
    output_tokens: int
    #: The durable sponsored ledger holds a charge for this request.
    durable: bool
    #: Inline images: the input reservation is a fixed provider price, not payload bytes.
    fixed_input: bool
    meter: UpstreamMeter


def settled_tokens(
    reserved_input: int, reserved_output: int, meter: UpstreamMeter, *, fixed_input: bool
) -> tuple[int, int, str]:
    """The (input, output) tokens a finished request is settled to, and how they were found.

    Never above the reservation. No upstream call: nothing. Reported usage: that usage.
    Otherwise (an aborted stream, an error answer, a timeout or transport error after the
    send) the masked payload's bytes as input (a byte-level tokenizer never emits more tokens
    than bytes, so this never underestimates the real input) and the full output reservation:
    muse-spark-1.3 bills hidden reasoning inside its output tokens and streams nothing for
    it, so no output seen is no evidence of no output billed.
    """
    if not meter.forwarded:
        return 0, 0, "no_upstream"
    if meter.input_tokens is not None and meter.output_tokens is not None:
        tokens_in, tokens_out, outcome = meter.input_tokens, meter.output_tokens, "usage"
    else:
        tokens_in, tokens_out, outcome = meter.payload_bytes, reserved_output, "estimated"
    if fixed_input:
        tokens_in = reserved_input
    return min(tokens_in, reserved_input), min(tokens_out, reserved_output), outcome


# Tool types a client executes itself; any other type (web search, file search, code
# interpreter, MCP) runs and bills at the provider, outside the reserved token usage.
_CLIENT_TOOL_TYPES = frozenset({"function", "custom"})
# Responses API only: a ``namespace`` groups client tools under one name (Codex's
# ``multi_agent_v1``, Muse Code's ``muse``, LAB-1658). It is client-side only when every tool
# it holds is; the upstream (api.meta.ai) takes it as is and calls the tools
# ``<namespace>.<name>``, so nothing is flattened. Namespaces appear only in the top-level
# array: masking refuses a nested one after admission, so it is refused here first (LAB-1659).
_NAMESPACE_TOOL_TYPE = "namespace"
# ``tool_choice`` strings and object types that only steer client tools; any other object
# (``{"type": "web_search_preview"}``, ``{"type": "mcp", ...}``) asks for a provider tool.
_CLIENT_TOOL_CHOICES = frozenset({"auto", "none", "required"})
_ALLOWED_TOOLS_CHOICE = "allowed_tools"
# Bound on the tool walk: tool definitions counted across both levels. Clients send a few
# dozen; past the bound the request is refused rather than walked.
MAX_TOOL_DEFINITIONS = 512


class _ToolWalkLimitError(Exception):
    """The tool array counts past the walk bound."""


class _NestedNamespaceError(Exception):
    """A namespace tool holds another namespace."""


def _provider_tool_choice(choice: Any) -> bool:
    """Whether ``tool_choice`` names anything but a client tool or a plain mode."""
    if isinstance(choice, str):
        return choice not in _CLIENT_TOOL_CHOICES
    if not isinstance(choice, dict):
        return True
    choice_type = choice.get("type")
    if not isinstance(choice_type, str):
        return True
    if choice_type in _CLIENT_TOOL_TYPES:
        return False
    if choice_type != _ALLOWED_TOOLS_CHOICE:
        return True
    allowed = choice.get("tools")
    if not isinstance(allowed, list):
        return True
    return not all(
        isinstance(entry, dict)
        and isinstance(entry.get("type"), str)
        and entry["type"] in _CLIENT_TOOL_TYPES
        for entry in allowed
    )


def _classify_tool_entry(
    tool: Any, *, namespaces: bool, nested: bool
) -> tuple[bool, list[Any] | None]:
    """Classify one tool entry as ``(is_provider_tool, namespace_children)``."""
    if not isinstance(tool, dict):
        return True, None
    tool_type = tool.get("type", "function")
    if not isinstance(tool_type, str):
        return True, None
    if tool_type in _CLIENT_TOOL_TYPES:
        return False, None
    if not namespaces or tool_type != _NAMESPACE_TOOL_TYPE:
        return True, None
    if nested:
        raise _NestedNamespaceError
    inner = tool.get("tools")
    if not isinstance(inner, list):
        return True, None
    return False, inner


def _walk_tools(
    entries: list[Any], *, namespaces: bool, nested: bool = False, seen: int = 0
) -> tuple[bool, int]:
    """Walk tool definitions up to :data:`MAX_TOOL_DEFINITIONS`."""
    for tool in entries:
        seen += 1
        if seen > MAX_TOOL_DEFINITIONS:
            raise _ToolWalkLimitError
        is_provider, children = _classify_tool_entry(tool, namespaces=namespaces, nested=nested)
        if is_provider:
            return True, seen
        if children is not None:
            child_provider, seen = _walk_tools(
                children, namespaces=namespaces, nested=True, seen=seen
            )
            if child_provider:
                return True, seen
    return False, seen


def _provider_billed_tools(body: dict[str, Any], *, namespaces: bool = False) -> bool:
    """Whether a chat or Responses body asks the provider for separately billed tool work.

    ``namespaces`` (Responses API): accept top-level ``namespace`` tools whose tools are all
    client-side. Raises :class:`_NestedNamespaceError` for a namespace inside a namespace and
    :class:`_ToolWalkLimitError` past the count bound.
    """
    if "web_search_options" in body:
        return True
    if "tool_choice" in body and _provider_tool_choice(body["tool_choice"]):
        return True
    tools = body.get("tools")
    if tools is None:
        return False
    if not isinstance(tools, list):
        return True
    is_provider, _ = _walk_tools(tools, namespaces=namespaces)
    return is_provider
