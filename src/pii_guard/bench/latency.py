"""``pii-guard bench latency``: what the gateway adds to an LLM call, per stage and mode.

The benchmark starts two local HTTP servers on free loopback ports -- the mock upstream with a
fixed delay (:mod:`pii_guard.bench.mock_upstream`) and the pii-guard API pointing at it -- and
sends a fixed fictional corpus (:data:`CORPUS`) through ``POST /v1/chat/completions``: N
requests per cell, for every combination of mode (``fast``, ``audit``), concurrency (1, 8)
and streaming (off, on). Each request opens a new session (a fresh ``/s/<session>/v1`` URL),
so nothing is served from the detection cache.

Per request it keeps the gateway's own timing (:class:`~pii_guard.observability.RequestTimer`:
stages, per-detector time, ``overhead = total - upstream - client``, added time to first token)
and the client-side wall time; per cell it reports p50 / p95 / p99 / mean. Because the upstream
is a fixed sleep, the overhead is pii-guard's work and nothing else: parsing, detection, masking,
the HTTP hop to the upstream and back, unmasking. With ``--record SLUG`` the result is written
as run records (``kind: latency``, one per mode) in ``eval/results/runs/`` and the benchmark
report is regenerated.

Audit mode calls the configured LLM detector (``PII_GUARD_LLM_DETECTOR_*``) once per
request: keep ``--audit-requests`` small on a paid endpoint, and the corpus is fictional.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import platform
import secrets
import socket
import subprocess
import threading
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any

import httpx

from pii_guard import __version__
from pii_guard.bench.mock_upstream import create_mock_upstream
from pii_guard.eval import stats
from pii_guard.observability import Observability, ObservabilitySettings, TrafficLevel
from pii_guard.observability.timing import STAGES

__all__ = [
    "CORPUS",
    "CellResult",
    "build_records",
    "percentiles",
    "run_benchmark",
]

#: The fixed fictional corpus: one user message per request, cycled in order.
CORPUS: tuple[tuple[str, str], ...] = (
    (
        "hu",
        "Szia! Teszt Elek vagyok, e-mail: teszt.elek@example.com, telefon: +36 30 123 4567. "
        "Kérlek, utald a díjat a HU42 1177 3016 1111 1018 0000 0000 számlára.",
    ),
    (
        "en",
        "Hi, this is Jane Placeholder (jane.placeholder@example.net, +44 20 7946 0958). Please "
        "refund the deposit to GB82 WEST 1234 5698 7654 32.",
    ),
    (
        "de",
        "Hallo, hier ist Erika Mustermann, E-Mail erika.mustermann@example.de, Telefon "
        "+49 30 901820. Bitte überweisen Sie auf DE89 3704 0044 0532 0130 00.",
    ),
    ("hu", "Az új lakcímem 1051 Budapest, Minta utca 12., kérlek frissítsd a szerződésen."),
    (
        "en",
        "Summarise the meeting: Minta Mária will send the draft to jane.placeholder@example.net "
        "by Friday; call +44 20 7946 0958 if anything changes.",
    ),
    (
        "hu",
        "Kérlek, írj egy rövid emlékeztetőt: a TAJ számom 123 456 788, az ügyintéző Minta Mária, "
        "a határidő péntek.",
    ),
    ("en", "What is the capital of Hungary? Answer in one sentence."),
    (
        "de",
        "Bitte fassen Sie zusammen: Erika Mustermann hat die Rechnung per E-Mail an "
        "erika.mustermann@example.de geschickt.",
    ),
)

_PCTS = (50, 95, 99)


def percentiles(values: Sequence[float]) -> dict[str, float] | None:
    """p50 / p95 / p99 (:func:`pii_guard.eval.stats.percentile`) and the mean, to 0.001 ms."""
    pcts = stats.percentiles(values, _PCTS)
    if pcts is None:
        return None
    out = {k: round(v, 3) for k, v in pcts.items()}
    out["mean"] = round(sum(values) / len(values), 3)
    return out


# --- servers ------------------------------------------------------------------------------


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


class LocalServer:
    """An ASGI app served by uvicorn on 127.0.0.1 in a background thread."""

    def __init__(self, app: Any, port: int | None = None) -> None:
        import uvicorn

        self.port = port or _free_port()
        # lifespan "auto": the gateway's shutdown closes its pooled upstream client (LAB-1176).
        config = uvicorn.Config(
            app, host="127.0.0.1", port=self.port, log_level="warning", lifespan="auto"
        )
        self.server = uvicorn.Server(config)
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def __enter__(self) -> LocalServer:
        self.thread.start()
        deadline = time.monotonic() + 15
        while not self.server.started:
            if time.monotonic() > deadline or not self.thread.is_alive():
                raise RuntimeError(f"server on port {self.port} did not start")
            time.sleep(0.02)
        return self

    def __exit__(self, *exc: object) -> None:
        self.server.should_exit = True
        self.thread.join(timeout=10)


class _Collector(Observability):
    """Keeps every event's timing in memory; no traffic payloads, so no extra cost."""

    def __init__(self) -> None:
        super().__init__(ObservabilitySettings(traffic_log=TrafficLevel.OFF))
        self.events: dict[str, dict[str, Any]] = {}

    @property
    def recording(self) -> bool:  # type: ignore[override]
        return True

    def record(self, event: dict[str, Any]) -> None:
        self.events[event["id"]] = event


