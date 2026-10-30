"""Placeholder-labelled image masking with a shared vault session (LAB-1156).

Synthetic card from :mod:`visual_helpers` (fictional values), a perfect fake OCR engine and a
fake SAM client, so everything runs in CI without Tesseract or network.
"""

from __future__ import annotations

import base64
import io
import json
from typing import Any, ClassVar

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw
from visual_helpers import (
    FACE_BOX,
    FICTIONAL_NAME,
    FICTIONAL_TAJ,
    FICTIONAL_TAX_ID,
    SIGNATURE_BOX,
    FakeOcr,
    card_words,
    id_card_png,
    png_bytes,
)

from pii_guard.api.app import create_app
from pii_guard.config import Settings
from pii_guard.detect.rules import RuleDetector
from pii_guard.gateway import Gateway, GatewayConfig
from pii_guard.gateway.detection import build_mode_detectors
from pii_guard.policy import Policy, PolicySet
from pii_guard.types import EntityType, MaskingError, Span
from pii_guard.vault import PLACEHOLDER_RE, Vault, VaultSession
from pii_guard.visual import labels as labels_module
from pii_guard.visual.image import load_image
from pii_guard.visual.labels import VaultMatcher
from pii_guard.visual.masking import ImageMasker
from pii_guard.visual.ocr import OcrText, OcrWord, TextFinding
from pii_guard.visual.regions import Box, Region
from pii_guard.visual.render import LABEL_FILL, LABEL_INK, LabelBox, render_labels

TENANT_KEY = "0f1e2d3c4b5a69788796a5b4c3d2e1f00f1e2d3c4b5a69788796a5b4c3d2e1f0"
GOLD = (FICTIONAL_NAME, FICTIONAL_TAJ, FICTIONAL_TAJ.replace(" ", ""), FICTIONAL_TAX_ID)


class FakeSam:
    """Finds the drawn face and signature of the synthetic card."""

    model = "fake-sam"
    prompts: ClassVar[dict[EntityType, tuple[str, ...]]] = {
        EntityType.FACE: ("face",),
        EntityType.SIGNATURE: ("signature",),
    }

    def segment(self, image: bytes, entity_types: object = None) -> list[Region]:
        return [
            Region(EntityType.FACE, FACE_BOX, None, "sam"),
            Region(EntityType.SIGNATURE, SIGNATURE_BOX, None, "sam"),
        ]


def masker(words: list[OcrWord] | None = None, **kwargs: Any) -> ImageMasker:
    return ImageMasker(
        sam=FakeSam(),  # type: ignore[arg-type]
        policies=kwargs.pop("policies", PolicySet()),
        ocr=FakeOcr(words),
        text_detector=RuleDetector(),
        **kwargs,
    )


def seeded(session: VaultSession, value: str, entity_type: EntityType = EntityType.PERSON) -> str:
    """Mask a contract sentence naming ``value`` in ``session``; return its placeholder."""
    text = f"A szerződő fél: {value}, aki aláírja."
    start = text.index(value)
    span = Span(start, start + len(value), entity_type, value, 1.0, "test")
    masked = session.mask(text, [span])
    return PLACEHOLDER_RE.search(masked).group(0)  # type: ignore[union-attr]


def caps_words() -> list[OcrWord]:
    """The card's words with the name in capitals and surname-first, as on a real card."""
    out = []
    for word in card_words():
        text = {"Teszt": "TESZT", "Elek": "ELEK"}.get(word.text, word.text)
        out.append(OcrWord(text, word.box, word.line))
    return out


def all_text(outcome: Any) -> str:
    return (outcome.transcript or "") + json.dumps(outcome.summary or {}, ensure_ascii=False)


def assert_no_gold(text: str) -> None:
    for value in GOLD:
        assert value not in text, value


# --- the shared vault ---------------------------------------------------------------------------


def test_a_card_name_gets_the_placeholder_of_the_same_person_in_text() -> None:
    session = Vault(bytes.fromhex(TENANT_KEY)).session()
    in_text = seeded(session, "Teszt Elek")
    outcome = masker(caps_words()).mask(
        id_card_png(), render="labels", matcher=VaultMatcher(session)
    )
    names = [r for r in outcome.regions if r.entity_type is EntityType.PERSON]
    assert names and all(r.label is not None for r in names)
    assert {r.label.placeholder for r in names if r.label} == {in_text}
    assert names[0].label is not None and names[0].label.match in ("exact", "fuzzy")
    assert in_text in (outcome.transcript or "")
    # Faces and signatures are labelled with their kind only (no holder on this card type).
    face = next(r for r in outcome.regions if r.entity_type is EntityType.FACE)
    assert face.label is not None and face.label.label == "PHOTO"
    # The upstream answer unmasks with the session as usual.
    assert session.unmask(f"{in_text} aláírta.") == "Teszt Elek aláírta."


def test_values_first_seen_in_an_image_join_the_session() -> None:
    session = Vault(bytes.fromhex(TENANT_KEY)).session()
    outcome = masker().mask(id_card_png(), render="labels", matcher=VaultMatcher(session))
    taj = next(r for r in outcome.regions if r.entity_type is EntityType.NATIONAL_ID_HU_TAJ)
    assert taj.label is not None and taj.label.match == "new"
    # The same value later in text gets the image's placeholder.
    masked = session.mask(f"TAJ-szám: {FICTIONAL_TAJ}.", [])
    assert taj.label.placeholder in masked


def test_near_namesake_in_text_is_flagged_uncertain_not_merged() -> None:
    session = Vault(bytes.fromhex(TENANT_KEY)).session()
    other = seeded(session, "Teszt Elak")  # a different person, one real letter apart
    outcome = masker().mask(id_card_png(), render="labels", matcher=VaultMatcher(session))
    name = next(r for r in outcome.regions if r.entity_type is EntityType.PERSON)
    assert name.label is not None
    assert name.label.placeholder != other
    assert name.label.match == "uncertain"
    assert name.label.confidence is not None and name.label.confidence < 0.85


