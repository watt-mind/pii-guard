"""Per-policy visual detection (LAB-1444): on-device signatures, and SAM only when chosen.

The YOLOS model is replaced by an in-process box function, YuNet by a fake and SAM by an
in-memory transport that records prompts, so no torch, model file or network is needed.
Every image is a blank synthetic canvas.
"""

from __future__ import annotations

import hashlib
import io
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import httpx
import pytest
from PIL import Image

from pii_guard.config import Settings
from pii_guard.policy import Policy, PolicySet
from pii_guard.projects.visual import effective_policies, stricter, visual_detection
from pii_guard.types import DetectionError, EntityType
from pii_guard.visual.masking import ImageMasker
from pii_guard.visual.regions import Box, Region
from pii_guard.visual.sam import SamClient
from pii_guard.visual.segmenters import (
    LOCAL_SIGNATURE_TYPES,
    SIGNATURE_DETECTOR,
    VISUAL_DETECTIONS,
    HybridSegmenter,
    LocalSignatureSegmenter,
    OffSegmenter,
    SignatureDetector,
    default_entity_types,
    fetch_signature_detector,
    main,
    policy_segmenter,
    sam_calls,
)


def _png(width: int = 640, height: int = 400) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (width, height), (240, 240, 240)).save(buf, format="PNG")
    return buf.getvalue()


class Faces:
    model = "yunet-2023mar"

    def __init__(self) -> None:
        self.calls: list[list[EntityType]] = []

    def segment(
        self, image: bytes, entity_types: Sequence[EntityType | str] | None = None
    ) -> list[Region]:
        types = [EntityType(t) for t in entity_types or ()]
        self.calls.append(types)
        return [Region(t, Box(70, 110, 170, 240), 0.9, "yunet") for t in types]


class Boxes:
    """YOLOS stand-in: one signature on the whole image, a duplicate on every tile."""

    def __init__(self, fail: bool = False) -> None:
        self.sizes: list[tuple[int, int]] = []
        self.fail = fail

    def __call__(self, image: Image.Image) -> list[tuple[float, float, float, float, float]]:
        self.sizes.append(image.size)
        if self.fail:
            raise RuntimeError("synthetic inference failure")
        if image.size == (640, 400):
            return [(400.0, 300.0, 520.0, 350.0, 0.9)]
        return []


class Sam:
    def __init__(self) -> None:
        self.prompts: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.prompts.append(request.url.path)
        return httpx.Response(
            200,
            json={
                "status": "completed",
                "output": [{"type": "message", "content": [{"type": "output_text", "text": ""}]}],
            },
        )

    def client(self) -> SamClient:
        return SamClient(
            api_key="test-key-not-a-secret", max_retries=0, transport=httpx.MockTransport(self)
        )


# --- the signature detector -------------------------------------------------------------------


def test_signature_detector_runs_whole_image_and_tiles_and_merges() -> None:
    boxes = Boxes()
    detector = SignatureDetector(boxes=boxes)
    regions = detector.segment(_png())
    assert len(boxes.sizes) == 5  # the whole image and 2x2 overlapping tiles
    assert [(r.entity_type, r.box, r.source) for r in regions] == [
        (EntityType.SIGNATURE, Box(400, 300, 520, 350), "yolos")
    ]


def test_signature_detector_fails_closed() -> None:
    with pytest.raises(DetectionError, match="cannot find FACE"):
        SignatureDetector(boxes=Boxes()).segment(_png(), [EntityType.FACE])
    with pytest.raises(DetectionError, match="RuntimeError"):
        SignatureDetector(boxes=Boxes(fail=True)).segment(_png())
    with pytest.raises(DetectionError, match="decoded"):
        SignatureDetector(boxes=Boxes()).segment(b"not an image")
    with pytest.raises(ValueError, match="score_threshold"):
        SignatureDetector(boxes=Boxes(), score_threshold=1.5)


def test_signature_detector_refuses_missing_or_tampered_files(tmp_path: Path) -> None:
    with pytest.raises(DetectionError, match="missing"):
        SignatureDetector(model_path=tmp_path)
    for model in SIGNATURE_DETECTOR:
        (tmp_path / model.filename).write_bytes(b"synthetic tampered file")
    with pytest.raises(DetectionError, match="SHA-256 mismatch"):
        SignatureDetector(model_path=tmp_path)


def test_signature_detector_pin_is_safetensors_at_one_revision() -> None:
    names = [m.filename for m in SIGNATURE_DETECTOR]
    assert names == ["config.json", "preprocessor_config.json", "model.safetensors"]
    revisions = {m.url.split("/resolve/")[1].split("/")[0] for m in SIGNATURE_DETECTOR}
    assert len(revisions) == 1
    assert all(len(m.sha256) == 64 and m.licence == "Apache-2.0" for m in SIGNATURE_DETECTOR)


