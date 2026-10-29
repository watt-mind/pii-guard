"""Record the landing's labels-mode image showcase (LAB-1484).

The landing (``ui/src/hosted/ImageShowcase.tsx``, ``HeroImage.tsx``) shows what the default
``render="labels"`` does to the fictional specimen ID card ``ui/public/samples/id-card.png``
(``eval/fixtures/visual/images/hu-id_card-front.png``): each text value covered by a box with
its vault placeholder printed in it, the face and ID photo covered, and the masked transcript
and document summary that go to the model with the image. This script makes that recording
with the real API, configured like the hosted preview (ADR 0014): the on-device ``local``
segmenter (YuNet), the built-in Tesseract OCR, the ``rules`` detector, signatures and stamps
kept.

One vault session, as an application would use it: the party is pre-loaded as a known value,
the user's message is masked (``/v1/mask``), then the image (``/v1/mask/image``), so the
holder's name gets the same placeholder in the text and on the card. A stand-in model answers
from the masked summary only (like :func:`pii_guard.eval.visual_labels.demo_mock_answer`), and
the answer is restored with ``/v1/unmask`` to check the round trip.

The written JSON is value-free: the masked message, the regions (``to_public_dict``, plus the
label's lines and font size from :func:`pii_guard.visual.render.fit_label`, so the browser
draws it at the server's size), the transcript, the summary and the masked answer. The script
fails if any printed value of the card (``eval/fixtures/visual/generation.json``) or the
message's name would be written. Needs the ``ocr`` and ``local-vision`` extras and the
``tesseract`` binary::

    uv run --no-sync python scripts/record_image_labels.py            # writes the recording
    uv run --no-sync python scripts/record_image_labels.py --check    # compares, writes nothing
"""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import json
import secrets
import sys
import unicodedata
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from pii_guard.api.app import create_app
from pii_guard.config import Settings
from pii_guard.eval.visual_labels import load_gold
from pii_guard.vault import PLACEHOLDER_RE
from pii_guard.visual.render import fit_label

ROOT = Path(__file__).resolve().parent.parent
SAMPLE = ROOT / "ui" / "public" / "samples" / "id-card.png"
FIXTURE_ID = "hu-id_card-front"
OUT = ROOT / "ui" / "src" / "content" / "imageLabelsRecording.json"
#: The fictional holder printed on the card, pre-loaded as the application's known party.
HOLDER = "Fiktív Mária"
#: The user's message. Keep in step with MESSAGE in ui/src/hosted/ImageShowcase.tsx.
MESSAGE = f"{HOLDER} is the seller. Is her ID card attached, and is it still valid?"


def stand_in_answer(summary: dict[str, Any]) -> str:
    """What a model can answer from the masked summary alone (placeholders, no values)."""
    holder = summary.get("holder")
    if not holder:
        return "No ID card for the seller is attached."
    state = "it has expired" if summary.get("expired") else "it has not expired"
    return f"Yes: the attached ID card belongs to {holder}, and {state}."


def _fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


#: Words of a value that the card also prints as ordinary text: its footer reads "MI által
#: generált fiktív minta" (AI-generated fictional specimen), and the surname is "Fiktív".
BOILERPLATE = frozenset({"fiktiv"})


def assert_value_free(recording: dict[str, Any]) -> None:
    """Fail if a printed value of the card (whole, digits only, or a word of it) is in the
    recording. Prints counts only, never the value."""
    blob = _fold(json.dumps(recording, ensure_ascii=False))
    digits = "".join(c for c in blob if c.isdigit())
    values = [*load_gold()[FIXTURE_ID].values(), HOLDER]
    needles = {_fold(v) for v in values}
    needles |= {_fold(w) for v in values for w in v.split() if len(w) >= 4} - BOILERPLATE
    found = [n for n in needles if n in blob]
    for value in values:
        number = "".join(c for c in value if c.isdigit())
        if len(number) >= 6 and number in digits:
            found.append(value)
    if found:
        raise SystemExit(f"recording would contain {len(found)} value(s); nothing written")


