"""What one request actually sent upstream and got back, for hosted settlement (LAB-1662).

Hosted admission reserves a conservative bound before any work starts. Once the request has
finished, the hosted middleware settles that reservation down to what this meter saw: whether
a masked payload was forwarded, its size, and the usage the upstream reported. The meter only
counts; it never holds payload text, so it carries no PII.

A request outside hosted admission has no meter and every hook is a no-op.
"""

from __future__ import annotations

import json
from contextvars import ContextVar
from dataclasses import dataclass


@dataclass(slots=True)
class UpstreamMeter:
    #: The masked payload passed its admitted bound and is about to go upstream.
    forwarded: bool = False
    #: Bytes of that masked payload, without the inline images charged at a fixed price.
    payload_bytes: int = 0
    #: Token usage the upstream reported, or None when it reported none (aborted stream,
    #: error answer, a chat stream without ``include_usage``).
    input_tokens: int | None = None
    output_tokens: int | None = None
    #: The hosted middleware asked the upstream for a usage chunk the client did not ask
    #: for: the gateway takes it out of the client's stream.
    strip_usage: bool = False


UPSTREAM_METER: ContextVar[UpstreamMeter | None] = ContextVar(
    "pii_guard_upstream_meter", default=None
)


def _count(value: object) -> int | None:
    return value if type(value) is int and value >= 0 else None


def record_payload(payload_bytes: int) -> None:
    meter = UPSTREAM_METER.get()
    if meter is not None:
        meter.forwarded = True
        meter.payload_bytes = max(0, payload_bytes)


def record_usage(usage: object) -> None:
    """Chat (``prompt_tokens``/``completion_tokens``) or Responses (``input_tokens``/
    ``output_tokens``) usage; reasoning tokens are already inside the output count."""
    meter = UPSTREAM_METER.get()
    if meter is None or not isinstance(usage, dict):
        return
    for input_key, output_key in (
        ("prompt_tokens", "completion_tokens"),
        ("input_tokens", "output_tokens"),
    ):
        tokens_in, tokens_out = _count(usage.get(input_key)), _count(usage.get(output_key))
        if tokens_in is not None and tokens_out is not None:
            meter.input_tokens, meter.output_tokens = tokens_in, tokens_out
            return


def scan_usage(data: str, *, nested: bool = False) -> None:
    """Usage from one SSE ``data`` payload: top level for chat chunks, inside ``response``
    for Responses events (``response.completed``)."""
    if UPSTREAM_METER.get() is None or '"usage"' not in data:
        return
    try:
        parsed = json.loads(data)
    except ValueError:
        return
    if not isinstance(parsed, dict):
        return
    if nested:
        parsed = parsed.get("response")
        if not isinstance(parsed, dict):
            return
    record_usage(parsed.get("usage"))


def client_chunk(data: str) -> str | None:
    """The chat stream chunk the client sees, after :func:`scan_usage` has read it.

    When usage was requested for settlement only, a usage-only chunk (``choices: []``) is
    dropped and a ``usage`` riding on a content chunk is removed, so the client's stream
    keeps the shape it asked for. Anything else passes through byte for byte.
    """
    meter = UPSTREAM_METER.get()
    if meter is None or not meter.strip_usage or '"usage"' not in data:
        return data
    try:
        parsed = json.loads(data)
    except ValueError:
        return data
    if not isinstance(parsed, dict) or parsed.get("usage") is None:
        return data
    if parsed.get("choices") == []:
        return None
    del parsed["usage"]
    return json.dumps(parsed, ensure_ascii=False, separators=(",", ":"))
