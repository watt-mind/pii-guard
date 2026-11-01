"""Demo: "which parties have an ID?" through the pii-guard gateway (LAB-1156).

One chat turn carries a fictional sales contract naming three parties, the ID cards of two of
them (one with its name in capitals, one expired) and the question. The gateway masks it in
one vault session: the contract's names become placeholders, each card's values are matched
to them (``FIKTÍV`` + ``MÁRIA`` on the card is ``Fiktív Mária`` in the contract), every
covered region shows its placeholder, and each image is followed by its masked transcript and
document summary. The model answers with placeholders; the gateway restores the names.

    uv run python examples/which_parties_have_an_id.py                 # mocked upstream
    uv run python examples/which_parties_have_an_id.py --live          # Baseten (BASETEN_API_KEY)
    uv run python examples/which_parties_have_an_id.py --render opaque # the "before": black boxes
    uv run python examples/which_parties_have_an_id.py --ocr tesseract --sam local --out demo/
    uv run python examples/which_parties_have_an_id.py --ocr tesseract --sam live --out demo/
    uv run python examples/which_parties_have_an_id.py --record-run RUN_ID   # a run record

Everything is fictional (ADR 0005): the cards are the LAB-1121 specimens in
``eval/fixtures/visual/`` (one with its expiry date reprinted in the past). By default the
recorded OCR words are used and SAM is off (faces and signatures stay visible; ``--sam local``
masks them on-device via YuNet + YOLOS-tiny; ``--sam live`` uses SAM 3, ``META_API_KEY``). Keys
are read from the environment or ``.env`` and never printed. ``--out DIR`` writes the forwarded
(masked) request, the masked images and the answer.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import secrets
import sys
import time
from pathlib import Path
from typing import Any

import httpx
from fastapi.testclient import TestClient

from pii_guard.api.app import create_app
from pii_guard.config import Settings
from pii_guard.eval.visual_labels import (
    demo_documents,
    demo_messages,
    demo_mock_answer,
    score_demo_answer,
)
from pii_guard.gateway import Gateway, GatewayConfig
from pii_guard.gateway.detection import build_mode_detectors
from pii_guard.types import EntityType
from pii_guard.vault import Vault
from pii_guard.visual.regions import Region
from pii_guard.visual.sam import SamClient

BASETEN_URL = "https://inference.baseten.co/v1"
BASETEN_MODEL = "meta-models/muse-spark-open-1026"


class NoSam:
    """SAM off: no faces or signatures are found (they stay visible)."""

    model = "off"
    prompts = {EntityType.FACE: ("face",), EntityType.SIGNATURE: ("signature",)}  # noqa: RUF012

    def segment(self, image: bytes, entity_types: object = None) -> list[Region]:
        return []


def _env(name: str) -> str | None:
    if os.environ.get(name):
        return os.environ[name]
    env = Path(os.environ.get("PII_GUARD_ENV_FILE", ".env"))
    if env.is_file():
        for line in env.read_text(encoding="utf-8").splitlines():
            key, sep, value = line.partition("=")
            if sep and key.strip() == name:
                return value.strip().strip('"') or None
    return None


def run(
    *,
    live: bool = False,
    render: str = "labels",
    ocr: str = "cached",
    sam: str = "off",
    out: Path | None = None,
) -> dict[str, Any]:
    demo = demo_documents()
    forwarded: list[dict[str, Any]] = []

    def mock_upstream(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        forwarded.append(body)
        answer = demo_mock_answer(body)
        return httpx.Response(
            200,
            json={
                "id": "mock",
                "object": "chat.completion",
                "model": body["model"],
                "choices": [{"index": 0, "message": {"role": "assistant", "content": answer}}],
            },
        )

    class Recorder(httpx.AsyncHTTPTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            forwarded.append(json.loads(request.content))
            return await super().handle_async_request(request)

    if live:
        key = _env("BASETEN_API_KEY")
        if not key:
            raise SystemExit("--live needs BASETEN_API_KEY")
        upstream_url, upstream_key, model = BASETEN_URL, key, BASETEN_MODEL
        transport: httpx.AsyncBaseTransport = Recorder()
    else:
        upstream_url, upstream_key, model = "http://upstream.invalid/v1", "mock", "mock-model"
        transport = httpx.MockTransport(mock_upstream)

    settings = Settings(
        tenant_key=secrets.token_hex(32),
        upstream_base_url=upstream_url,
        upstream_api_key=upstream_key,
        image_render=render,  # type: ignore[arg-type]
        detectors=("rules",),
    )
    config = GatewayConfig(mode="fast")
    if ocr == "tesseract":
        from pii_guard.visual.ocr import TesseractOcr

        engine: Any = TesseractOcr()
    else:
        engine = demo.ocr
    if sam == "live":
        sam_client: Any = SamClient(api_key=_env("META_API_KEY"))
    elif sam == "local":
        from pii_guard.visual.segment import LocalSegmenter
        from pii_guard.visual.segmenters import LocalSignatureSegmenter

        sam_client = LocalSignatureSegmenter(LocalSegmenter())
    else:
        sam_client = NoSam()
    app = create_app(settings)
    vault = Vault.from_settings(settings)
    app.state.vault = vault  # the REST API and the gateway share one vault
    app.state.gateway = Gateway(
        settings=settings,
        vault=vault,
        config=config,
        detectors=build_mode_detectors(settings, config),
        transport=transport,
        sam=sam_client,
        ocr=engine,
    )
    body = {"model": model, "messages": demo_messages(demo), "max_tokens": 1200}
    if live:
        body["reasoning_effort"] = "low"
    started = time.perf_counter()
    # Loopback base URL + client: the DNS-rebinding guard answers 400 for TestClient's
    # default host (testserver) (LAB-1253).
    with TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 50000)) as http:
        # The application knows its contract's parties: it pre-loads them as known values,
        # so the session masks them in the text without an NER or LLM detector.
        created = http.post(
            "/v1/sessions",
            json={"known_values": [{"value": p, "entity_type": "PERSON"} for p in demo.parties]},
        )
        created.raise_for_status()
        session_id = created.json()["session_id"]
        response = http.post(
            "/v1/chat/completions", json=body, headers={"X-PII-Guard-Session": session_id}
        )
    elapsed = time.perf_counter() - started
    if response.status_code != 200:
        raise SystemExit(f"gateway answered {response.status_code}: {response.text[:300]}")
    answer_json = response.json()
    answer = answer_json["choices"][0]["message"]["content"] or ""
    score = score_demo_answer(answer, demo.expected)
    raw = json.dumps(forwarded[0], ensure_ascii=False) if forwarded else ""
    leaked = sum(p in raw or p.upper() in raw for p in demo.parties)
    if out is not None:
        out.mkdir(parents=True, exist_ok=True)
        (out / "forwarded.json").write_text(
            json.dumps(forwarded[0], ensure_ascii=False, indent=1), encoding="utf-8"
        )
        index = 0
        user = next(m for m in forwarded[0]["messages"] if m["role"] == "user")
        for part in user["content"]:
            if part.get("type") == "image_url":
                index += 1
                png = base64.b64decode(part["image_url"]["url"].split(",", 1)[1])
                (out / f"masked-{index}.png").write_bytes(png)
        (out / "answer.txt").write_text(answer + "\n", encoding="utf-8")
    return {
        "render": render,
        "upstream": "baseten:" + BASETEN_MODEL if live else "mock",
        "ocr": ocr,
        "sam": sam,
        "score": score,
        "leaked": leaked,
        "seconds": round(elapsed, 1),
        "usage": answer_json.get("usage"),
        "answer": answer,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--live", action="store_true", help="ask Baseten instead of the mock")
    parser.add_argument("--render", choices=("labels", "opaque"), default="labels")
    parser.add_argument("--ocr", choices=("cached", "tesseract"), default="cached")
    parser.add_argument("--sam", choices=("off", "local", "live"), default="off")
    parser.add_argument("--out", type=Path, help="write the forwarded request, images, answer")
    parser.add_argument("--record-run", metavar="RUN_ID", help="write a run record")
    args = parser.parse_args(argv)
    result = run(live=args.live, render=args.render, ocr=args.ocr, sam=args.sam, out=args.out)
    if args.record_run:
        from pii_guard.eval.record import write_records
        from pii_guard.eval.visual_labels import demo_record

        write_records([demo_record(result, args.record_run, [])], overwrite=True)
    print(result.pop("answer"))
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