def _label_fit(region: dict[str, Any]) -> dict[str, Any]:
    """The label's lines and font size exactly as the server printed them."""
    if not region.get("label") or not region.get("cover_box"):
        return {}
    x1, y1, x2, y2 = region["cover_box"]
    draw = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    fitted = fit_label(draw, region["label"], x2 - x1 + 1, y2 - y1 + 1)
    if fitted is None:
        return {"label_lines": [], "label_px": None}
    lines, size = fitted
    return {"label_lines": lines, "label_px": size}


def record() -> dict[str, Any]:
    settings = Settings(
        tenant_key=secrets.token_hex(32),
        segmenter="local",
        image_render="labels",
        detectors=("rules",),
        policy_overrides={"SIGNATURE": "keep", "STAMP": "keep"},
    )
    app = create_app(settings)
    png = SAMPLE.read_bytes()
    with TestClient(app, base_url="http://127.0.0.1") as http:
        created = http.post(
            "/v1/sessions", json={"known_values": [{"value": HOLDER, "entity_type": "PERSON"}]}
        )
        created.raise_for_status()
        session = created.json()["session_id"]
        text = http.post(
            "/v1/mask", json={"text": MESSAGE, "language": "en", "session_id": session}
        )
        text.raise_for_status()
        image = http.post(
            "/v1/mask/image",
            json={
                "image": base64.b64encode(png).decode("ascii"),
                "language": "hu",
                "session_id": session,
                "render": "labels",
            },
        )
        image.raise_for_status()
        body = image.json()
        answer = stand_in_answer(body["summary"] or {})
        restored = http.post("/v1/unmask", json={"text": answer, "session_id": session})
        restored.raise_for_status()
    back = restored.json()
    back_text = back.get("text") or back.get("unmasked_text") or ""
    if PLACEHOLDER_RE.search(back_text) or HOLDER not in back_text:
        raise SystemExit("the answer did not restore")
    if body["analysis"]["ocr"]["engine"] != "tesseract" or body["render"] != "labels":
        raise SystemExit("needs Tesseract and labels rendering")
    regions = [{**r, **_label_fit(r)} for r in body["regions"]]
    return {
        "recorded": dt.date.today().isoformat(),
        "note": (
            "scripts/record_image_labels.py: POST /v1/mask/image with render=labels on "
            "ui/public/samples/id-card.png (fictional specimen), configured like the hosted "
            "preview (segmenter local/YuNet, Tesseract, rules; signatures and stamps kept), in "
            "the session that masked the message. Value-free: placeholders only, no image."
        ),
        "message": {"masked": text.json()["masked_text"]},
        "image": {
            "media_type": body["media_type"],
            "width": body["width"],
            "height": body["height"],
            "regions": regions,
            "masked": body["masked"],
            "kept": body["kept"],
            "analysis": body["analysis"],
            "transcript": body["transcript"],
            "summary": body["summary"],
            "matches": body["matches"],
        },
        "answer": {"masked": answer, "by": "stand-in model reading the masked summary"},
    }


def _comparable(recording: dict[str, Any]) -> str:
    """The recording without what changes from run to run by design: the date, the
    session-random placeholder ids, and the label fit and box extension that depend on them."""
    rec = json.loads(json.dumps({k: v for k, v in recording.items() if k != "recorded"}))
    for region in rec["image"]["regions"]:
        region.pop("cover_box", None)
        region.pop("label_px", None)
    text = json.dumps(rec, ensure_ascii=False, sort_keys=True)
    return PLACEHOLDER_RE.sub(lambda m: m.group(0).rsplit("_", 1)[0] + "]]", text)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--check", action="store_true", help="compare with the committed file")
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args(argv)
    recording = record()
    assert_value_free(recording)
    if args.check:
        committed = json.loads(args.out.read_text(encoding="utf-8"))
        same = _comparable(committed) == _comparable(recording)
        print("recording matches" if same else "recording differs (placeholder ids aside)")
        return 0 if same else 1
    args.out.write_text(
        json.dumps(recording, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    image = recording["image"]
    print(f"wrote {args.out.name}: {len(image['regions'])} regions, {image['matches']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
