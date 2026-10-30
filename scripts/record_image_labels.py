"""Record the landing's labels-mode image showcase (LAB-1484).

The landing (``ui/src/hosted/ImageShowcase.tsx``) shows what the default ``render="labels"``
does to two fictional specimen ID cards, ``ui/public/samples/id-card-en.png``
(``eval/fixtures/visual/images/en-id_card-front.png``, the default since LAB-1509) and
``ui/public/samples/id-card.png`` (``hu-id_card-front.png``): each text value covered by a box with
its vault placeholder printed in it, the face and ID photo covered, and the masked transcript
and document summary that go to the model with the image. This script makes that recording
with the real API, configured like the hosted preview (ADR 0014): the on-device ``local``
segmenter (YuNet), the built-in Tesseract OCR, the ``rules`` detector, signatures and stamps
kept.

One vault session, as an application would use it: the party is pre-loaded as a known value,
the user's message is masked (``/v1/mask``), then the image (``/v1/mask/image``), so the
holder's name gets the same placeholder in the text and on the card. Muse Spark
(``muse-spark-1.3`` on the Meta Model API, the hosted preview's included model) answers the
masked message from the text the gateway sends with a labelled image (its document summary and
masked transcript, :func:`pii_guard.gateway.service.image_annotation`; LAB-1524), and the answer
is restored with ``/v1/unmask`` to check the round trip. The answer may only use the message's
placeholders, so the landing can put the name back; the script asks up to three times.

The written JSON is value-free: the masked message, the regions (``to_public_dict``, plus the
label's lines and font size from :func:`pii_guard.visual.render.fit_label`, so the browser
draws it at the server's size), the transcript, the summary and the masked answer. The script
fails if any printed value of the card (``eval/fixtures/visual/generation.json``) or the
message's name would be written. Needs the ``ocr`` and ``local-vision`` extras, the
``tesseract`` binary and ``META_API_KEY`` (``--check`` calls no model and compares everything
but the answer)::

    uv run --no-sync python scripts/record_image_labels.py              # writes both recordings
    uv run --no-sync python scripts/record_image_labels.py --sample en  # one of them
    uv run --no-sync python scripts/record_image_labels.py --check      # compares, writes nothing
"""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import json
import os
import secrets
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import httpx
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw
from pydantic import SecretStr

from pii_guard.api.app import create_app
from pii_guard.config import Settings
from pii_guard.eval.visual_labels import load_gold
from pii_guard.gateway.service import image_annotation
from pii_guard.policy import Policy
from pii_guard.types import EntityType
from pii_guard.upstreams import PRESETS
from pii_guard.vault import PLACEHOLDER_RE
from pii_guard.visual.render import fit_label

ROOT = Path(__file__).resolve().parent.parent
CONTENT = ROOT / "ui" / "src" / "content"
MUSE = PRESETS["meta"]
MODEL = MUSE.default_model or "muse-spark-1.3"
ATTEMPTS = 3
SYSTEM = (
    "You help a notary's office check the documents a client sends. People and their details "
    "appear as placeholders such as [[PERSON_ab12cd]]; write them exactly as given. Answer in "
    "one or two short sentences."
)


@dataclass(frozen=True)
class Sample:
    """One showcase card: the public image, its fixture (for the gold values), the language of
    its printed text, the fictional holder pre-loaded as the application's known party, and
    where the recording goes. Keep the messages in step with ui/src/content/imageLabels.ts."""

    image: Path
    fixture_id: str
    language: str
    holder: str
    out: Path

    @property
    def message(self) -> str:
        return f"{self.holder} is the seller. Is her ID card attached, and is it still valid?"


SAMPLES = {
    # LAB-1509: the English specimen (eval/fixtures/visual/images/en-id_card-front.png),
    # the landing's default.
    "en": Sample(
        ROOT / "ui" / "public" / "samples" / "id-card-en.png",
        "en-id_card-front",
        "en",
        "Jane Placeholder",
        CONTENT / "imageLabelsRecording.en.json",
    ),
    "hu": Sample(
        ROOT / "ui" / "public" / "samples" / "id-card.png",
        "hu-id_card-front",
        "hu",
        "Fiktív Mária",
        CONTENT / "imageLabelsRecording.json",
    ),
}


def muse_answer(masked_message: str, annotation: str) -> str:
    """Muse Spark's answer to the masked message with the image's annotation (one call)."""
    key = os.environ.get(MUSE.key_env, "")
    if not key:
        raise SystemExit(f"set {MUSE.key_env} to record the model's answer")
    response = httpx.post(
        f"{MUSE.base_url}/chat/completions",
        headers={"Authorization": f"Bearer {key}"},
        json={
            "model": MODEL,
            "reasoning_effort": "low",
            "max_tokens": 2048,
            "messages": [
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": f"{masked_message}\n\n{annotation}"},
            ],
        },
        timeout=120,
    )
    if response.status_code != 200:
        raise SystemExit(f"the model answered {response.status_code}")
    return (response.json()["choices"][0]["message"].get("content") or "").strip()


def usable(answer: str, masked_message: str) -> bool:
    """A placeholder in it, and only the message's: the landing restores from the message."""
    own = {m.group(0) for m in PLACEHOLDER_RE.finditer(masked_message)}
    used = {m.group(0) for m in PLACEHOLDER_RE.finditer(answer)}
    return bool(used) and used <= own