def test_known_values_are_matched_and_registered() -> None:
    from pii_guard.vault.known import KnownValue

    session = Vault(bytes.fromhex(TENANT_KEY)).session()
    session.known_values.add([KnownValue("Teszt Elek", EntityType.PERSON)])
    outcome = masker(caps_words()).mask(
        id_card_png(), render="labels", matcher=VaultMatcher(session)
    )
    name = next(r for r in outcome.regions if r.entity_type is EntityType.PERSON)
    assert name.label is not None and name.label.placeholder
    assert session.mask("Teszt Elek fizet.", []) == f"{name.label.placeholder} fizet."


def test_keep_policy_values_are_not_registered() -> None:
    session = Vault(bytes.fromhex(TENANT_KEY)).session()
    policies = PolicySet({EntityType.NATIONAL_ID_HU_TAJ: Policy.KEEP})
    masker(policies=policies).mask(id_card_png(), render="labels", matcher=VaultMatcher(session))
    assert all(t is not EntityType.NATIONAL_ID_HU_TAJ for _, t, _ in session.entities())


# --- transcript, summary, fail closed -------------------------------------------------------


def test_transcript_and_summary_hold_no_raw_values() -> None:
    session = Vault(bytes.fromhex(TENANT_KEY)).session()
    seeded(session, "Teszt Elek")
    outcome = masker().mask(id_card_png(), render="labels", matcher=VaultMatcher(session))
    assert outcome.transcript is not None and outcome.summary is not None
    assert_no_gold(all_text(outcome))
    assert_no_gold(json.dumps([r.to_public_dict() for r in outcome.regions]))
    assert "SAMPLE ID CARD" not in outcome.transcript  # heading not read by the fake OCR
    assert "TAJ:" in outcome.transcript  # captions stay, values go
    # Every placeholder in the transcript resolves in the session.
    assert not session.unmask_with_report(outcome.transcript).unresolved


