"""Hosted image masking (LAB-1390, ADR 0014) through the real ASGI app.

Signed-in Google owners only; local processing only (the built-in Tesseract and on-device
segmenter types, faces and signatures, with their model work replaced by in-process fakes);
bounded bytes, pixels, media types, capacity and a daily image count reserved before work;
owner-scoped sessions shared with text. Every image is drawn here and every identity and
value is synthetic (ADR 0005). Nothing may leave the process: the HTTP transports are blocked.
"""

from __future__ import annotations

import base64
import io
import json
import logging
import random
import time
from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from pii_guard.api.app import create_app
from pii_guard.config import Settings
from pii_guard.hosted.images import (
    hosted_visual_policies,
    image_body_limit,
    require_servable_visual_policies,
)
from pii_guard.hosted.quotas import QuotaLedger, QuotaLimits
from pii_guard.policy import Policy, PolicySet
from pii_guard.types import EntityType
from pii_guard.visual import OcrWord, SamClient
from pii_guard.visual.ocr import TesseractOcr
from pii_guard.visual.regions import Box, Region
from pii_guard.visual.segment import LocalSegmenter
from pii_guard.visual.segmenters import LocalSignatureSegmenter, SignatureDetector

ORIGIN = "https://guard.example"
TAJ_VALUE = "123 456 788"  # fictional, passes the checksum
NAME_VALUE = "Teszt Elek"  # the conventional fictional Hungarian name
W, H = 400, 260
FACE = Box(30, 40, 129, 169)
SIGNATURE = Box(220, 190, 330, 230)
WORDS = [
    OcrWord("TAJ:", Box(160, 60, 199, 79), (0,)),
    OcrWord("123", Box(205, 60, 239, 79), (0,)),
    OcrWord("456", Box(245, 60, 279, 79), (0,)),
    OcrWord("788", Box(285, 60, 319, 79), (0,)),
]


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def blocked(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("hosted image processing attempted network access")

    async def async_blocked(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("hosted image processing attempted network access")

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", blocked)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", async_blocked)


def auth(subject: str = "synthetic-one") -> dict[str, str]:
    encoded = base64.b64encode(
        json.dumps({"auth_typ": "google", "claims": [{"typ": "sub", "val": subject}]}).encode()
    ).decode()
    return {"x-ms-client-principal": encoded, "origin": ORIGIN}


def settings(**overrides: Any) -> Settings:
    return Settings(
        _env_file=None,
        **{
            "hosted": True,
            "hosted_public_origin": ORIGIN,
            "hosted_trust_easy_auth": True,
            "hosted_single_process": True,
            "tenant_key": bytes(range(32)).hex(),
            "allowed_hosts": ("guard.example",),
            "detectors": ("rules",),
            "ner_fallback": "off",
            # The opt-in on-device engines (ADR 0015); the SAM 3.1 default has its own tests.
            "segmenter": "local",
            "upstream_api_key": "synthetic-sponsored-key",
            **overrides,
        },
    )


def card(width: int = W, height: int = H, fmt: str = "PNG") -> bytes:
    image = Image.new("RGB", (width, height), (230, 236, 248))
    draw = ImageDraw.Draw(image)
    draw.ellipse(FACE.to_list(), fill=(240, 200, 170))
    draw.text((160, 60), f"TAJ: {TAJ_VALUE}", fill="black")
    output = io.BytesIO()
    image.save(output, format=fmt)
    return output.getvalue()


class Calls:
    def __init__(self) -> None:
        self.ocr = 0
        self.segment = 0
        self.signature = 0


def local_pipeline(app: FastAPI, calls: Calls) -> None:
    """The real hosted component types, with their model work replaced in-process."""
    faces = LocalSegmenter(detector=object())

    def segment(image: bytes, entity_types: Any = None) -> list[Region]:
        calls.segment += 1
        return [Region(EntityType.FACE, FACE, 0.9, "yunet")]

    def signatures() -> SignatureDetector:
        def boxes(image: Image.Image) -> list[tuple[float, float, float, float, float]]:
            if image.size != (W, H):
                return []  # the 2x2 tiles: the whole-image pass already found it
            calls.signature += 1
            return [(*map(float, SIGNATURE.to_list()), 0.8)]

        return SignatureDetector(boxes=boxes)

    def words(image: Image.Image) -> list[OcrWord]:
        calls.ocr += 1
        return list(WORDS)

    faces.segment = segment  # type: ignore[method-assign]
    segmenter = LocalSignatureSegmenter(faces, signatures=signatures)
    ocr = TesseractOcr()
    ocr.read = None  # type: ignore[assignment,method-assign]
    ocr.words = words  # type: ignore[method-assign]
    app.state.sam_client = segmenter
    app.state.ocr_engine = ocr


def roomy(app: FastAPI, **limits: int) -> None:
    app.state.hosted.quotas = QuotaLedger(QuotaLimits(**limits))


@pytest.fixture
def hosted() -> Iterator[tuple[TestClient, Calls]]:
    app = create_app(settings())
    calls = Calls()
    local_pipeline(app, calls)
    with TestClient(app, base_url=ORIGIN) as client:
        yield client, calls


def post_image(
    client: TestClient,
    headers: dict[str, str],
    data: bytes | None = None,
    *,
    path: str = "/v1/mask/image",
    **fields: str,
) -> httpx.Response:
    body = {"image": base64.b64encode(card() if data is None else data).decode(), **fields}
    return client.post(path, json=body, headers=headers)


def test_signed_in_owner_masks_in_memory_and_shares_placeholders_with_text(
    hosted: tuple[TestClient, Calls],
) -> None:
    client, calls = hosted
    text = client.post("/v1/mask", json={"text": f"TAJ: {TAJ_VALUE}"}, headers=auth())
    assert text.status_code == 200, text.text
    session = text.json()["session_id"]
    placeholder = text.json()["masked_text"].removeprefix("TAJ: ").strip()
    assert TAJ_VALUE not in placeholder and placeholder.startswith("[[")

    response = post_image(client, auth(), session_id=session)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["session_id"] == session
    assert placeholder in body["transcript"] and TAJ_VALUE not in body["transcript"]
    assert body["analysis"]["sam"]["model"].startswith(LocalSegmenter.model)
    assert body["analysis"]["ocr"]["ran"] is True
    # Signatures are masked on-device by default (LAB-1444): no SAM, no override.
    assert {r["entity_type"] for r in body["regions"]} >= {"FACE", "SIGNATURE"}
    assert TAJ_VALUE not in response.text
    assert calls.ocr == calls.segment == calls.signature == 1
    # The image's value restores like the text's: one owner, one session.
    restored = client.post(
        "/v1/unmask", json={"session_id": session, "text": body["transcript"]}, headers=auth()
    )
    assert TAJ_VALUE in restored.json()["text"]
    assert response.headers["cache-control"] == "no-store"


def test_raw_upload_is_accepted_like_json(hosted: tuple[TestClient, Calls]) -> None:
    client, _ = hosted
    headers = {**auth(), "content-type": "image/png"}
    response = client.post("/v1/mask/image", content=card(), headers=headers)
    assert response.status_code == 200, response.text


def test_another_owner_cannot_use_a_session(hosted: tuple[TestClient, Calls]) -> None:
    client, calls = hosted
    session = client.post("/v1/mask", json={"text": "x"}, headers=auth()).json()["session_id"]
    response = post_image(client, auth("synthetic-two"), session_id=session)
    assert response.status_code == 404
    assert calls.ocr == 0


def test_guests_keys_endpoints_and_cross_origin_refused(
    hosted: tuple[TestClient, Calls],
) -> None:
    client, calls = hosted
    # A guest (no identity, a demo cookie is issued): sign in first.
    assert post_image(client, {"origin": ORIGIN}).status_code == 401
    # A guard API key is its owner for text, but images stay with the signed-in console.
    issued = client.post("/v1/account/api-keys", json={"name": "Synthetic key"}, headers=auth())
    assert issued.status_code == 201, issued.text
    key = {"authorization": "Bearer " + issued.json()["key"]}
    assert post_image(client, key).status_code == 401
    # Endpoint paths are for endpoint keys and text; never images.
    assert post_image(client, auth(), path="/e/ep_synthetic/v1/mask/image").status_code in {
        401,
        403,
        404,
    }
    # Same-origin is still required for a cookie/Easy Auth mutation.
    headers = auth()
    headers["origin"] = "https://cross-site.example"
    assert post_image(client, headers).status_code == 403
    assert client.get("/v1/mask/image", headers=auth()).status_code == 403
    assert calls.ocr == calls.segment == 0


def test_byte_media_type_and_pixel_limits_refuse_before_work() -> None:
    app = create_app(settings(hosted_max_image_bytes=65536))
    calls = Calls()
    local_pipeline(app, calls)
    with TestClient(app, base_url=ORIGIN) as client:
        noise = Image.frombytes("RGB", (160, 160), random.Random(0).randbytes(160 * 160 * 3))  # noqa: S311 - synthetic noise
        output = io.BytesIO()
        noise.save(output, format="PNG")
        big = output.getvalue()
        assert 65536 < len(big) < image_body_limit(app.state.settings)
        # Over the decoded image limit, under the ingress body limit: the route says 413.
        too_big = client.post(
            "/v1/mask/image", content=big, headers={**auth(), "content-type": "image/png"}
        )
        assert too_big.status_code == 413, too_big.text
        # Over the ingress body limit: refused while reading, before the route.
        oversized = b"\x89PNG" + b"0" * image_body_limit(app.state.settings)
        refused = client.post(
            "/v1/mask/image", content=oversized, headers={**auth(), "content-type": "image/png"}
        )
        assert refused.status_code == 403
        # Not a PNG or JPEG, whatever the header says (sniffed from the bytes).
        gif = io.BytesIO()
        Image.new("RGB", (8, 8)).save(gif, format="GIF")
        assert post_image(client, auth(), gif.getvalue()).status_code == 415
        text = client.post(
            "/v1/mask/image", content=b"hello", headers={**auth(), "content-type": "text/plain"}
        )
        assert text.status_code == 415
        # Over the hosted pixel cap (8 MP), a small file: 413 before decoding.
        huge = card(3000, 3000)
        assert len(huge) < 65536
        assert post_image(client, auth(), huge).status_code == 413
        assert calls.ocr == calls.segment == 0


def test_daily_image_count_is_reserved_before_work_and_never_refunded(
    hosted: tuple[TestClient, Calls],
) -> None:
    client, calls = hosted
    roomy(client.app, user_images=1)
    assert post_image(client, auth()).status_code == 200
    second = post_image(client, auth())
    assert second.status_code == 429
    assert second.json()["error"]["code"] == "quota_exceeded"
    assert calls.ocr == 1
    # Text still works: the image count is separate from the request/token budget.
    assert client.post("/v1/mask", json={"text": "x"}, headers=auth()).status_code == 200
    # Another owner has its own count.
    assert post_image(client, auth("synthetic-two")).status_code == 200


def test_unavailable_accounting_denies_image_work(hosted: tuple[TestClient, Calls]) -> None:
    client, calls = hosted

    def broken_clock() -> float:
        raise OSError("synthetic clock failure")

    ledger = QuotaLedger(QuotaLimits())
    ledger._clock = broken_clock
    client.app.state.hosted.quotas = ledger
    response = post_image(client, auth())
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "quota_unavailable"
    assert calls.ocr == calls.segment == 0


def test_one_image_job_per_replica(hosted: tuple[TestClient, Calls]) -> None:
    client, calls = hosted
    real = client.app.state.image_workers
    assert real is client.app.state.hosted.image_workers and real.size == 1
    client.app.state.image_workers = SimpleNamespace(running=1, size=1)
    response = post_image(client, auth())
    assert response.status_code == 429
    assert response.json()["error"]["code"] == "hosted_capacity"
    assert calls.ocr == 0


def test_masked_stamp_policy_refuses_and_hides_images() -> None:
    # Nothing on the replica finds stamps: a server that masks them refuses every image.
    app = create_app(settings(policy_overrides="STAMP=mask"))
    calls = Calls()
    local_pipeline(app, calls)
    with TestClient(app, base_url=ORIGIN) as client:
        caps = client.get("/v1/status", headers=auth()).json()["capabilities"]
        assert caps["images"] is False
        response = post_image(client, auth())
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "detection_profile_denied"
        assert "STAMP" in response.json()["error"]["message"]
        assert calls.ocr == calls.segment == calls.signature == 0


def test_kept_signatures_skip_the_signature_detector() -> None:
    app = create_app(settings(policy_overrides="SIGNATURE=keep"))
    calls = Calls()
    local_pipeline(app, calls)
    with TestClient(app, base_url=ORIGIN) as client:
        # A new project policy starts from the server's visual actions.
        store = app.state.projects.store
        project = store.default_project("synthetic-one")
        policy_id = project["default_policy_version_id"]
        assert (
            store.get_policy("synthetic-one", project["id"], policy_id)["entity_policies"][
                "SIGNATURE"
            ]
            == "keep"
        )
        response = post_image(client, auth())
        assert response.status_code == 200, response.text
        assert "SIGNATURE" not in {r["entity_type"] for r in response.json()["regions"]}
        assert calls.signature == 0


def test_owner_visual_policy_and_stricter_operator_overrides() -> None:
    owner = PolicySet({EntityType.SIGNATURE: Policy.KEEP, EntityType.FACE: Policy.KEEP})
    stored = {"entity_policies": {"SIGNATURE": "keep", "FACE": "keep"}}
    server = PolicySet()
    loose = settings()
    effective = hosted_visual_policies(stored, owner, loose, server)
    assert effective.of(EntityType.SIGNATURE) is Policy.KEEP  # the owner's choice stands
    strict = settings(policy_overrides="SIGNATURE=mask,FACE=keep")
    effective = hosted_visual_policies(stored, owner, strict, server)
    assert effective.of(EntityType.SIGNATURE) is Policy.MASK  # the stricter operator wins
    assert effective.of(EntityType.FACE) is Policy.KEEP
    # A version saved before visual types existed: the server's actions, as before.
    legacy = hosted_visual_policies({"entity_policies": {}}, owner, loose, server)
    assert legacy.of(EntityType.SIGNATURE) is Policy.MASK


def test_hosted_policies_use_the_replicas_segmenter_whatever_their_detection() -> None:
    import pii_guard.detection_profile as profile

    stamps = PolicySet({EntityType.STAMP: Policy.MASK})
    on_device, sam = settings(), sam_settings()
    # The on-device engines can't find stamps: refused before work. SAM 3.1 finds them.
    with pytest.raises(profile.DetectionProfileError, match="cannot find STAMP"):
        require_servable_visual_policies(stamps, on_device)
    require_servable_visual_policies(stamps, sam)
    require_servable_visual_policies(PolicySet(), on_device)


def test_images_capability_follows_the_operator(hosted: tuple[TestClient, Calls]) -> None:
    client, _ = hosted
    assert client.get("/v1/status", headers=auth()).json()["capabilities"]["images"] is True
    limits = client.get("/v1/account", headers=auth()).json()["limits"]
    assert limits["images_per_day"] == 20 and limits["max_image_bytes"] == 4 * 1024 * 1024
    guest = client.get("/v1/account", headers={"origin": ORIGIN}).json()["limits"]
    assert guest["images_per_day"] == 0 and guest["max_image_bytes"] == 0
    with TestClient(create_app(settings(hosted_images=False)), base_url=ORIGIN) as off:
        assert off.get("/v1/status", headers=auth()).json()["capabilities"]["images"] is False
        assert post_image(off, auth()).status_code == 403
        # Without images, readiness does not need OCR.
        off.app.state.ocr_engine = None
        assert off.get("/readyz").status_code == 200


def test_hybrid_off_or_ocr_opt_out_refused_at_startup() -> None:
    # hybrid would run a non-Meta face model next to SAM; off refuses every image (ADR 0015).
    for overrides in (
        {"segmenter": "hybrid"},
        {"segmenter": "off"},
        {"image_require_ocr": False},
    ):
        with pytest.raises(ValueError, match=r"SAM 3\.1"):
            create_app(settings(**overrides))
    create_app(settings(segmenter="local"))
    create_app(settings(segmenter="sam-api"))


def test_injected_remote_or_unknown_components_are_refused(
    hosted: tuple[TestClient, Calls],
) -> None:
    client, calls = hosted
    local = client.app.state.sam_client
    client.app.state.sam_client = SamClient(api_key="synthetic-not-a-key")
    response = post_image(client, auth())
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "detection_profile_denied"
    client.app.state.sam_client = local
    client.app.state.ocr_engine = SimpleNamespace(name="other", words=lambda image: [])
    assert post_image(client, auth()).json()["error"]["code"] == "detection_profile_denied"
    client.app.state.ocr_engine = None
    assert post_image(client, auth()).json()["error"]["code"] == "ocr_unavailable"
    assert calls.ocr == calls.segment == 0


def test_readiness_requires_ocr_and_the_local_segmenter(
    hosted: tuple[TestClient, Calls],
) -> None:
    client, _ = hosted
    assert client.get("/readyz").status_code == 200
    ocr = client.app.state.ocr_engine
    client.app.state.ocr_engine = None
    assert client.get("/readyz").status_code == 503
    client.app.state.ocr_engine = ocr
    client.app.state.sam_client = SamClient(api_key="synthetic-not-a-key")
    assert client.get("/readyz").status_code == 503


def test_no_image_payload_or_value_reaches_logs(
    hosted: tuple[TestClient, Calls], caplog: pytest.LogCaptureFixture
) -> None:
    client, _ = hosted
    data = card()
    encoded = base64.b64encode(data).decode()
    with caplog.at_level(logging.DEBUG):
        ok = post_image(client, auth(), data)
        refused = post_image(client, auth("synthetic-two"), data, session_id="s_synthetic")
    assert ok.status_code == 200 and refused.status_code == 404
    logged = "\n".join(
        record.getMessage() + " " + json.dumps(record.__dict__, default=str)
        for record in caplog.records
    )
    for secret in (TAJ_VALUE, NAME_VALUE, encoded[:64], "synthetic-one"):
        assert secret not in logged
    for response in (ok, refused):
        assert TAJ_VALUE not in response.text.replace(ok.json()["image"], "")


def test_deadline_refuses_and_a_still_running_job_keeps_the_slot(
    hosted: tuple[TestClient, Calls], monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _ = hosted
    segmenter = client.app.state.sam_client
    fast = segmenter.segment

    def slow(image: bytes, entity_types: Any = None) -> list[Region]:
        time.sleep(0.5)
        return []

    with monkeypatch.context() as patch:
        patch.setattr(
            "pii_guard.hosted.images.hosted_image_limits", lambda settings: (8_000_000, 0.05)
        )
        segmenter.segment = slow
        response = post_image(client, auth())
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "detection_failed"
        # The timed-out thread still runs: the replica's one slot is busy, no queue builds.
        busy = post_image(client, auth("synthetic-two"))
        assert busy.status_code == 429
    segmenter.segment = fast
    deadline = time.monotonic() + 5
    while client.app.state.image_workers.running and time.monotonic() < deadline:
        time.sleep(0.05)
    assert post_image(client, auth("synthetic-two")).status_code == 200


def test_a_bare_or_missing_local_segmenter_is_paired_with_signatures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import pii_guard.hosted.images as images

    bare = LocalSegmenter(detector=object())
    state = SimpleNamespace(settings=settings(), sam_client=bare)
    paired = images.hosted_segmenter(state)
    assert isinstance(paired, LocalSignatureSegmenter) and paired.local is bare
    assert images.hosted_segmenter(state) is paired  # stored, built once
    monkeypatch.setattr(
        images, "build_segmenter", lambda *a, **k: LocalSegmenter(detector=object())
    )
    built = images.hosted_segmenter(SimpleNamespace(settings=settings(), sam_client=None))
    assert isinstance(built, LocalSignatureSegmenter)
    # A pairing around anything but the built-in on-device segmenter is refused.
    impostor = LocalSignatureSegmenter(SamClient(api_key="test-key-not-a-secret"))
    with pytest.raises(Exception, match="on-device segmenter"):
        images.hosted_segmenter(SimpleNamespace(settings=settings(), sam_client=impostor))


# --- the Meta-only default: SAM 3.1 (ADR 0015, LAB-1795) -----------------------------------


class Sam:
    """The Meta Model API, in process: records each SAM prompt, answers with no region."""

    def __init__(self, status: int = 200) -> None:
        self.prompts: list[str] = []
        self.status = status

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.prompts.append(json.loads(request.content)["input"][0]["content"][0]["text"])
        if self.status != 200:
            return httpx.Response(self.status, json={"error": "synthetic failure"})
        return httpx.Response(
            200,
            json={
                "status": "completed",
                "output": [{"type": "message", "content": [{"type": "output_text", "text": ""}]}],
            },
        )


def sam_settings(**overrides: Any) -> Settings:
    """The hosted defaults: no segmenter set, so the Meta-only default applies."""
    base = settings(**overrides)
    return base.model_copy(update={"segmenter": Settings(_env_file=None).segmenter})


def sam_pipeline(app: FastAPI, sam: Sam, calls: Calls) -> None:
    app.state.sam_client = SamClient(
        api_key="synthetic-not-a-key",
        max_retries=0,
        transport=httpx.MockTransport(sam),
        settings=app.state.settings,
    )
    ocr = TesseractOcr()
    ocr.read = None  # type: ignore[assignment,method-assign]

    def words(image: Image.Image) -> list[OcrWord]:
        calls.ocr += 1
        return list(WORDS)

    ocr.words = words  # type: ignore[method-assign]
    app.state.ocr_engine = ocr


@pytest.fixture
def no_on_device_models(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail the test if a non-Meta on-device model is built (YuNet or YOLOS-tiny)."""

    def refused(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("a non-Meta on-device model was built")

    monkeypatch.setattr(LocalSegmenter, "__init__", refused)
    monkeypatch.setattr(SignatureDetector, "__init__", refused)


def test_hosted_defaults_to_sam_for_faces_id_photos_and_signatures(
    no_on_device_models: None,
) -> None:
    config = sam_settings()
    assert config.segmenter == "sam-api"
    app = create_app(config)
    sam, calls = Sam(), Calls()
    sam_pipeline(app, sam, calls)
    with TestClient(app, base_url=ORIGIN) as client:
        assert client.get("/readyz").status_code == 200
        status = client.get("/v1/status", headers=auth()).json()
        assert status["capabilities"]["images"] is True  # SAM 3.1 has its key
        response = post_image(client, auth())
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["analysis"]["sam"]["model"] == "sam-3.1"
        assert TAJ_VALUE not in body["transcript"]
    # One SAM 3.1 request per prompt: faces, ID photos and signatures (and stamps) all go to SAM.
    assert {"face", "signature", "photo of a person"} <= set(sam.prompts)
    assert calls.ocr == 1


def test_hosted_sam_default_builds_the_built_in_client(no_on_device_models: None) -> None:
    import pii_guard.hosted.images as images

    state = SimpleNamespace(settings=sam_settings(sam_api_key="synthetic-not-a-key"))
    state.sam_client = None
    built = images.hosted_segmenter(state)
    assert type(built) is SamClient and built.configured
    assert images.hosted_segmenter(state) is built  # stored, built once
    assert not hasattr(images, "local_segmenter")  # one name for the hosted segmenter


def test_hosted_sam_without_a_key_is_not_ready_and_refuses_images(
    no_on_device_models: None,
) -> None:
    app = create_app(sam_settings())
    calls = Calls()
    sam_pipeline(app, Sam(), calls)
    # No key: an emptied PII_GUARD_SAM_API_KEY, as on the offline CI stacks (LAB-1255).
    app.state.sam_client = SamClient(api_key="", settings=app.state.settings)
    with TestClient(app, base_url=ORIGIN) as client:
        assert client.get("/readyz").status_code == 503
        assert client.get("/v1/status", headers=auth()).json()["capabilities"]["images"] is False
        response = post_image(client, auth())
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "detection_failed"
        assert TAJ_VALUE not in response.text


def test_hosted_sam_failure_fails_closed_without_a_non_meta_fallback(
    no_on_device_models: None,
) -> None:
    app = create_app(sam_settings())
    sam, calls = Sam(status=500), Calls()
    sam_pipeline(app, sam, calls)
    with TestClient(app, base_url=ORIGIN) as client:
        response = post_image(client, auth())
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "detection_failed"
    assert sam.prompts  # SAM was asked; nothing else was tried after it failed
    assert TAJ_VALUE not in response.text


def test_hosted_sam_replica_refuses_an_injected_on_device_segmenter() -> None:
    app = create_app(sam_settings())
    calls = Calls()
    sam_pipeline(app, Sam(), calls)
    local_pipeline(app, calls)  # replaces the SAM client with the on-device pairing
    with TestClient(app, base_url=ORIGIN) as client:
        response = post_image(client, auth())
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "detection_profile_denied"
        assert client.get("/readyz").status_code == 503
    assert calls.segment == calls.signature == calls.ocr == 0


def test_hosted_sam_serves_a_stamp_masking_policy(no_on_device_models: None) -> None:
    # SAM 3.1 finds stamps, so a policy that masks them is served, not refused (ADR 0015).
    app = create_app(sam_settings(policy_overrides="STAMP=mask"))
    sam, calls = Sam(), Calls()
    sam_pipeline(app, sam, calls)
    with TestClient(app, base_url=ORIGIN) as client:
        assert client.get("/v1/status", headers=auth()).json()["capabilities"]["images"] is True
        response = post_image(client, auth())
    assert response.status_code == 200, response.text
    assert "stamp" in sam.prompts


def test_on_device_replica_refuses_a_stamp_masking_policy() -> None:
    # The opt-in on-device engines can't find stamps: refused before any work.
    on_device = create_app(settings(policy_overrides="STAMP=mask"))
    local_calls = Calls()
    local_pipeline(on_device, local_calls)
    with TestClient(on_device, base_url=ORIGIN) as client:
        assert client.get("/v1/status", headers=auth()).json()["capabilities"]["images"] is False
        refused = post_image(client, auth())
    assert refused.json()["error"]["code"] == "detection_profile_denied"
    assert local_calls.segment == local_calls.ocr == 0
