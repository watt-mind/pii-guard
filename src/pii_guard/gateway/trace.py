"""One gateway call as a traffic event (:mod:`pii_guard.observability.traffic`).

:class:`CallTrace` is filled by :class:`~pii_guard.gateway.service.Gateway` as the request
goes through (counts, the masked body, the upstream's answer, timing) and turned into an event
by :meth:`CallTrace.finish`, which publishes it once. Payloads are only kept when the traffic
log is on; originals (the client's request, the restored answer) only at level ``full``.

The event never holds request headers (so no ``Authorization`` or upstream key), and the
session only as its :meth:`~pii_guard.observability.traffic.TrafficLog.session_ref`.

``model`` goes upstream verbatim and is checked like an identifier (LAB-1563), so the event
keeps it only once that check has passed: the outbound re-check ran and found nothing. A
refused, blocked or failed call gets :data:`MODEL_WITHHELD` instead, in ``model`` and in the
``full`` original alike (LAB-1358). The upstream's reported model is kept only when the request
model was and it is model-id shaped.
"""

from __future__ import annotations

import copy
import json
import re
import secrets
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from pii_guard.observability import Observability, RequestTimer
from pii_guard.policy import BlockedEntityError
from pii_guard.types import PiiGuardError

if TYPE_CHECKING:
    from pii_guard.gateway.service import RequestStats

__all__ = ["MODEL_WITHHELD", "CallTrace", "new_request_id"]

#: Stands in for a model name the gateway has not checked (or that is not model-id shaped).
MODEL_WITHHELD = "[withheld]"
#: Model ids as providers write them (``org/name:tag``, ``name@version``); no spaces.
_MODEL_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,127}")
#: An e-mail address hidden in an otherwise id-shaped string.
_EMAIL_RE = re.compile(r"[^@/:\s]+@[^@\s]+\.[A-Za-z]{2,}")


def new_request_id() -> str:
    return "req_" + secrets.token_hex(8)


def _json(raw: bytes | None) -> Any:
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        return f"[not JSON, {len(raw)} bytes]"