def test_the_session_sweep_masks_a_value_the_transcript_let_through(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = Vault(bytes.fromhex(TENANT_KEY)).session()
    monkeypatch.setattr(
        labels_module, "_transcript", lambda words, covered, *args, **kwargs: FICTIONAL_TAJ
    )
    outcome = masker().mask(id_card_png(), render="labels", matcher=VaultMatcher(session))
    assert outcome.transcript is not None and FICTIONAL_TAJ not in outcome.transcript


def test_a_transcript_that_would_leak_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    session = Vault(bytes.fromhex(TENANT_KEY)).session()
    monkeypatch.setattr(
        labels_module, "_transcript", lambda words, covered, *args, **kwargs: FICTIONAL_TAJ
    )
    # Without both sweeps too (a defect in every layer), the leak check still stops it.
    monkeypatch.setattr(VaultSession, "mask", lambda self, text, *args, **kwargs: text)
    monkeypatch.setattr(VaultMatcher, "sweep", lambda self, text, *args: text)
    with pytest.raises(MaskingError):
        masker().mask(id_card_png(), render="labels", matcher=VaultMatcher(session))


def test_sweep_masks_values_the_conversation_named_but_no_detector_found() -> None:
    session = Vault(bytes.fromhex(TENANT_KEY)).session()
    signer = seeded(session, "Próba Ottó")
    matcher = VaultMatcher(session)
    swept = matcher.sweep("Tisztelettel:\nPRÓBA OTTÓ, TAJ 123-456-788.\nPróbaidő")
    assert swept.startswith(f"Tisztelettel:\n{signer},")
    assert "Próbaidő" in swept  # a word merely starting like a value stays
    assert matcher.sweep(signer) == signer


def badge_words() -> list[OcrWord]:
    """A visitor badge: the name has no caption, so no detector finds it."""

    def word(text: str, x: int, line: int) -> OcrWord:
        x += 300  # clear of the fake face and signature
        return OcrWord(text, Box(x, 40 * line + 10, x + 12 * len(text), 40 * line + 30), (line,))

    return [
        word("VISITOR", 20, 0),
        word("TESZT", 20, 1),
        word("ELEK", 100, 1),
        word("Teszt", 20, 2),  # a lone surname on a line of its own: not the person
        word("minta", 100, 2),
    ]


def test_find_covers_values_the_conversation_named() -> None:
    session = Vault(bytes.fromhex(TENANT_KEY)).session()
    person = seeded(session, "Teszt Elek")
    seeded(session, "Teszt Elak")  # a near-namesake must never be the one found
    outcome = masker(badge_words()).mask(
        id_card_png(), render="labels", matcher=VaultMatcher(session)
    )
    found = [r for r in outcome.regions if r.region.source == "vault"]
    assert len(found) == 1
    assert found[0].label is not None and found[0].label.placeholder == person
    assert found[0].region.box == Box(320, 50, 448, 70)
    assert outcome.transcript is not None and "TESZT" not in outcome.transcript
    assert "\nTeszt minta" in outcome.transcript


def test_find_never_covers_an_uncertain_match() -> None:
    session = Vault(bytes.fromhex(TENANT_KEY)).session()
    seeded(session, "Teszt Elemér")
    outcome = masker(badge_words()).mask(
        id_card_png(), render="labels", matcher=VaultMatcher(session)
    )
    assert not [r for r in outcome.regions if r.region.source == "vault"]


class OrganizationDetector:
    """A weaker text detector that reads the badge's person name as an organization."""

    name = "weak-ner"

    def detect(self, text: str, language: str = "hu") -> list[Span]:
        start = text.find("TESZT ELEK")
        if start < 0:
            return []
        end = start + len("TESZT ELEK")
        return [Span(start, end, EntityType.ORGANIZATION, text[start:end], 0.6, self.name)]


def test_a_known_person_read_as_a_kept_organization_is_still_masked_in_pixels() -> None:
    # LAB-1351: an ORGANIZATION/keep finding over a session-known name used to suppress the
    # vault backstop; the transcript sweep masked the name, the pixels kept it readable.
    session = Vault(bytes.fromhex(TENANT_KEY)).session()
    person = seeded(session, "Teszt Elek")
    words = badge_words()
    image = id_card_png()
    outcome = ImageMasker(
        sam=FakeSam(),  # type: ignore[arg-type]
        policies=PolicySet(),
        ocr=FakeOcr(words),
        text_detector=OrganizationDetector(),
    ).mask(image, render="labels", matcher=VaultMatcher(session))
    masked = [r for r in outcome.regions if r.policy is Policy.MASK]
    found = [r for r in masked if r.region.source == "vault"]
    assert len(found) == 1
    assert found[0].entity_type is EntityType.PERSON
    assert found[0].label is not None and found[0].label.placeholder == person
    # The kept organization finding is still reported, unmasked.
    assert any(
        r.entity_type is EntityType.ORGANIZATION and r.policy is Policy.KEEP
        for r in outcome.regions
    )
    # The name's pixels changed.
    name_box = found[0].region.box
    before = load_image(image).crop((name_box.x1, name_box.y1, name_box.x2 + 1, name_box.y2 + 1))
    after = load_image(outcome.image).crop(
        (name_box.x1, name_box.y1, name_box.x2 + 1, name_box.y2 + 1)
    )
    assert before.tobytes() != after.tobytes()
    # Transcript and pixels agree: every word the transcript masked is under a mask region.
    assert outcome.transcript is not None and person in outcome.transcript
    kept = set(outcome.transcript.split())
    for word in words:
        if word.text in kept:
            continue
        area = word.box.width * word.box.height
        assert any(
            labels_module._overlap(word.box, r.region.box) >= labels_module.WORD_COVER * area
            for r in masked
        ), word.text


def test_a_masked_finding_still_suppresses_a_duplicate_vault_find() -> None:
    session = Vault(bytes.fromhex(TENANT_KEY)).session()
    seeded(session, "Teszt Elek")
    matcher = VaultMatcher(session)
    words = badge_words()
    box = words[1].box.union(words[2].box)
    finding = TextFinding(Region(EntityType.PERSON, box, 0.9, "ner"), "TESZT ELEK", "detector")
    ocr = OcrText(words, [finding], [], [])
    assert matcher.find(ocr, frozenset({EntityType.PERSON})) == []
    kept = TextFinding(Region(EntityType.ORGANIZATION, box, 0.9, "ner"), "TESZT ELEK", "detector")
    ocr = OcrText(words, [kept], [], [])
    assert [f.region.entity_type for f in matcher.find(ocr, frozenset({EntityType.PERSON}))] == [
        EntityType.PERSON
    ]


def test_leak_check_scope() -> None:
    assert labels_module._leaks("TAJ 123-456-788", ["123 456 788"])
    assert labels_module._leaks("szerződő: TESZT ELEK", ["Teszt Elek"])
    assert not labels_module._leaks("Fiktív kiadás", ["Fiktív"])  # one word, no digit
    assert not labels_module._leaks("TAJ [[NATIONAL_ID_HU_TAJ_a1b2c3]]", ["123 456 788"])


def test_labels_need_a_matcher_and_a_known_mode() -> None:
    with pytest.raises(ValueError, match="matcher"):
        masker().mask(id_card_png(), render="labels")
    with pytest.raises(ValueError, match="render"):
        masker().mask(id_card_png(), render="blur")  # type: ignore[arg-type]


def test_opaque_mode_returns_no_transcript_or_summary() -> None:
    outcome = masker().mask(id_card_png())
    assert outcome.render == "opaque"
    assert outcome.transcript is None and outcome.summary is None
    assert all(r.label is None for r in outcome.regions)
    assert "placeholder" not in outcome.regions[0].to_public_dict()


# --- rendering -------------------------------------------------------------------------------


def magenta_png(size: tuple[int, int] = (400, 200)) -> bytes:
    image = Image.new("RGB", size, (255, 0, 255))
    return png_bytes(image)


def test_labelled_cover_leaves_no_original_pixel_and_covers_what_opaque_covers() -> None:
    boxes = [Box(10, 10, 60, 30), Box(100, 100, 380, 160), Box(300, 10, 302, 12)]
    out = render_labels(
        magenta_png(),
        [
            LabelBox(boxes[0], "[[PERSON_a1b2c3]]"),
            LabelBox(boxes[1], "PHOTO · [[PERSON_a1b2c3]]"),
            LabelBox(boxes[2], "[[PERSON_a1b2c3]]"),
        ],
    )
    image = load_image(out.image)
    for box in boxes:
        for x in range(max(0, box.x1 - 2), box.x2 + 3):
            for y in range(max(0, box.y1 - 2), box.y2 + 3):
                assert image.getpixel((x, y)) != (255, 0, 255), (x, y)
    for box, covered in zip(boxes, out.boxes, strict=True):
        assert covered is not None
        assert covered.x1 <= box.x1 - 2 and covered.x2 >= box.x2 + 2  # never smaller
    # A narrow box is extended into free space so its label stays legible.
    assert out.boxes[0] is not None and out.boxes[0].x2 > boxes[0].x2 + 2
    # The big box shows ink (a label), the 3x3 one has no room for any.
    big = image.crop((100, 100, 381, 161))
    assert big.getextrema()[0][0] < 100


def test_extension_stops_before_visible_words() -> None:
    box, obstacle = Box(10, 10, 40, 30), Box(60, 12, 90, 28)
    out = render_labels(magenta_png(), [LabelBox(box, "[[PERSON_a1b2c3]]")], obstacles=[obstacle])
    assert out.boxes[0] is not None and out.boxes[0].x2 < obstacle.x1
    image = load_image(out.image)
    assert image.getpixel((obstacle.x1, 20)) == (255, 0, 255)


def test_label_fill_is_neutral_and_output_has_no_metadata() -> None:
    out = render_labels(magenta_png(), [LabelBox(Box(0, 0, 399, 199), None)])
    image = Image.open(io.BytesIO(out.image))
    assert image.convert("RGB").getpixel((200, 100)) == LABEL_FILL
    assert not image.info.get("exif")


def test_both_modes_report_the_same_detected_boxes() -> None:
    session = Vault(bytes.fromhex(TENANT_KEY)).session()
    opaque = masker().mask(id_card_png())
    labelled = masker().mask(id_card_png(), render="labels", matcher=VaultMatcher(session))
    assert [r.region.box for r in opaque.regions] == [r.region.box for r in labelled.regions]
    for r in labelled.regions:
        if r.policy is Policy.MASK:
            assert r.cover_box is not None
            assert r.cover_box.x1 <= r.region.box.x1 and r.cover_box.x2 >= r.region.box.x2


# --- REST API --------------------------------------------------------------------------------


def make_app(tenant_key: str | None = TENANT_KEY, **state: Any) -> FastAPI:
    app = create_app(Settings(tenant_key=tenant_key))
    app.state.sam_client = FakeSam()
    app.state.ocr_engine = FakeOcr(caps_words())
    for key, value in state.items():
        setattr(app.state, key, value)
    return app


def post_card(http: TestClient, **fields: Any) -> httpx.Response:
    data = base64.b64encode(id_card_png()).decode()
    return http.post("/v1/mask/image", json={"image": data, **fields})


def test_api_default_is_labels_in_a_session_shared_with_text() -> None:
    with TestClient(make_app()) as http:
        text = http.post("/v1/mask", json={"text": "Az ügyfél neve Teszt Elek."}).json()
        # The rules detector does not find names: pre-load it as a known value instead.
        session_id = text["session_id"]
        http.post(
            f"/v1/sessions/{session_id}/known-values",
            json={"known_values": [{"value": "Teszt Elek", "entity_type": "PERSON"}]},
        ).raise_for_status()
        masked_text = http.post(
            "/v1/mask", json={"text": "Az ügyfél neve Teszt Elek.", "session_id": session_id}
        ).json()["masked_text"]
        body = post_card(http, session_id=session_id).json()
    assert body["render"] == "labels"
    assert body["session_id"] == session_id
    placeholder = PLACEHOLDER_RE.search(masked_text).group(0)  # type: ignore[union-attr]
    names = [r for r in body["regions"] if r["entity_type"] == "PERSON"]
    assert names and {r["placeholder"] for r in names} == {placeholder}
    assert placeholder in body["transcript"]
    assert body["summary"]["document_type"] is None  # the synthetic card has no title
    assert_no_gold(json.dumps(body, ensure_ascii=False).replace(body["image"], ""))


def test_api_new_session_and_opaque_flag() -> None:
    with TestClient(make_app()) as http:
        labelled = post_card(http).json()
        opaque = http.post(
            "/v1/mask/image?render=opaque",
            content=id_card_png(),
            headers={"Content-Type": "image/png"},
        ).json()
    assert labelled["session_id"] and labelled["render"] == "labels"
    assert opaque["render"] == "opaque" and opaque["session_id"] is None
    assert opaque["transcript"] is None and "placeholder" not in opaque["regions"][0]


def test_api_without_vault_falls_back_to_opaque_unless_labels_is_asked() -> None:
    with TestClient(make_app(tenant_key=None), raise_server_exceptions=False) as http:
        default = post_card(http)
        explicit = post_card(http, render="labels")
    assert default.status_code == 200 and default.json()["render"] == "opaque"
    assert explicit.status_code == 503  # like every vault endpoint without a key
    assert explicit.json()["error"]["code"] == "vault_not_configured"


def test_api_rejects_unknown_session_and_bad_options() -> None:
    with TestClient(make_app(), raise_server_exceptions=False) as http:
        unknown = post_card(http, session_id="s_" + "0" * 32)
        bad = post_card(http, render="blur")
    assert unknown.status_code == 404
    assert bad.status_code == 422


# --- gateway ---------------------------------------------------------------------------------


def test_gateway_sends_labelled_image_with_transcript_and_masks_text_seen_in_the_image() -> None:
    forwarded: list[dict[str, Any]] = []

    def upstream(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        forwarded.append(body)
        names = [m.group(0) for m in PLACEHOLDER_RE.finditer(json.dumps(body))]
        answer = f"Ez a kártya: {names[0]}" if names else "?"
        return httpx.Response(
            200,
            json={"choices": [{"index": 0, "message": {"role": "assistant", "content": answer}}]},
        )

    settings = Settings(
        tenant_key=TENANT_KEY, upstream_base_url="http://up.invalid/v1", upstream_api_key="k"
    )
    config = GatewayConfig(mode="fast")
    app = create_app(settings)
    app.state.gateway = Gateway(
        settings=settings,
        vault=Vault.from_settings(settings),
        config=config,
        detectors=build_mode_detectors(settings, config),
        transport=httpx.MockTransport(upstream),
        sam=FakeSam(),  # type: ignore[arg-type]
        ocr=FakeOcr(caps_words()),
    )
    url = "data:image/png;base64," + base64.b64encode(id_card_png()).decode()
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "Kié ez a kártya? Teszt Elek küldte."},
                {"type": "image_url", "image_url": {"url": url}},
            ],
        }
    ]
    with TestClient(app) as http:
        response = http.post("/v1/chat/completions", json={"model": "m", "messages": messages})
    assert response.status_code == 200, response.text
    parts = forwarded[0]["messages"][-1]["content"]
    assert [p["type"] for p in parts] == ["text", "image_url", "text"]
    annotation = parts[2]["text"]
    assert "Document summary:" in annotation and "Masked transcript:" in annotation
    raw = json.dumps(forwarded[0], ensure_ascii=False)
    assert "Teszt Elek" not in raw and "TESZT" not in raw and FICTIONAL_TAJ not in raw
    # The name was first found on the card; the text's mention got the same placeholder.
    text_placeholder = PLACEHOLDER_RE.search(parts[0]["text"]).group(0)  # type: ignore[union-attr]
    assert text_placeholder in annotation
    # The answer is restored on the way back.
    assert "TESZT ELEK" in response.json()["choices"][0]["message"]["content"].upper()


