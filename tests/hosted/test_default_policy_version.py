"""A project's default policy is its family's latest version on every hosted route (LAB-1537).

The hosted Policy view shows the default family's latest version; requests that select no
endpoint (text, chat completions, responses, images) must apply that same version, while an
endpoint URL ``/e/<id>/...`` keeps applying the exact version it pins. Identities, keys,
hosts and values are synthetic (ADR 0005).
"""

from __future__ import annotations

import base64
import io
import json
import time
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from pii_guard.api.app import create_app
from pii_guard.config import Settings
from pii_guard.hosted.quotas import QuotaLedger, QuotaLimits
from pii_guard.types import EntityType
from pii_guard.visual import OcrWord
from pii_guard.visual.ocr import TesseractOcr
from pii_guard.visual.regions import Box, Region
from pii_guard.visual.segment import LocalSegmenter
from pii_guard.visual.segmenters import LocalSignatureSegmenter, SignatureDetector

ORIGIN = "https://guard.example"
EMAIL = "synthetic.one@example.com"
W, H = 400, 260
SIGNATURE = Box(220, 190, 330, 230)


def auth(subject: str = "synthetic-one") -> dict[str, str]:
    encoded = base64.b64encode(
        json.dumps({"auth_typ": "google", "claims": [{"typ": "sub", "val": subject}]}).encode()
    ).decode()
    return {"x-ms-client-principal": encoded, "origin": ORIGIN}


def settings() -> Settings:
    return Settings(
        _env_file=None,
        hosted=True,
        hosted_public_origin=ORIGIN,
        hosted_trust_easy_auth=True,
        hosted_single_process=True,
        tenant_key=bytes(range(32)).hex(),
        allowed_hosts=("guard.example",),
        detectors=("rules",),
        ner_fallback="off",
        upstream_api_key="synthetic-sponsored-key",
    )


@pytest.fixture
def hosted(monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[TestClient, list[httpx.Request]]]:
    seen: list[httpx.Request] = []

    def echo(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        body = json.loads(request.content)
        if request.url.path.endswith("/responses"):
            return httpx.Response(
                200,
                json={
                    "id": "synthetic-response",
                    "object": "response",
                    "status": "completed",
                    "model": body["model"],
                    "output": [
                        {
                            "type": "message",
                            "role": "assistant",
                            "content": [{"type": "output_text", "text": body["input"]}],
                        }
                    ],
                },
            )
        return httpx.Response(
            200,
            json={
                "id": "synthetic-completion",
                "object": "chat.completion",
                "model": body["model"],
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": body["messages"][-1]["content"],
                        },
                    }
                ],
            },
        )

    # Nothing leaves the process: every hosted transport is the in-process echo.
    for transport in ("pii_guard.hosted.runtime", "pii_guard.hosted.egress"):
        monkeypatch.setattr(transport + ".SecureTransport", lambda: httpx.MockTransport(echo))
    monkeypatch.setattr(
        "pii_guard.hosted.egress.secure_client",
        lambda **kwargs: httpx.AsyncClient(transport=httpx.MockTransport(echo), **kwargs),
    )
    app = create_app(settings())
    app.state.hosted.quotas = QuotaLedger(
        QuotaLimits(global_daily_microdollars=1_000_000_000),
        sponsored_allocation_microdollars=1_000_000_000,
        allocation_expires_at=time.time() + 3600,
        claim_allocation=lambda: True,
    )
    with TestClient(app, base_url=ORIGIN) as client:
        yield client, seen


def _default_project(client: TestClient) -> dict[str, Any]:
    listed = client.get("/v1/projects", headers=auth())
    assert listed.status_code == 200, listed.text
    return dict(listed.json()["projects"][0])


def _new_default_version(client: TestClient, project: dict[str, Any], **actions: str) -> str:
    saved = client.put(
        f"/v1/projects/{project['id']}/policies/{project['default_policy_id']}",
        json={"name": "Default policy", "entity_policies": actions},
        headers=auth(),
    )
    assert saved.status_code == 201, saved.text
    assert saved.json()["version"] == 2
    return str(saved.json()["policy_version_id"])


def _latest_default(client: TestClient, project: dict[str, Any]) -> str:
    """What the Policy view shows: the default family's highest version."""
    policies = client.get(f"/v1/projects/{project['id']}/policies", headers=auth()).json()
    family = [p for p in policies["policies"] if p["policy_id"] == project["default_policy_id"]]
    return str(max(family, key=lambda p: p["version"])["policy_version_id"])


def _sent_text(request: httpx.Request) -> str:
    body = json.loads(request.content)
    return str(body["input"] if "input" in body else body["messages"][-1]["content"])