def _model_id(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    if _MODEL_ID_RE.fullmatch(value) and not _EMAIL_RE.search(value):
        return value
    return MODEL_WITHHELD


class CallTrace:
    """Collects one call; :meth:`finish` (or :meth:`fail`) emits its event exactly once."""

    def __init__(
        self,
        observability: Observability | None,
        timer: RequestTimer,
        body: object,
    ) -> None:
        self.observability = observability
        self.timer = timer
        self.request_id = new_request_id()
        self.recording = observability is not None and observability.recording
        self.payloads = observability is not None and observability.traffic.enabled
        self.full = observability is not None and observability.traffic.full
        # The client's request, before masking rewrites it in place (``full`` only).
        self.original: Any = copy.deepcopy(body) if self.full else None
        self.model = body.get("model") if isinstance(body, Mapping) else None
        self.mode: str | None = None
        self.language: str | None = None
        self.stream = bool(body.get("stream")) if isinstance(body, Mapping) else False
        self.session_id: str | None = None
        self.session_new = False
        # Which step chose the session (header|path|prompt_cache_key|default), LAB-1286.
        self.session_source: str | None = None
        self.stats: RequestStats | None = None
        self.masked_request: bytes | None = None
        self.upstream_body: bytes | None = None
        self.answer: Any = None  # restored, ``full`` only
        self.stream_masked: dict[int, str] | None = None
        self.stream_restored: dict[int, str] | None = None
        self.stream_chunks = 0
        self.usage: Any = None
        self.streaming = False  # the event is emitted when the stream ends
        self._done = False

    def __repr__(self) -> str:
        return f"CallTrace({self.request_id}, recording={self.recording})"

    def scan_usage(self, data: str) -> None:
        """Pick ``usage`` out of a stream chunk (it comes in the last one, if asked for)."""
        if self.recording and '"usage"' in data:
            try:
                usage = json.loads(data).get("usage")
            except (ValueError, AttributeError):
                return
            if isinstance(usage, dict):
                self.usage = usage

    def fail(self, exc: BaseException) -> None:
        from pii_guard.gateway.outbound import OutboundCheckFailedError

        if isinstance(exc, PiiGuardError):
            blocked = isinstance(exc, BlockedEntityError | OutboundCheckFailedError)
            outcome = "blocked" if blocked else "refused"
            error = {"code": exc.code, "status": exc.status_code}
            if isinstance(exc, BlockedEntityError):
                error["entity_types"] = {t.value: n for t, n in sorted(exc.counts.items())}
            elif isinstance(exc, OutboundCheckFailedError):
                error["entity_types"] = dict(exc.counts)
        else:
            outcome = "error"
            error = {"code": type(exc).__name__, "status": 500}
        self.finish(outcome=outcome, error=error)

    def finish(self, outcome: str = "ok", error: dict[str, Any] | None = None) -> None:
        if self._done:
            return
        self._done = True
        self.timer.finish()
        obs = self.observability
        if obs is None or not self.recording:
            return
        stats = self.stats
        if outcome == "ok" and stats is not None and (stats.upstream_status or 0) >= 400:
            outcome = "upstream_error"
            error = {"code": "upstream_error", "status": stats.upstream_status}
        # The model passed its identifier check only if the outbound re-check ran clean.
        outbound = getattr(stats, "outbound", None)
        model_checked = outbound is not None and not outbound.hits
        if not isinstance(self.model, str):
            model = None
        elif model_checked:
            model = _model_id(self.model)
        else:
            model = MODEL_WITHHELD
        detectors = sorted((stats.detector_ms if stats else {}).keys())
        if stats is not None and stats.images:
            detectors.append("visual")
        self.timer.add_detectors(dict(stats.detector_ms) if stats else {})
        if stats is not None and stats.image_ms:
            self.timer.add_detectors({"visual": stats.image_ms})
        event: dict[str, Any] = {
            "id": self.request_id,
            "time": datetime.now(UTC).isoformat(timespec="milliseconds"),
            "level": obs.traffic.level.value,
            "outcome": outcome,
            "error": error,
            "mode": self.mode,
            "language": self.language,
            "stream": self.stream,
            "model": model,
            "session_ref": (
                obs.traffic.session_ref(self.session_id) if self.session_id is not None else None
            ),
            "session_new": self.session_new,
            "session_source": self.session_source,
            "detectors": detectors,
            "entities": _entities(stats),
            "outbound_check": (
                stats.outbound.event() if stats is not None and stats.outbound else None
            ),
            "cache": (
                {"hits": stats.cache_hits, "misses": stats.cache_misses, "seeded": stats.seeded}
                if stats
                else None
            ),
            "upstream": {
                "status": stats.upstream_status if stats else None,
                "model": None,
                "unresolved_placeholders": stats.unresolved if stats else 0,
            },
            "usage": None,
            "timing": self.timer.breakdown(),
            "request": None,
            "response": None,
        }
        upstream_answer = _json(self.upstream_body) if self.upstream_body is not None else None
        answer = self.answer
        if isinstance(upstream_answer, dict):
            reported = _model_id(upstream_answer.get("model"))
            if reported is not None and not model_checked:
                reported = MODEL_WITHHELD
            event["upstream"]["model"] = reported
            if reported is not None and reported != upstream_answer.get("model"):
                upstream_answer = {**upstream_answer, "model": reported}
                if isinstance(answer, dict) and "model" in answer:
                    answer = {**answer, "model": reported}
            self.usage = upstream_answer.get("usage", self.usage)
        if isinstance(self.usage, dict):
            event["usage"] = {
                k: v
                for k, v in self.usage.items()
                if isinstance(v, int) and not isinstance(v, bool)
            }
        if self.payloads:
            request: dict[str, Any] = {"masked": _json(self.masked_request)}
            response: dict[str, Any] = {}
            if self.upstream_body is not None:
                response["masked"] = upstream_answer
            elif self.stream_masked is not None:
                response["masked"] = {"content": _by_choice(self.stream_masked)}
                response["chunks"] = self.stream_chunks
            if self.full:
                original = self.original
                if isinstance(original, dict) and model is not None and model != self.model:
                    original = {**original, "model": model}
                request["original"] = original
                if answer is not None:
                    response["unmasked"] = answer
                elif self.stream_restored is not None:
                    response["unmasked"] = {"content": _by_choice(self.stream_restored)}
            event["request"] = obs.scrub(request)
            event["response"] = obs.scrub(response) if response else None
        obs.record(event)


def _by_choice(content: Mapping[int, str]) -> dict[str, str]:
    return {str(k): v for k, v in sorted(content.items())}


def _entities(stats: RequestStats | None) -> dict[str, Any] | None:
    if stats is None:
        return None
    out: dict[str, Any] = {
        "detected": dict(sorted(stats.spans.items())),
        "masked": dict(sorted((k, v) for k, v in stats.masked.items() if v)),
        "texts": stats.texts,
    }
    if stats.images:
        out["images"] = {
            "count": stats.images,
            "masked": dict(sorted(stats.image_masked.items())),
            "kept": dict(sorted(stats.image_kept.items())),
            "ocr": stats.image_ocr,
        }
    return out