def test_gateway_opaque_setting_sends_no_annotation() -> None:
    forwarded: list[dict[str, Any]] = []

    def upstream(request: httpx.Request) -> httpx.Response:
        forwarded.append(json.loads(request.content))
        return httpx.Response(
            200, json={"choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"}}]}
        )

    settings = Settings(
        tenant_key=TENANT_KEY,
        upstream_base_url="http://up.invalid/v1",
        upstream_api_key="k",
        image_render="opaque",
    )
    config = GatewayConfig(mode="fast")
    app = create_app(settings)
    app.state.gateway = Gateway(
        settings=settings,
        vault=Vault.from_settings(settings),
        config=config,
        detectors=build_mode_detectors(settings, config),
        transport=httpx.MockTransport(upstream),
        sam=FakeSam(),  # type: ignore[arg-type]
        ocr=FakeOcr(),
    )
    url = "data:image/png;base64," + base64.b64encode(id_card_png()).decode()
    messages = [{"role": "user", "content": [{"type": "image_url", "image_url": url}]}]
    with TestClient(app) as http:
        assert http.post(
            "/v1/chat/completions", json={"model": "m", "messages": messages}
        ).is_success
    assert [p["type"] for p in forwarded[0]["messages"][-1]["content"]] == ["image_url"]