# --- running ------------------------------------------------------------------------------


@dataclass
class CellResult:
    mode: str
    concurrency: int
    stream: bool
    requests: int
    errors: int
    wall_s: float
    detectors: list[str]
    client_ms: list[float] = field(default_factory=list)
    client_ttft_ms: list[float] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        timing = [e["timing"] for e in self.events]

        def col(key: str) -> list[float]:
            return [t[key] for t in timing if t.get(key) is not None]

        detector_names = sorted({k for t in timing for k in t["detectors_ms"]})
        return {
            "mode": self.mode,
            "concurrency": self.concurrency,
            "stream": self.stream,
            "requests": self.requests,
            "errors": self.errors,
            "throughput_rps": round(self.requests / self.wall_s, 3) if self.wall_s else None,
            "overhead_ms": percentiles(col("overhead_ms")),
            "total_ms": percentiles(col("total_ms")),
            "upstream_ms": percentiles(col("upstream_ms")),
            "added_ttft_ms": percentiles(col("added_ttft_ms")) if self.stream else None,
            "client_ms": percentiles(self.client_ms),
            "client_ttft_ms": percentiles(self.client_ttft_ms) if self.stream else None,
            "stages_ms": {
                stage: percentiles([t["stages_ms"][stage] for t in timing]) for stage in STAGES
            },
            "detectors_ms": {
                name: percentiles([t["detectors_ms"].get(name, 0.0) for t in timing])
                for name in detector_names
            },
        }


async def _one(
    client: httpx.AsyncClient, mode: str, stream: bool, language: str, text: str
) -> tuple[str | None, float, float | None, bool]:
    body: dict[str, Any] = {
        "model": "pii-guard-mock",
        "messages": [{"role": "user", "content": text}],
    }
    if stream:
        body["stream"] = True
    headers = {"X-PII-Guard-Mode": mode, "X-PII-Guard-Language": language}
    # A new vault session per request: without one the gateway's default session would serve
    # the repeated corpus from its detection cache (LAB-1286).
    url = f"/s/bench_{secrets.token_hex(8)}/v1/chat/completions"
    started = time.perf_counter()
    first: float | None = None
    try:
        if stream:
            async with client.stream("POST", url, json=body, headers=headers) as r:
                async for line in r.aiter_lines():
                    if first is None and line.startswith("data:"):
                        first = (time.perf_counter() - started) * 1000
                ok = r.status_code == 200
                rid = r.headers.get("x-pii-guard-request-id")
        else:
            r = await client.post(url, json=body, headers=headers)
            ok = r.status_code == 200
            rid = r.headers.get("x-pii-guard-request-id")
    except httpx.HTTPError:
        return None, (time.perf_counter() - started) * 1000, None, False
    return rid, (time.perf_counter() - started) * 1000, first, ok