def _fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


#: Words of a value that the recording also holds as ordinary text: the Hungarian card's footer
#: reads "MI által generált fiktív minta" (AI-generated fictional specimen) and its surname is
#: "Fiktív"; the English card's surname is "Placeholder", which is also a key of every region.
#: The whole name is still checked.
BOILERPLATE = frozenset({"fiktiv", "placeholder"})


def assert_value_free(recording: dict[str, Any], sample: Sample) -> None:
    """Fail if a printed value of the card (whole, digits only, or a word of it) is in the
    recording. Prints counts only, never the value."""
    blob = _fold(json.dumps(recording, ensure_ascii=False))
    digits = "".join(c for c in blob if c.isdigit())
    values = [*load_gold()[sample.fixture_id].values(), sample.holder]
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


def record(sample: Sample, ask_model: bool = True) -> dict[str, Any]:
    settings = Settings(
        tenant_key=SecretStr(secrets.token_hex(32)),
        segmenter="local",
        image_render="labels",
        detectors=("rules",),
        policy_overrides={EntityType.SIGNATURE: Policy.KEEP, EntityType.STAMP: Policy.KEEP},
    )
    app = create_app(settings)
    png = sample.image.read_bytes()
    with TestClient(app, base_url="http://127.0.0.1") as http:
        created = http.post(
            "/v1/sessions",
            json={"known_values": [{"value": sample.holder, "entity_type": "PERSON"}]},
        )
        created.raise_for_status()
        session = created.json()["session_id"]
        text = http.post(
            "/v1/mask", json={"text": sample.message, "language": "en", "session_id": session}
        )
        text.raise_for_status()
        image = http.post(
            "/v1/mask/image",
            json={
                "image": base64.b64encode(png).decode("ascii"),
                "language": sample.language,
                "session_id": session,
                "render": "labels",
            },
        )
        image.raise_for_status()
        body = image.json()
        masked_message = text.json()["masked_text"]
        annotation = image_annotation(
            1, cast(Any, SimpleNamespace(summary=body["summary"], transcript=body["transcript"]))
        )
        answer = ""
        for attempt in range(1, ATTEMPTS + 1 if ask_model else 0):
            answer = muse_answer(masked_message, annotation)
            if usable(answer, masked_message):
                break
            print(
                f"attempt {attempt}: the answer can't be restored from the message", file=sys.stderr
            )
            answer = ""
        if ask_model and not answer:
            raise SystemExit(f"no usable answer in {ATTEMPTS} attempts; nothing written")
        if ask_model:
            restored = http.post("/v1/unmask", json={"text": answer, "session_id": session})
            restored.raise_for_status()
            back = restored.json()
            back_text = back.get("text") or back.get("unmasked_text") or ""
            if PLACEHOLDER_RE.search(back_text) or sample.holder not in back_text:
                raise SystemExit("the answer did not restore")
    if body["analysis"]["ocr"]["engine"] != "tesseract" or body["render"] != "labels":
        raise SystemExit("needs Tesseract and labels rendering")
    regions = [{**r, **_label_fit(r)} for r in body["regions"]]
    return {
        "recorded": dt.date.today().isoformat(),
        "note": (
            "scripts/record_image_labels.py: POST /v1/mask/image with render=labels on "
            f"ui/public/samples/{sample.image.name} (fictional specimen), configured like the "
            "hosted preview (segmenter local/YuNet, Tesseract, rules; signatures and stamps "
            "kept), in the session that masked the message. Value-free: placeholders only, "
            "no image."
        ),
        "message": {"masked": masked_message},
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
        "answer": {
            "masked": answer,
            "model": MODEL,
            "by": "Muse Spark, reading the masked message, summary and transcript",
        },
    }


def _comparable(recording: dict[str, Any]) -> str:
    """The recording without what changes from run to run by design: the date, the
    session-random placeholder ids, the label fit and box extension that depend on them, and
    the model's answer (``--check`` calls no model)."""
    rec = json.loads(
        json.dumps({k: v for k, v in recording.items() if k not in ("recorded", "answer")})
    )
    for region in rec["image"]["regions"]:
        region.pop("cover_box", None)
        region.pop("label_px", None)
    text = json.dumps(rec, ensure_ascii=False, sort_keys=True)
    return PLACEHOLDER_RE.sub(lambda m: m.group(0).rsplit("_", 1)[0] + "]]", text)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--check", action="store_true", help="compare with the committed file")
    parser.add_argument("--sample", choices=[*SAMPLES, "all"], default="all")
    args = parser.parse_args(argv)
    status = 0
    for key in SAMPLES if args.sample == "all" else [args.sample]:
        sample = SAMPLES[key]
        recording = record(sample, ask_model=not args.check)
        assert_value_free(recording, sample)
        if args.check:
            committed = json.loads(sample.out.read_text(encoding="utf-8"))
            same = _comparable(committed) == _comparable(recording)
            print(
                f"{key}: "
                + ("recording matches" if same else "recording differs (placeholder ids aside)")
            )
            status |= 0 if same else 1
            continue
        sample.out.write_text(
            json.dumps(recording, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        image = recording["image"]
        print(f"wrote {sample.out.name}: {len(image['regions'])} regions, {image['matches']}")
    return status


if __name__ == "__main__":
    sys.exit(main())