def _name_line(text: str) -> list[OcrWord]:
    """One OCR line ``Name: …`` on the synthetic card, word by word."""
    out, x = [], 240
    for word in text.split(" "):
        out.append(OcrWord(word, Box(x, 90, x + 10 * len(word), 110), (0,)))
        x += 10 * len(word) + 8
    return out


@pytest.mark.parametrize(
    ("in_text", "on_card"),
    [
        ("Kovács Ella", "Name: KOVÁCS ELIA"),  # a capital I is not a capital L
        ("Hell Anna", "Name: HEIL ANNA"),
        ("Kovács Anna", "Name: KOVÁCS ANNA ZSÓFIA"),  # a name the text does not have
    ],
)
def test_a_card_never_reuses_a_near_namesakes_placeholder(in_text: str, on_card: str) -> None:
    # LAB-1211: these were merged (fuzzy 0.95): the card's placeholder unmasked to the
    # contract's person. Now the card gets its own placeholder, flagged uncertain.
    session = Vault(bytes.fromhex(TENANT_KEY)).session()
    placeholder = seeded(session, in_text)
    outcome = masker(_name_line(on_card)).mask(
        id_card_png(), "hu", render="labels", matcher=VaultMatcher(session, "hu")
    )
    labels = [r.label for r in outcome.regions if r.label and r.label.placeholder]
    assert labels, outcome.regions
    assert all(label.placeholder != placeholder for label in labels)
    person = next(
        r.label for r in outcome.regions if r.entity_type is EntityType.PERSON and r.label
    )
    assert person.match == "uncertain"
    assert session.unmask(person.placeholder or "") == on_card.removeprefix("Name: ")


def test_draw_helper_is_fictional() -> None:
    # Guard: the synthetic card stays fictional and small.
    image = Image.open(io.BytesIO(id_card_png()))
    ImageDraw.Draw(image)
    assert image.size == (640, 400)


# --- expiry in the transcript (LAB-1196) --------------------------------------------------------


def _expiry_ocr() -> OcrText:
    """Two OCR lines: a caption line and the card's expiry date (a non-personal field)."""
    from pii_guard.visual.captions import CaptionValue

    caption = OcrWord("Expiry", Box(10, 10, 70, 26), (0,))
    date = OcrWord("2020.01.01.", Box(80, 10, 170, 26), (0,))
    field = CaptionValue(
        caption="Expiry",
        language="hu",
        entity_type=None,
        box=date.box,
        caption_box=caption.box,
        words=(date,),
    )
    return OcrText([caption, date], [], [], [field])


def test_transcript_reduces_the_expiry_date_by_default() -> None:
    from pii_guard.visual.labels import label_image

    session = Vault(bytes.fromhex(TENANT_KEY)).session()
    outcome = label_image(_expiry_ocr(), [], VaultMatcher(session, "hu"))
    assert outcome.transcript == "Expiry [EXPIRY]"
    assert "2020" not in outcome.transcript
    assert outcome.summary["expired"] is True
    assert outcome.summary["expiry"] is None


def test_transcript_keeps_the_expiry_date_when_asked() -> None:
    from pii_guard.visual.labels import label_image

    session = Vault(bytes.fromhex(TENANT_KEY)).session()
    outcome = label_image(_expiry_ocr(), [], VaultMatcher(session, "hu"), expiry="keep")
    assert outcome.transcript == "Expiry 2020.01.01."
    assert outcome.summary["expiry"] == "2020-01-01"


# --- nested duplicate labels and photo caption clipping (LAB-1488) ------------------------------


@pytest.mark.parametrize("inner_first", [False, True])
def test_nested_same_label_cover_has_one_outline_and_preserves_coverage(inner_first: bool) -> None:
    # LAB-1688: the face must not leave a second outline inside its masked ID photo.
    image = magenta_png((400, 200))
    outer = LabelBox(Box(10, 10, 300, 150), "PHOTO · [[PERSON_a1b2c3]]")
    inner = LabelBox(Box(60, 30, 200, 120), "PHOTO · [[PERSON_a1b2c3]]")
    boxes = [inner, outer] if inner_first else [outer, inner]
    out = render_labels(image, boxes)
    assert out.image == render_labels(image, [outer]).image
    assert out.boxes == [_padded(item.box) for item in boxes]
    assert _magenta_pixels(out.image, [_padded(outer.box), _padded(inner.box)]) == 0
    assert load_image(out.image).getpixel((inner.box.x1 - 2, inner.box.y1 - 2)) == LABEL_FILL


@pytest.mark.parametrize("label", ["PHOTO · [[PERSON_d4e5f6]]", "[[PERSON_a1b2c3]]", None])
def test_nested_independent_cover_keeps_its_outline(label: str | None) -> None:
    outer = LabelBox(Box(10, 10, 300, 150), "PHOTO · [[PERSON_a1b2c3]]")
    inner = LabelBox(Box(60, 30, 200, 120), label)
    out = render_labels(magenta_png((400, 200)), [outer, inner])
    assert load_image(out.image).getpixel((inner.box.x1 - 2, inner.box.y1 - 2)) == LABEL_INK