async def _cell(
    base_url: str,
    collector: _Collector,
    *,
    mode: str,
    concurrency: int,
    stream: bool,
    requests: int,
    warmup: int,
    offset: int,
) -> CellResult:
    limits = httpx.Limits(max_connections=concurrency, max_keepalive_connections=concurrency)
    async with httpx.AsyncClient(base_url=base_url, timeout=300, limits=limits) as client:
        for i in range(warmup):
            language, text = CORPUS[(offset + i) % len(CORPUS)]
            await _one(client, mode, stream, language, text)
        collector.events.clear()
        semaphore = asyncio.Semaphore(concurrency)

        async def job(i: int) -> tuple[str | None, float, float | None, bool]:
            language, text = CORPUS[(offset + i) % len(CORPUS)]
            async with semaphore:
                return await _one(client, mode, stream, language, text)

        started = time.perf_counter()
        results = await asyncio.gather(*(job(i) for i in range(requests)))
        wall = time.perf_counter() - started
    await asyncio.sleep(0.05)  # let stream finalisers record their events
    cell = CellResult(mode, concurrency, stream, requests, 0, wall, [])
    for rid, client_ms, ttft, ok in results:
        event = collector.events.get(rid or "")
        if not ok or event is None or event["outcome"] != "ok":
            cell.errors += 1
            continue
        cell.events.append(event)
        cell.client_ms.append(round(client_ms, 3))
        if ttft is not None:
            cell.client_ttft_ms.append(round(ttft, 3))
    cell.detectors = sorted({d for e in cell.events for d in e["detectors"]})
    return cell


def run_benchmark(
    *,
    modes: Sequence[str] = ("fast",),
    concurrency: Sequence[int] = (1, 8),
    streams: Sequence[bool] = (False, True),
    requests: int = 200,
    mode_requests: Mapping[str, int] | None = None,
    warmup: int = 5,
    delay_ms: float = 50.0,
    progress: Any = None,
) -> list[CellResult]:
    """Run every cell; ``mode_requests`` caps N per mode (``{"audit": 12}``)."""
    from pii_guard.api.app import create_app
    from pii_guard.config import Settings

    settings = Settings(
        host="127.0.0.1",
        upstream_api_key=None,
        tenant_key=secrets.token_hex(32),
        upstream_base_url="http://127.0.0.1:1/v1",  # replaced below
    )
    mock_app = create_mock_upstream(delay_ms=delay_ms)
    cells: list[CellResult] = []
    with LocalServer(mock_app) as upstream:
        settings = settings.model_copy(update={"upstream_base_url": upstream.url + "/v1"})
        app = create_app(settings, ObservabilitySettings(traffic_log=TrafficLevel.OFF))
        collector = _Collector()
        app.state.observability = collector
        with LocalServer(app) as api:
            offset = 0
            for mode in modes:
                n = (mode_requests or {}).get(mode, requests)
                w = min(warmup, 1) if mode == "audit" else warmup
                for c in concurrency:
                    for stream in streams:
                        cell = asyncio.run(
                            _cell(
                                api.url,
                                collector,
                                mode=mode,
                                concurrency=c,
                                stream=stream,
                                requests=n,
                                warmup=w,
                                offset=offset,
                            )
                        )
                        offset += n + w
                        cells.append(cell)
                        if progress:
                            progress(cell)
    return cells


# --- run records --------------------------------------------------------------------------


def corpus_sha256() -> str:
    return hashlib.sha256(json.dumps(CORPUS, ensure_ascii=False).encode("utf-8")).hexdigest()


def _cpu_brand() -> str | None:
    try:
        if platform.system() == "Darwin":
            out = subprocess.run(
                ["sysctl", "-n", "machdep.cpu.brand_string"],  # noqa: S607
                capture_output=True,
                text=True,
                timeout=5,
                check=True,
            ).stdout.strip()
            return out or None
        with open("/proc/cpuinfo", encoding="utf-8") as f:
            for line in f:
                if line.startswith("model name"):
                    return line.split(":", 1)[1].strip()
    except (OSError, subprocess.SubprocessError):
        return None
    return None


