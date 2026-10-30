"""What one request actually sent upstream and got back, for hosted settlement (LAB-1662).

Hosted admission reserves a conservative bound before any work starts. Once the request has
finished, the hosted middleware settles that reservation down to what this meter saw: the
masked payload that was forwarded, the bytes the upstream returned and the usage it reported.
The meter only counts; it never holds payload text, so it carries no PII.

A request outside hosted admission has no meter and every hook is a no-op.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

import httpx


@dataclass(slots=True)
class UpstreamMeter:
    #: The masked payload passed its admitted bound and is about to go upstream.
    forwarded: bool = False
    #: Bytes of that masked payload, without the inline images charged at a fixed price.
    payload_bytes: int = 0
    #: Raw bytes the upstream returned (status line excluded), stream or whole body.
    received_bytes: int = 0
    #: Token usage the upstream reported, or None when it reported none (aborted stream,
    #: error answer, a chat stream without ``include_usage``).
    input_tokens: int | None = None
    output_tokens: int | None = None


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


class MeteredStream(httpx.AsyncByteStream):
    """Count the upstream's raw response bytes as they are read."""

    def __init__(self, stream: Any, meter: UpstreamMeter) -> None:
        self._stream, self._meter = stream, meter

    async def __aiter__(self) -> AsyncIterator[bytes]:
        async for chunk in self._stream:
            self._meter.received_bytes += len(chunk)
            yield chunk

    async def aclose(self) -> None:
        await self._stream.aclose()


def meter_response(response: httpx.Response) -> None:
    """Attach the current request's meter (if any) to an upstream response."""
    meter = UPSTREAM_METER.get()
    if meter is None:
        return
    if response.is_stream_consumed:
        meter.received_bytes += len(response.content)
    else:
        response.stream = MeteredStream(response.stream, meter)