@pytest.mark.parametrize("photo_policy", [Policy.MASK, Policy.KEEP])
def test_photo_outline_suppression_respects_policy_and_preserves_signature(
    photo_policy: Policy,
) -> None:
    class PhotoSam(FakeSam):
        def segment(self, image: bytes, entity_types: object = None) -> list[Region]:
            return [
                Region(EntityType.ID_PHOTO, Box(20, 40, 210, 260), None, "sam"),
                *super().segment(image, entity_types),
            ]

    session = Vault(bytes.fromhex(TENANT_KEY)).session()
    outcome = ImageMasker(
        sam=PhotoSam(),  # type: ignore[arg-type]
        policies=PolicySet({EntityType.ID_PHOTO: photo_policy, EntityType.SIGNATURE: Policy.MASK}),
        ocr=FakeOcr([]),
        text_detector=RuleDetector(),
    ).mask(magenta_png((640, 400)), render="labels", matcher=VaultMatcher(session))
    photo, face, signature = (
        next(r for r in outcome.regions if r.entity_type is kind)
        for kind in (EntityType.ID_PHOTO, EntityType.FACE, EntityType.SIGNATURE)
    )
    assert photo.policy is photo_policy
    assert face.policy is Policy.MASK and face.cover_box is not None
    assert signature.policy is Policy.MASK and signature.cover_box is not None
    assert _magenta_pixels(outcome.image, [face.cover_box, signature.cover_box]) == 0
    expected = LABEL_FILL if photo_policy is Policy.MASK else LABEL_INK
    assert load_image(outcome.image).getpixel((face.cover_box.x1, face.cover_box.y1)) == expected
    if photo_policy is Policy.MASK:
        assert photo.cover_box is not None
        assert _magenta_pixels(outcome.image, [photo.cover_box]) == 0
    else:
        assert photo.cover_box is None


def test_nested_different_labels_still_print_both() -> None:
    image = magenta_png((400, 200))
    outer = LabelBox(Box(10, 10, 300, 150), "PHOTO · [[PERSON_a1b2c3]]")
    inner = LabelBox(Box(60, 30, 200, 120), "[[PERSON_a1b2c3]]")
    assert (
        render_labels(image, [outer, inner]).image
        != render_labels(image, [outer, LabelBox(inner.box, None)]).image
    )


def test_photo_cover_is_clipped_at_swallowed_caption_starts() -> None:
    from pii_guard.visual.masking import clip_photo

    photo = Region(EntityType.ID_PHOTO, Box(10, 79, 329, 561), 0.95, "yunet")
    face = Box(87, 120, 253, 410)
    caption = OcrWord("Családi", Box(290, 110, 360, 125), (0,))
    inside = OcrWord("smudge", Box(300, 200, 320, 220), (1,))  # fully inside: not a start
    left = OcrWord("KÁRTYA", Box(40, 40, 120, 60), (2,))  # left of the face: untouched
    clipped = clip_photo(photo, face, [caption, inside, left])
    assert clipped.box == Box(10, 79, 287, 561)
    assert clipped.entity_type is EntityType.ID_PHOTO and clipped.source == "yunet"


def test_photo_cover_never_shrinks_past_its_face() -> None:
    from pii_guard.visual.masking import _clip_photos, clip_photo

    photo = Region(EntityType.ID_PHOTO, Box(10, 79, 329, 561), 0.95, "yunet")
    face = Box(87, 120, 253, 410)
    assert clip_photo(photo, None, [OcrWord("Családi", Box(290, 110, 360, 125), (0,))]) is photo
    assert clip_photo(photo, face, []) is photo
    # A word starting left of the face's right edge is no caption start: unchanged.
    assert clip_photo(photo, face, [OcrWord("Családi", Box(200, 110, 400, 125), (0,))]) is photo
    regions = [
        photo,
        Region(EntityType.FACE, face, 0.95, "yunet"),
    ]
    (clipped, *_) = _clip_photos(regions, [OcrWord("Családi", Box(290, 110, 360, 125), (0,))])
    assert clipped.box.x2 == 287


def test_label_image_invalid_mrz_matches_existing_and_fixes() -> None:
    from pii_guard.visual.labels import label_image
    from pii_guard.visual.mrz import MrzData, MrzZone

    session = Vault(bytes.fromhex(TENANT_KEY)).session()
    ph = session.mask("123456AB", [Span(0, 8, EntityType.ID_DOCUMENT, "123456AB", 1.0, "rules")])

    mrz = MrzData(
        format="td1",
        document_code="I",
        issuing_state="HUN",
        document_number="123456AB",
        nationality="HUN",
        birth="800101",
        expiry="300101",
        surname="KOVACS",
        given="JANOS",
        valid=False,
        number_check="5",
    )
    zone = MrzZone(
        Region(EntityType.ID_DOCUMENT, Box(0, 0, 10, 10), 1.0, "ocr"), ("l1", "l2", "l3")
    )
    ocr = OcrText([], [], [zone], [])

    orig_parse = labels_module.parse_mrz
    orig_fixes = labels_module.mrz_number_fixes
    try:
        labels_module.parse_mrz = lambda lines: mrz
        matcher = VaultMatcher(session, "hu")
        outcome = label_image(ocr, [], matcher)
        assert outcome.summary.get("document_number") == ph

        mrz_confused = MrzData(
            format="td1",
            document_code="I",
            issuing_state="HUN",
            document_number="I23456AB",
            nationality="HUN",
            birth="800101",
            expiry="300101",
            surname="KOVACS",
            given="JANOS",
            valid=False,
            number_check="5",
        )
        labels_module.parse_mrz = lambda lines: mrz_confused
        labels_module.mrz_number_fixes = lambda m: ["123456AB"]
        matcher2 = VaultMatcher(session, "hu")
        outcome2 = label_image(ocr, [], matcher2)
        assert outcome2.summary.get("document_number") == ph
    finally:
        labels_module.parse_mrz = orig_parse
        labels_module.mrz_number_fixes = orig_fixes