def build_records(
    cells: Sequence[CellResult],
    *,
    slug: str,
    delay_ms: float,
    day: str | None = None,
    detector_info: Mapping[str, Mapping[str, Any]] | None = None,
    notes: Sequence[str] = (),
    commit: tuple[str, bool] | None = None,
) -> list[dict[str, Any]]:
    """One ``kind: latency`` run record per mode (``<day>-<slug>-<mode>``)."""
    from pii_guard.eval.record import RECORD_SCHEMA_VERSION, host_info
    from pii_guard.eval.report import git_commit

    day = day or date.today().isoformat()
    commit_hash, dirty = commit if commit is not None else git_commit()
    hardware = host_info()
    brand = _cpu_brand()
    hardware["description"] = (
        f"{brand or hardware['machine']}, {hardware['cpu_count']} CPUs, local loopback"
    )
    records = []
    for mode in dict.fromkeys(c.mode for c in cells):
        mode_cells = [c for c in cells if c.mode == mode]
        names = sorted({d for c in mode_cells for d in c.detectors}, key=_detector_order)
        detectors = []
        for name in names:
            info = dict((detector_info or {}).get(name) or {})
            detectors.append(
                {
                    "name": name,
                    "model": info.get("model"),
                    "model_ref": info.get("model_ref"),
                    "revision": None,
                    "settings": dict(info.get("settings") or {}),
                    "serving": info.get("serving"),
                }
            )
        system_detectors = "+".join(
            d["name"] + (f":{d['model']}" if d["model"] else "") for d in detectors
        )
        label = (
            "pii-guard gateway, "
            + mode
            + " mode ("
            + " + ".join(d["name"] + (f" {d['model']}" if d["model"] else "") for d in detectors)
            + ")"
        )
        records.append(
            {
                "schema_version": RECORD_SCHEMA_VERSION,
                "run_id": f"{day}-{slug}-{mode}",
                "kind": "latency",
                "date": day,
                "recorded_at": datetime.now(UTC).isoformat(timespec="seconds"),
                "source": "recorded",
                "imported_from": None,
                "title": f"Gateway overhead, {mode} mode, mock upstream at {delay_ms:g} ms",
                "notes": [
                    f"Mock upstream with a fixed {delay_ms:g} ms delay on loopback; overhead = "
                    "gateway total - time waiting on the upstream - time handing stream events "
                    "to the client.",
                    "Each request is a new session (no detection cache hits); one user message "
                    "per request from the fixed fictional corpus.",
                    *notes,
                ],
                "code": {
                    "commit": commit_hash,
                    "dirty": dirty,
                    "pii_guard_version": __version__,
                    "note": None,
                },
                "system": {
                    "key": f"gateway-latency:{mode}:{system_detectors or 'none'}",
                    "label": label,
                    "family": "pii-guard",
                    "tool": "pii-guard",
                    "version": __version__,
                    "detectors": detectors,
                },
                "fixture_set": "latency-corpus",
                "fixtures": [
                    {
                        "path": "src/pii_guard/bench/latency.py#CORPUS",
                        "sha256": corpus_sha256(),
                        "set": "latency-corpus",
                        "language": None,
                        "origin": "hand-written",
                        "generator": None,
                        "documents": len(CORPUS),
                    }
                ],
                "languages": sorted({lang for lang, _ in CORPUS}),
                "hardware": hardware,
                "cost": None,
                "metrics": {
                    "upstream_delay_ms": delay_ms,
                    "cells": [c.summary() for c in mode_cells],
                },
            }
        )
    return records


def _detector_order(name: str) -> tuple[int, str]:
    order = {"rules": 0, "ner": 1, "llm": 2, "known": 3, "visual": 4}
    return order.get(name, 9), name