def test_fetch_checks_every_file(tmp_path: Path) -> None:
    payloads = {m.filename: b"synthetic " + m.filename.encode() for m in SIGNATURE_DETECTOR}

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=payloads[request.url.path.rsplit("/", 1)[1]])

    with pytest.raises(DetectionError, match="SHA-256"):
        fetch_signature_detector(tmp_path, transport=httpx.MockTransport(handler))
    assert not list(tmp_path.glob("*.part"))
    assert main(["nope"]) == 2


def test_fetch_keeps_verified_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import pii_guard.visual.segmenters as segmenters
    from pii_guard.visual.segment import ModelFile

    data = b"synthetic verified file"
    pinned = tuple(
        ModelFile(m.filename, m.url, hashlib.sha256(data).hexdigest(), len(data), m.licence)
        for m in SIGNATURE_DETECTOR
    )
    monkeypatch.setattr(segmenters, "SIGNATURE_DETECTOR", pinned)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=data)

    assert fetch_signature_detector(tmp_path, transport=httpx.MockTransport(handler)) == tmp_path
    assert sorted(p.name for p in tmp_path.iterdir()) == sorted(m.filename for m in pinned)


# --- local = YuNet + signatures --------------------------------------------------------------


def test_local_signature_segmenter_splits_types_and_builds_signatures_lazily() -> None:
    faces, built = Faces(), []

    def signatures() -> SignatureDetector:
        built.append(1)
        return SignatureDetector(boxes=Boxes())

    seg = LocalSignatureSegmenter(faces, signatures=signatures)
    assert seg.model == "yunet-2023mar"
    seg.segment(_png(), [EntityType.FACE])
    assert built == []  # no signature asked for: the detector is not even loaded
    regions = seg.segment(_png(), [EntityType.FACE, EntityType.SIGNATURE, EntityType.ID_PHOTO])
    assert {r.entity_type for r in regions} == set(LOCAL_SIGNATURE_TYPES)
    assert faces.calls[-1] == [EntityType.FACE, EntityType.ID_PHOTO]
    seg.segment(_png(), [EntityType.SIGNATURE])
    assert built == [1]  # built once, reused
    assert seg.model == "yunet-2023mar+yolos-tiny-signature"
    with pytest.raises(DetectionError, match="STAMP"):
        seg.segment(_png(), [EntityType.STAMP])


def test_local_signature_segmenter_fails_closed_without_the_detector() -> None:
    def unavailable() -> SignatureDetector:
        raise DetectionError("the signature detector needs torch and transformers")

    seg = LocalSignatureSegmenter(Faces(), signatures=unavailable)
    with pytest.raises(DetectionError, match="torch"):
        seg.segment(_png(), [EntityType.FACE, EntityType.SIGNATURE])


def test_local_policy_masks_signatures_with_no_sam_call() -> None:
    sam = Sam()
    server = HybridSegmenter(sam=sam.client(), local=Faces())  # type: ignore[arg-type]
    local = LocalSignatureSegmenter(Faces(), signatures=lambda: SignatureDetector(boxes=Boxes()))
    chosen = policy_segmenter("local", server, lambda: local)
    assert chosen is local
    policies = PolicySet()
    types = default_entity_types(chosen, policies.of)
    assert EntityType.SIGNATURE in types and EntityType.STAMP not in types
    assert sam_calls(chosen, types) == 0
    outcome = ImageMasker(sam=chosen, policies=policies, ocr=None).mask(_png())
    assert EntityType.SIGNATURE in {r.entity_type for r in outcome.regions}
    assert sam.prompts == []


# --- selection: the stricter of policy and server wins ------------------------------------


def test_policy_segmenter_selection() -> None:
    sam = Sam().client()
    hybrid = HybridSegmenter(sam=sam, local=Faces())  # type: ignore[arg-type]
    local = LocalSignatureSegmenter(Faces())
    off = OffSegmenter()
    pick = lambda d, s: policy_segmenter(d, s, lambda: local)  # noqa: E731
    assert VISUAL_DETECTIONS == ("local", "sam")
    assert pick("sam", hybrid) is hybrid
    assert pick("sam", sam) is sam
    assert pick("local", hybrid) is local
    assert pick("local", sam) is local
    # A stricter server wins: a policy never turns egress on.
    assert pick("sam", Faces()) is local  # type: ignore[arg-type]
    assert pick("sam", off) is off and pick("local", off) is off
    with pytest.raises(ValueError, match="visual_detection"):
        pick("cloud", hybrid)


# --- the policy's visual actions ----------------------------------------------------------


def test_visual_detection_defaults_to_local() -> None:
    assert visual_detection(None) == "local"
    assert visual_detection({}) == "local"
    assert visual_detection({"visual_detection": "sam"}) == "sam"
    assert visual_detection({"visual_detection": "bogus"}) == "local"


