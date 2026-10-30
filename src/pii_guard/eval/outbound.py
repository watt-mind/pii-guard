"""``pii-guard eval --outbound-check``: replay the documents through the gateway (LAB-1505).

The outbound re-check (:mod:`pii_guard.gateway.outbound`, LAB-1500) reads every masked request
again before it goes upstream and refuses it (``422 outbound_check_failed``) when a value the
session knows is still in it. On the evaluation sets every request is one the gateway should
forward, so every block is a false block: the rate should be 0.

The replay sends each document through the in-process gateway in fast mode, with the run's own
detectors (``--detectors``), against a mock upstream that answers ``OK.``; each document opens
its own vault session, as a new conversation would. A document that is a Chat Completions body
(``messages``: the agent-traffic sets) is sent as it is, any other as one user message. Known
values are not pre-loaded here.

The result is one ``outbound_check`` block per language and overall, added to the scorecard's
text blocks and carried into the run record (``text_block.outbound_check``): requests,
re-checked requests (refusals before the re-check, such as a blocked entity policy, are not
re-checked), blocked, the false-block rate and the re-check's own time (p50 / p95 ms). Counts
and times only, never a value or a text.
"""

from __future__ import annotations

import asyncio
import json
import secrets
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import httpx

from pii_guard.eval import stats
from pii_guard.eval.fixtures import Document
from pii_guard.types import Detector

__all__ = ["Outcome", "outbound_blocks", "replay", "summarize_outcomes"]


@dataclass(frozen=True)
class Outcome:
    """One replayed document: ``passed``, ``blocked`` or ``refused`` (before the re-check)."""

    language: str
    result: str
    #: The re-check's own time (``outbound_check.ms``); ``None`` when it did not run.
    ms: float | None = None


def _answer(request: httpx.Request) -> httpx.Response:
    body = json.loads(request.content)
    return httpx.Response(
        200,
        json={
            "id": "chatcmpl-eval",
            "object": "chat.completion",
            "created": 0,
            "model": body.get("model", "mock"),
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "OK."},
                    "finish_reason": "stop",
                }
            ],
        },
    )


def _body(text: str) -> dict[str, Any]:
    try:
        body = json.loads(text)
    except ValueError:
        body = None
    if isinstance(body, dict) and isinstance(body.get("messages"), list):
        body.setdefault("model", "mock")
        body.pop("stream", None)
        return body
    return {"model": "mock", "messages": [{"role": "user", "content": text}]}


def _gateway(detectors: Sequence[Detector]) -> Any:
    from pydantic import SecretStr

    from pii_guard.config import Settings
    from pii_guard.gateway import Gateway, GatewayConfig, Mode, build_mode_detectors
    from pii_guard.vault import Vault

    settings = Settings(
        tenant_key=SecretStr(secrets.token_hex(32)),
        upstream_base_url="https://upstream.invalid/v1",
        upstream_api_key=SecretStr("eval-mock-upstream"),
    )
    config = GatewayConfig(mode=Mode.FAST)
    return Gateway(
        settings=settings,
        vault=Vault.from_settings(settings),
        config=config,
        detectors=build_mode_detectors(settings, config, base=list(detectors)),
        transport=httpx.MockTransport(_answer),
    )


async def _send(gateway: Any, document: Document, session: str) -> Outcome:
    from pii_guard.gateway.outbound import OutboundCheckFailedError
    from pii_guard.types import PiiGuardError

    headers = {"X-PII-Guard-Mode": "fast", "X-PII-Guard-Language": document.language}
    try:
        response, gw_stats = await gateway.chat_completions(
            _body(document.text), headers, path_session=session
        )
    except OutboundCheckFailedError:
        return Outcome(document.language, "blocked")
    except PiiGuardError:
        return Outcome(document.language, "refused")
    check = gw_stats.outbound
    if response.status_code != 200 or check is None:
        return Outcome(document.language, "refused")
    return Outcome(document.language, check.result, round(check.ms, 3))


def replay(documents: Sequence[Document], detectors: Sequence[Detector]) -> list[Outcome]:
    """Send every document through the gateway, each in a new session, in order."""

    async def run() -> list[Outcome]:
        gateway = _gateway(detectors)
        try:
            return [
                await _send(gateway, d, f"evalob_{i}_{secrets.token_hex(4)}")
                for i, d in enumerate(documents)
            ]
        finally:
            await gateway.aclose()

    return asyncio.run(run())


def summarize_outcomes(outcomes: Sequence[Outcome]) -> dict[str, Any]:
    """The ``outbound_check`` block: counts, the false-block rate and the re-check time."""
    blocked = sum(o.result == "blocked" for o in outcomes)
    checked = sum(o.result in ("passed", "blocked") for o in outcomes)
    ms = [o.ms for o in outcomes if o.ms is not None]
    pcts = stats.percentiles(ms, (50, 95))
    return {
        "requests": len(outcomes),
        "checked": checked,
        "blocked": blocked,
        "rate": round(blocked / checked, 6) if checked else None,
        "check_ms": None if pcts is None else {k: round(v, 3) for k, v in pcts.items()},
    }


def outbound_blocks(documents: Sequence[Document], detectors: Sequence[Detector]) -> dict[str, Any]:
    """``{"overall": block, "languages": {lang: block}}`` from one gateway replay."""
    outcomes = replay(documents, detectors)
    by_language: dict[str, list[Outcome]] = defaultdict(list)
    for o in outcomes:
        by_language[o.language].append(o)
    return {
        "overall": summarize_outcomes(outcomes),
        "languages": {lang: summarize_outcomes(by_language[lang]) for lang in sorted(by_language)},
    }