def test_project_reports_the_latest_default_version(hosted) -> None:
    client, _ = hosted
    project = _default_project(client)
    first = project["default_policy_version_id"]
    second = _new_default_version(client, project, EMAIL="keep")
    assert second != first
    project = _default_project(client)
    assert project["default_policy_version_id"] == second == _latest_default(client, project)
    single = client.get(f"/v1/projects/{project['id']}", headers=auth()).json()
    assert single["default_policy_version_id"] == second


def test_text_mask_applies_the_latest_default_version(hosted) -> None:
    client, _ = hosted
    project = _default_project(client)
    masked = client.post("/v1/mask", json={"text": f"Mail {EMAIL}"}, headers=auth())
    assert masked.status_code == 200, masked.text
    assert EMAIL not in masked.json()["masked_text"]
    second = _new_default_version(client, project, EMAIL="keep")
    kept = client.post("/v1/mask", json={"text": f"Mail {EMAIL}"}, headers=auth())
    assert kept.status_code == 200, kept.text
    assert kept.headers["x-pii-guard-policy-version"] == second
    assert EMAIL in kept.json()["masked_text"]


@pytest.mark.parametrize("path", ["/v1/chat/completions", "/v1/responses"])
def test_console_gateway_applies_the_latest_default_version(hosted, path: str) -> None:
    client, seen = hosted
    project = _default_project(client)
    second = _new_default_version(client, project, EMAIL="keep")
    body: dict[str, Any] = {"model": "muse-spark-1.3"}
    body.update(
        {"input": EMAIL}
        if path == "/v1/responses"
        else {"messages": [{"role": "user", "content": EMAIL}]}
    )
    result = client.post(path, json=body, headers=auth())
    assert result.status_code == 200, result.text
    assert result.headers["x-pii-guard-policy-version"] == second
    assert EMAIL in _sent_text(seen[-1])


def test_endpoint_url_keeps_its_pinned_version(hosted) -> None:
    client, seen = hosted
    project = _default_project(client)
    first = project["default_policy_version_id"]
    created = client.post(
        f"/v1/projects/{project['id']}/endpoints",
        json={
            "name": "Synthetic pinned endpoint",
            "policy_version_id": first,
            "provider": "sponsored",
            "model": "muse-spark-1.3",
        },
        headers=auth(),
    )
    assert created.status_code == 201, created.text
    endpoint = created.json()["id"]
    _new_default_version(client, project, EMAIL="keep")
    result = client.post(
        f"/e/{endpoint}/v1/chat/completions",
        json={"messages": [{"role": "user", "content": EMAIL}]},
        headers=auth(),
    )
    assert result.status_code == 200, result.text
    assert result.headers["x-pii-guard-policy-version"] == first
    assert EMAIL not in _sent_text(seen[-1])


def _local_images(app: FastAPI, signature_calls: list[int]) -> None:
    """The real hosted image component types with their model work faked in-process."""
    faces = LocalSegmenter(detector=object())

    def segment(image: bytes, entity_types: Any = None) -> list[Region]:
        return [Region(EntityType.FACE, Box(30, 40, 129, 169), 0.9, "yunet")]

    def signatures() -> SignatureDetector:
        def boxes(image: Image.Image) -> list[tuple[float, float, float, float, float]]:
            if image.size != (W, H):
                return []
            signature_calls.append(1)
            return [(*map(float, SIGNATURE.to_list()), 0.8)]

        return SignatureDetector(boxes=boxes)

    def words(image: Image.Image) -> list[OcrWord]:
        return []

    faces.segment = segment  # type: ignore[method-assign]
    ocr = TesseractOcr()
    ocr.read = None  # type: ignore[assignment,method-assign]
    ocr.words = words  # type: ignore[method-assign]
    app.state.sam_client = LocalSignatureSegmenter(faces, signatures=signatures)
    app.state.ocr_engine = ocr


def test_image_route_applies_the_latest_default_version(hosted) -> None:
    client, _ = hosted
    signature_calls: list[int] = []
    _local_images(client.app, signature_calls)
    output = io.BytesIO()
    Image.new("RGB", (W, H), (230, 236, 248)).save(output, format="PNG")
    body = {"image": base64.b64encode(output.getvalue()).decode()}
    masked = client.post("/v1/mask/image", json=body, headers=auth())
    assert masked.status_code == 200, masked.text
    assert "SIGNATURE" in {r["entity_type"] for r in masked.json()["regions"]}
    project = _default_project(client)
    second = _new_default_version(client, project, SIGNATURE="keep")
    kept = client.post("/v1/mask/image", json=body, headers=auth())
    assert kept.status_code == 200, kept.text
    assert kept.headers["x-pii-guard-policy-version"] == second
    assert "SIGNATURE" not in {r["entity_type"] for r in kept.json()["regions"]}
    assert len(signature_calls) == 1