# --- one readable label per overlapping finding (LAB-1672) --------------------------------------
# Observed on the English synthetic ID (eval/fixtures/visual/images/en-id_card-front.png):
# the caption read and the NER read of one value, a few pixels apart or running along the row.
DOB_CAPTION = Box(320, 221, 453, 240)
DOB_NER = Box(321, 222, 662, 239)
ID_CAPTION = Box(319, 264, 429, 294)
ID_NER = Box(321, 266, 695, 292)
CARD_SIZE = (1012, 638)
FICTIONAL_DOCUMENT = "ZX123456"


def _padded(box: Box, padding: int = 2) -> Box:
    return Box(box.x1 - padding, box.y1 - padding, box.x2 + padding, box.y2 + padding)


def _magenta_pixels(image: bytes, boxes: list[Box]) -> int:
    """Original (magenta) pixels left inside any of ``boxes``."""
    decoded = load_image(image).convert("RGB")
    return sum(
        decoded.getpixel((x, y)) == (255, 0, 255)
        for box in boxes
        for x in range(box.x1, box.x2 + 1)
        for y in range(box.y1, box.y2 + 1)
    )


def _document_row(
    caption_text: str = FICTIONAL_DOCUMENT, ner_text: str = f"{FICTIONAL_DOCUMENT} UTO"
) -> tuple[OcrText, list[tuple[Region, Policy]]]:
    words = [
        OcrWord(FICTIONAL_DOCUMENT, Box(321, 266, 427, 292), (0,)),
        OcrWord("UTO", Box(650, 266, 695, 292), (0,)),
    ]
    caption = Region(EntityType.ID_DOCUMENT, ID_CAPTION, None, "ocr")
    ner = Region(EntityType.ID_DOCUMENT, ID_NER, 0.9, "ocr")
    findings = [
        TextFinding(caption, caption_text, "caption", "Document no."),
        TextFinding(ner, ner_text, "detector"),
    ]
    return OcrText(words, findings, [], []), [(caption, Policy.MASK), (ner, Policy.MASK)]


def test_overlapping_reads_of_one_value_share_one_placeholder() -> None:
    from pii_guard.visual.labels import label_image

    session = Vault(bytes.fromhex(TENANT_KEY)).session()
    ocr, covered = _document_row()
    outcome = label_image(ocr, covered, VaultMatcher(session, "en"))
    caption_label, ner_label = outcome.labels
    assert caption_label == ner_label and caption_label.placeholder is not None
    # Neither was in the conversation: the caption read (the tight box) wins.
    assert caption_label.label == session.mask(
        FICTIONAL_DOCUMENT, [Span(0, 8, EntityType.ID_DOCUMENT, FICTIONAL_DOCUMENT, 1.0, "x")]
    )
    assert outcome.transcript == caption_label.placeholder  # one token, not two


def test_unified_label_prefers_the_placeholder_the_conversation_already_holds() -> None:
    from pii_guard.visual.labels import label_image

    session = Vault(bytes.fromhex(TENANT_KEY)).session()
    wide = f"{FICTIONAL_DOCUMENT} UTO"
    in_text = session.mask(wide, [Span(0, len(wide), EntityType.ID_DOCUMENT, wide, 1.0, "ner")])
    ocr, covered = _document_row()
    outcome = label_image(ocr, covered, VaultMatcher(session, "en"))
    assert [label.placeholder for label in outcome.labels] == [in_text, in_text]
    # The summary follows the winner, not the caption read's losing placeholder.
    assert outcome.summary["document_number"] == in_text


def test_adjacent_distinct_values_keep_their_own_labels() -> None:
    from pii_guard.visual.labels import label_image

    session = Vault(bytes.fromhex(TENANT_KEY)).session()
    left = Region(EntityType.ID_DOCUMENT, Box(100, 50, 200, 70), None, "ocr")
    right = Region(EntityType.ID_DOCUMENT, Box(197, 50, 300, 70), None, "ocr")  # 4 px overlap
    ocr = OcrText(
        [OcrWord("ZX123456", left.box, (0,)), OcrWord("QY654321", right.box, (0,))],
        [TextFinding(left, "ZX123456", "detector"), TextFinding(right, "QY654321", "detector")],
        [],
        [],
    )
    outcome = label_image(
        ocr, [(left, Policy.MASK), (right, Policy.MASK)], VaultMatcher(session, "en")
    )
    assert outcome.labels[0].placeholder != outcome.labels[1].placeholder
    # Rendered with the same label they still print twice: low overlap is not one value.
    image = magenta_png()
    same = [
        LabelBox(left.box, "[[ID_DOCUMENT_a1b2c3]]"),
        LabelBox(right.box, "[[ID_DOCUMENT_a1b2c3]]"),
    ]
    assert (
        render_labels(image, same).image
        != render_labels(image, [same[0], LabelBox(right.box, None)]).image
    )


def test_same_label_near_identical_boxes_print_one_label_over_their_union() -> None:
    image = magenta_png(CARD_SIZE)
    label = "[[DATE_OF_BIRTH_a1b2c3]]"
    out = render_labels(image, [LabelBox(DOB_CAPTION, label), LabelBox(DOB_NER, label)])
    union = DOB_CAPTION.union(DOB_NER)
    assert out.image == render_labels(image, [LabelBox(union, label)]).image
    assert out.boxes == [_padded(union), _padded(union)]


def test_observed_card_rows_render_one_readable_label_each() -> None:
    from pii_guard.visual.labels import label_image

    session = Vault(bytes.fromhex(TENANT_KEY)).session()
    ocr, covered = _document_row()
    id_labels = label_image(ocr, covered, VaultMatcher(session, "en")).labels
    dob = "[[DATE_OF_BIRTH_a1b2c3]]"
    items = [
        LabelBox(DOB_CAPTION, dob),
        LabelBox(DOB_NER, dob),
        LabelBox(ID_CAPTION, id_labels[0].label),
        LabelBox(ID_NER, id_labels[1].label),
    ]
    image = magenta_png(CARD_SIZE)
    out = render_labels(image, items)
    expected = render_labels(
        image,
        [
            LabelBox(DOB_CAPTION.union(DOB_NER), dob),
            LabelBox(ID_CAPTION.union(ID_NER), id_labels[0].label),
        ],
    )
    assert out.image == expected.image