def test_effective_policies() -> None:
    assert stricter(Policy.KEEP, Policy.MASK) is Policy.MASK
    assert stricter(Policy.BLOCK, Policy.MASK) is Policy.BLOCK
    stored: dict[str, Any] = {"entity_policies": {"SIGNATURE": "keep", "PERSON": "keep"}}
    project = PolicySet({EntityType.SIGNATURE: Policy.KEEP, EntityType.PERSON: Policy.KEEP})
    server = PolicySet({EntityType.FACE: Policy.KEEP})
    effective = effective_policies(stored, project, server)
    assert effective.of(EntityType.SIGNATURE) is Policy.KEEP
    assert effective.of(EntityType.PERSON) is Policy.KEEP  # text: the project's
    assert effective.of(EntityType.FACE) is Policy.KEEP  # not stored: the server's
    strict = effective_policies(stored, project, server, {EntityType.SIGNATURE: Policy.BLOCK})
    assert strict.of(EntityType.SIGNATURE) is Policy.BLOCK
    looser = effective_policies(
        {"entity_policies": {"FACE": "mask"}}, project, server, {EntityType.FACE: Policy.KEEP}
    )
    assert looser.of(EntityType.FACE) is Policy.MASK  # a looser override never unmasks


def test_settings_default_unchanged() -> None:
    # The server-wide segmenter setting is untouched; policies choose within it.
    assert Settings().segmenter == "hybrid"


# --- the self-hosted route picks per selected project policy -------------------------------


def _request(server: Any, policy: dict[str, Any] | None) -> Any:
    from types import SimpleNamespace

    state = SimpleNamespace(settings=Settings(_env_file=None), sam_client=server)
    return SimpleNamespace(
        app=SimpleNamespace(state=state), state=SimpleNamespace(project_policy=policy)
    )


def test_route_uses_the_server_segmenter_without_a_project_policy() -> None:
    from pii_guard.api.routes.image import _sam_client

    hybrid = HybridSegmenter(sam=Sam().client(), local=Faces())  # type: ignore[arg-type]
    assert _sam_client(_request(hybrid, None)) is hybrid


def test_route_local_policy_reuses_the_servers_faces_and_never_calls_sam() -> None:
    from pii_guard.api.routes.image import _sam_client
    from pii_guard.visual.segment import LocalSegmenter

    sam = Sam()
    faces = LocalSegmenter(detector=object())
    hybrid = HybridSegmenter(sam=sam.client(), local=faces)
    request = _request(hybrid, {"visual_detection": "local"})
    chosen = _sam_client(request)
    assert isinstance(chosen, LocalSignatureSegmenter) and chosen.local is faces
    assert _sam_client(request) is chosen  # built once per app
    assert _sam_client(_request(hybrid, {})) is not hybrid  # saved before the field: local
    sam_policy = _sam_client(_request(hybrid, {"visual_detection": "sam"}))
    assert sam_policy is hybrid
    assert sam.prompts == []


def test_route_builds_on_device_faces_when_the_server_has_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import pii_guard.api.routes.image as route
    from pii_guard.visual.segment import LocalSegmenter

    faces = LocalSegmenter(detector=object())
    monkeypatch.setattr(route, "build_segmenter", lambda *a, **k: faces)
    chosen = route._sam_client(_request(Sam().client(), {"visual_detection": "local"}))
    assert isinstance(chosen, LocalSignatureSegmenter) and chosen.local is faces


def test_selected_project_policy_drives_a_self_hosted_image(tmp_path: Path) -> None:
    """End to end: a project policy that keeps signatures, on-device, through the real app."""
    from fastapi.testclient import TestClient

    from pii_guard.api.app import create_app

    token = "synthetic-owner-token"  # noqa: S105 - fictional test value
    settings = Settings(
        _env_file=None,
        api_token=token,
        tenant_key=bytes(range(32)).hex(),
        project_state_path=str(tmp_path / "projects" / "state.sqlite3"),
        image_require_ocr=False,
    )
    app = create_app(settings)
    sam = Sam()
    faces = Faces()
    app.state.sam_client = HybridSegmenter(sam=sam.client(), local=faces)  # type: ignore[arg-type]
    boxes = Boxes()
    app.state.policy_local_segmenter = LocalSignatureSegmenter(
        faces, signatures=lambda: SignatureDetector(boxes=boxes)
    )
    app.state.ocr_engine = None
    headers = {"authorization": f"Bearer {token}"}
    with TestClient(app) as client:
        projects = client.get("/v1/projects", headers=headers).json()
        project = projects["default_project_id"]
        selected = {**headers, "x-pii-guard-project": project, "content-type": "image/png"}
        response = client.post("/v1/mask/image", content=_png(), headers=selected)
        assert response.status_code == 200, response.text
        types = {r["entity_type"] for r in response.json()["regions"]}
        assert "SIGNATURE" in types and "FACE" in types
        assert sam.prompts == []  # local: no SAM request