def test_unified_covers_keep_every_originally_covered_pixel() -> None:
    image = magenta_png(CARD_SIZE)
    boxes = [DOB_CAPTION, DOB_NER, ID_CAPTION, ID_NER]
    items = [
        LabelBox(DOB_CAPTION, "[[DATE_OF_BIRTH_a1b2c3]]"),
        LabelBox(DOB_NER, "[[DATE_OF_BIRTH_a1b2c3]]"),
        LabelBox(ID_CAPTION, "[[ID_DOCUMENT_d4e5f6]]"),
        LabelBox(ID_NER, "[[ID_DOCUMENT_d4e5f6]]"),
    ]
    out = render_labels(image, items)
    assert _magenta_pixels(out.image, [_padded(b) for b in boxes]) == 0
    for box, covered in zip(boxes, out.boxes, strict=True):
        assert covered is not None
        assert covered.union(_padded(box)) == covered  # every reported cover holds its box


def test_a_wide_read_over_two_values_never_merges_them() -> None:
    # [A, N, B]: N runs over two distinct numbers. It must not hand A's placeholder to B's
    # word, and B's value must stay B in the transcript.
    from pii_guard.visual.labels import label_image

    session = Vault(bytes.fromhex(TENANT_KEY)).session()
    a_box, b_box, n_box = Box(100, 50, 200, 70), Box(220, 50, 320, 70), Box(100, 50, 320, 70)
    a = Region(EntityType.ID_DOCUMENT, a_box, None, "ocr")
    n = Region(EntityType.ID_DOCUMENT, n_box, None, "ocr")
    b = Region(EntityType.ID_DOCUMENT, b_box, None, "ocr")
    ocr = OcrText(
        [OcrWord("ZX123456", a_box, (0,)), OcrWord("QY654321", b_box, (0,))],
        [
            TextFinding(a, "ZX123456", "detector"),
            TextFinding(n, "ZX123456 QY654321", "detector"),
            TextFinding(b, "QY654321", "detector"),
        ],
        [],
        [],
    )
    covered = [(a, Policy.MASK), (n, Policy.MASK), (b, Policy.MASK)]
    outcome = label_image(ocr, covered, VaultMatcher(session, "en"))
    first, wide, last = (label.placeholder for label in outcome.labels)
    assert len({first, wide, last}) == 3
    assert session.unmask(outcome.transcript) == "ZX123456 QY654321"


def test_reads_that_disagree_keep_their_own_placeholders() -> None:
    # The conversation holds ZX123457 UTO; the caption read ZX123456 is another number and
    # must not be restored as the conversation's one.
    from pii_guard.visual.labels import label_image

    session = Vault(bytes.fromhex(TENANT_KEY)).session()
    other = "ZX123457 UTO"
    in_text = session.mask(other, [Span(0, len(other), EntityType.ID_DOCUMENT, other, 1.0, "ner")])
    ocr, covered = _document_row(ner_text=other)
    caption_label, ner_label = label_image(ocr, covered, VaultMatcher(session, "en")).labels
    assert ner_label.placeholder == in_text
    assert caption_label.placeholder != in_text
    assert session.unmask(caption_label.placeholder or "") == FICTIONAL_DOCUMENT


def test_an_uncertain_read_never_takes_another_reads_placeholder() -> None:
    from pii_guard.visual.labels import RegionLabel, _unify

    caption = Region(EntityType.ID_DOCUMENT, ID_CAPTION, None, "ocr")
    ner = Region(EntityType.ID_DOCUMENT, ID_NER, None, "ocr")
    labels = [
        RegionLabel("[[ID_DOCUMENT_a1b2c3]]", "[[ID_DOCUMENT_a1b2c3]]", "exact", 1.0),
        RegionLabel("[[ID_DOCUMENT_d4e5f6]]", "[[ID_DOCUMENT_d4e5f6]]", "uncertain", 0.7),
    ]
    reads = {0: ("caption", FICTIONAL_DOCUMENT), 1: ("detector", f"{FICTIONAL_DOCUMENT} UTO")}
    out, winners = _unify(
        [(caption, Policy.MASK), (ner, Policy.MASK)], labels, reads, frozenset({"x"})
    )
    assert out == labels and winners == {}


@pytest.mark.parametrize("seed", range(4))
def test_labelled_covers_never_leave_a_detected_pixel_visible(seed: int) -> None:
    # Randomized layouts: nested covers sharing a right edge, chains of three or more
    # overlapping reads, boxes clipped at the image edge, same and different labels.
    import random

    rnd = random.Random(seed)  # noqa: S311 - layout fuzzing, not cryptography
    width, height = 220, 90
    image = magenta_png((width, height))
    labels = ["[[DATE_OF_BIRTH_a1b2c3]]", "[[ID_DOCUMENT_d4e5f6]]", None]
    for _ in range(60):
        items: list[LabelBox] = []
        for _ in range(rnd.randint(2, 6)):
            shape = rnd.random()
            if items and shape < 0.3:  # nested, sharing the right edge
                o = items[-1].box
                x1 = rnd.randint(o.x1, o.x2)
                box = Box(x1, rnd.randint(o.y1, o.y2), o.x2, o.y2)
            elif items and shape < 0.6:  # the next link of a chain along the row
                o = items[-1].box
                x1 = min(width - 1, o.x1 + rnd.randint(1, max(1, o.width)))
                box = Box(x1, o.y1, min(width - 1, x1 + rnd.randint(2, 80)), o.y2)
            else:  # anywhere, often against the image edge
                x1, y1 = rnd.randint(0, width - 3), rnd.randint(0, height - 3)
                box = Box(
                    x1, y1, min(width - 1, x1 + rnd.randint(2, 150)), min(height - 1, y1 + 30)
                )
            items.append(LabelBox(box, rnd.choice(labels)))
        out = render_labels(image, items)
        padded = [
            Box(
                max(0, b.x1 - 2),
                max(0, b.y1 - 2),
                min(width - 1, b.x2 + 2),
                min(height - 1, b.y2 + 2),
            )
            for b in (i.box for i in items)
        ]
        assert _magenta_pixels(out.image, padded) == 0, items
