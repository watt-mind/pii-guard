"""Generate the SAM prompt-study set in ``eval/visual/prompt-set/`` (LAB-1118).

A small synthetic set that isolates the visual types SAM 3.1 is prompted for, in the shapes the
fictional document set (``eval/fixtures/visual``, Muse Image signatures) does not cover:

- ``scribble``: pen-scribble signatures drawn as smooth random strokes (the LAB-1110 miss);
- ``script``: a fictional name set in a script typeface (an "e-signature" style);
- ``scanned``: either of the two on a degraded page (tinted paper, blur, noise, JPEG round trip);
- ``id_photo``: a framed portrait on a card (portraits cropped from the fictional set, which
  shows people who don't exist), some in grayscale or small;
- ``stamp``: round and rectangular rubber stamps drawn with Pillow, rotated, some over text.

Each page also carries a few lines of fictional form text, so a prompt that grabs text counts
as stray regions. Everything is fictional (ADR 0005): the names are made up, the issuer is the
"Fictional Specimen Authority". Labels are exact (ink bounding box + 3 px, pasted photo box),
keyed by image SHA-256 in the same format as ``eval/fixtures/visual/labels.json``, so
``pii-guard eval visual --prompt-study`` reads the set directly::

    uv run python eval/visual/generate_prompt_set.py      # offline, deterministic, no cost

The per-prompt study (``eval/results/visual/prompt-study-synthetic.md``) and the default-prompt
record (``python -m pii_guard.visual.segment_eval --candidate sam-api --set prompts``)::

    uv run pii-guard eval visual --specimens eval/visual/prompt-set/images \
        --manifest eval/visual/prompt-set/manifest.json \
        --labels eval/visual/prompt-set/labels.json --max-live-calls 140 \
        --prompt-study '{"SIGNATURE": ["signature", "squiggly line", "handwritten signature",
        "handwriting", "scribble", "cursive writing"], "ID_PHOTO": ["photo of a person",
        "id photo", "passport photo", "portrait"], "FACE": ["face", "head"],
        "STAMP": ["stamp", "rubber stamp", "seal", "ink stamp"]}' \
        --json eval/results/visual/prompt-study-synthetic.json \
        --markdown eval/results/visual/prompt-study-synthetic.md

Needs the macOS script fonts (``/System/Library/Fonts/Supplemental``); the images are committed,
so the eval itself needs no fonts.
"""

from __future__ import annotations

import hashlib
import io
import json
import math
import random
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "eval" / "visual" / "prompt-set"
FICTIONAL = ROOT / "eval" / "fixtures" / "visual"
FONT_DIR = Path("/System/Library/Fonts/Supplemental")
SANS = "Arial.ttf"
BOLD = "Arial Bold.ttf"
SCRIPTS = (
    "Brush Script.ttf",
    "SnellRoundhand.ttc",
    "Savoye LET.ttc",
    "Bradley Hand Bold.ttf",
    "Apple Chancery.ttf",
    "SignPainter.ttc",
)
NAMES = (
    "Lina Vartová",
    "Bence Szalóki",
    "Mara Eltheim",
    "Tobin Arkwell",
    "Ilka Feyrund",
    "Oren Calloway",
    "Dóra Pemberk",
    "Jasper Hollin",
)
SEED = 1118
PAGE = (1000, 700)
CARD = (1012, 638)
PAD = 3


def font(name: str, size: int) -> Any:
    return ImageFont.truetype(str(FONT_DIR / name), size)


def _form_text(draw: Any, rng: random.Random, title: str, lines: int = 4) -> None:
    draw.text((60, 40), "FICTIONAL SPECIMEN AUTHORITY", font=font(BOLD, 26), fill=(30, 30, 40))
    draw.text((60, 80), title, font=font(SANS, 22), fill=(60, 60, 70))
    f = font(SANS, 20)
    fields = ("Name", "Reference", "Date", "Place", "Department", "Case")
    for i in range(lines):
        value = rng.choice(NAMES) if i == 0 else f"{rng.randint(1000, 9999)}-{rng.randint(10, 99)}"
        draw.text((60, 150 + i * 42), f"{fields[i]}: {value}", font=f, fill=(25, 25, 30))


def _ink_layer(size: tuple[int, int]) -> tuple[Any, Any]:
    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    return layer, ImageDraw.Draw(layer)


def scribble(rng: random.Random, size: tuple[int, int], ink: tuple[int, int, int]) -> Any:
    """A pen-scribble signature: one or two smooth strokes made of summed sines."""
    w, h = size
    layer, draw = _ink_layer(size)
    for stroke in range(rng.choice((1, 2))):
        x0 = 10 + stroke * w * 0.45
        span = w * (0.9 if stroke == 0 else 0.45) - 20
        waves = [
            (rng.uniform(0.3, 1.0) * h * 0.35, rng.uniform(1.5, 6), rng.uniform(0, 6.3))
            for _ in range(3)
        ]
        rng_loops = rng.uniform(18, 34)
        points = []
        for i in range(160):
            t = i / 159
            x = x0 + t * span + math.sin(t * rng_loops + waves[0][2]) * h * 0.28
            y = h / 2 + sum(a * math.sin(t * f * math.tau + p) for a, f, p in waves) / 2
            points.append((x, max(4, min(h - 4, y))))
        draw.line(points, fill=(*ink, 255), width=rng.choice((2, 3, 4)), joint="curve")
    # an underline flourish on some
    if rng.random() < 0.5:
        y = h * rng.uniform(0.7, 0.85)
        draw.line([(w * 0.1, y), (w * 0.85, y - h * 0.08)], fill=(*ink, 255), width=2)
    return layer


def script(rng: random.Random, size: tuple[int, int], ink: tuple[int, int, int], i: int) -> Any:
    layer, draw = _ink_layer(size)
    name = NAMES[i % len(NAMES)]
    f = font(SCRIPTS[i % len(SCRIPTS)], int(size[1] * 0.62))
    draw.text((8, size[1] * 0.12), name, font=f, fill=(*ink, 255))
    return layer


def _bbox(layer: Any) -> tuple[int, int, int, int]:
    box = layer.getchannel("A").getbbox()
    if box is None:
        raise ValueError("empty ink layer")
    return box


def paste(page: Any, layer: Any, xy: tuple[int, int], angle: float = 0.0) -> list[int]:
    """Paste RGBA ink at ``xy`` (rotated); return its ink box on the page, padded."""
    if angle:
        layer = layer.rotate(angle, resample=Image.Resampling.BICUBIC, expand=True)
    x1, y1, x2, y2 = _bbox(layer)
    layer = layer.crop((x1, y1, x2, y2))
    page.paste(layer, xy, layer)
    w, h = page.size
    return [
        max(0, xy[0] - PAD),
        max(0, xy[1] - PAD),
        min(w, xy[0] + layer.width + PAD),
        min(h, xy[1] + layer.height + PAD),
    ]


def degrade(page: Any, rng: random.Random) -> Any:
    """A scanned look without moving anything: tinted paper, blur, noise, JPEG artefacts."""
    tint = Image.new("RGB", page.size, (rng.randint(215, 235), rng.randint(210, 228), 200))
    page = Image.blend(page, tint, 0.18)
    page = page.filter(ImageFilter.GaussianBlur(rng.uniform(0.6, 1.1)))
    noise = Image.effect_noise(page.size, rng.uniform(18, 30)).convert("RGB")
    page = Image.blend(page, noise, 0.07)
    buf = io.BytesIO()
    page.save(buf, format="JPEG", quality=rng.randint(30, 45))
    return Image.open(io.BytesIO(buf.getvalue())).convert("RGB")


def signature_page(rng: random.Random, kind: str, i: int, scanned: bool) -> tuple[Any, list]:
    page = Image.new("RGB", PAGE, (250, 250, 248))
    draw = ImageDraw.Draw(page)
    _form_text(draw, rng, "Declaration of consent (fictional)")
    line_y = 560
    draw.text((60, line_y - 26), "Signature:", font=font(SANS, 20), fill=(25, 25, 30))
    draw.line([(190, line_y), (640, line_y)], fill=(90, 90, 90), width=1)
    ink = rng.choice(((20, 40, 140), (15, 15, 20), (30, 50, 110)))
    size = (rng.randint(300, 420), rng.randint(90, 130))
    layer = scribble(rng, size, ink) if kind == "scribble" else script(rng, size, ink, i)
    box = paste(page, layer, (200, line_y - size[1] + 25), angle=rng.uniform(-6, 4))
    if scanned:
        page = degrade(page, rng)
    return page, [{"type": "signature", "entity": "SIGNATURE", "box": box}]


def _portraits() -> list[Any]:
    """Portrait crops from the fictional set (people who don't exist), one per image."""
    labels = json.loads((FICTIONAL / "labels.json").read_text("utf-8"))["specimens"]
    manifest = json.loads((FICTIONAL / "manifest.json").read_text("utf-8"))["specimens"]
    by_sha = {e["sha256"]: e for e in manifest}
    out = []
    for sha, label in labels.items():
        boxes = [r["box"] for r in label["regions"] if r["type"] == "portrait"]
        if not boxes or sha not in by_sha:
            continue
        image = Image.open(FICTIONAL / "images" / by_sha[sha]["file"]).convert("RGB")
        x1, y1, x2, y2 = boxes[0]
        w, h = image.size
        out.append(image.crop((round(x1 * w), round(y1 * h), round(x2 * w), round(y2 * h))))
    return out


def id_photo_card(rng: random.Random, portrait: Any, i: int) -> tuple[Any, list]:
    card = Image.new("RGB", CARD, rng.choice(((232, 238, 245), (240, 236, 226), (236, 242, 236))))
    draw = ImageDraw.Draw(card)
    draw.rectangle([0, 0, CARD[0], 70], fill=(70, 90, 120))
    draw.text((30, 20), "FICTIONAL SPECIMEN AUTHORITY", font=font(BOLD, 26), fill="white")
    scale = 1.0 if i % 3 else 0.55  # every third photo is small
    pw, ph = round(230 * scale), round(300 * scale)
    photo = portrait.resize((pw, ph), Image.Resampling.LANCZOS)
    if i % 2:
        photo = photo.convert("L").convert("RGB")
    x, y = 40, 110
    frame = rng.choice(((40, 40, 40), (150, 150, 150), (90, 70, 50)))
    draw.rectangle(
        [x - 8, y - 8, x + pw + 7, y + ph + 7], fill=(255, 255, 255), outline=frame, width=3
    )
    card.paste(photo, (x, y))
    f = font(SANS, 22)
    for row, (k, v) in enumerate(
        (
            ("Surname", NAMES[i].split()[1]),
            ("Given name", NAMES[i].split()[0]),
            ("Number", f"UTO{rng.randint(100000, 999999)}"),
            ("Expiry", f"0{rng.randint(1, 9)}.12.2031"),
        )
    ):
        draw.text((340, 120 + row * 60), k, font=font(SANS, 15), fill=(90, 90, 100))
        draw.text((340, 140 + row * 60), v, font=f, fill=(20, 20, 30))
    return card, [{"type": "portrait", "entity": "ID_PHOTO", "box": [x, y, x + pw, y + ph]}]


def stamp_layer(rng: random.Random, i: int, ink: tuple[int, int, int]) -> Any:
    alpha = rng.randint(170, 235)
    if i % 2 == 0:  # round, double ring
        d = rng.randint(170, 230)
        layer, draw = _ink_layer((d, d))
        draw.ellipse([2, 2, d - 3, d - 3], outline=(*ink, alpha), width=5)
        draw.ellipse([18, 18, d - 19, d - 19], outline=(*ink, alpha), width=2)
        f = font(BOLD, max(14, d // 11))
        for j, word in enumerate(("FICTIONAL", "SPECIMEN", "AUTHORITY")):
            tw = draw.textlength(word, font=f)
            draw.text(((d - tw) / 2, d * 0.3 + j * d * 0.15), word, font=f, fill=(*ink, alpha))
    else:  # rectangular, boxed text
        w, h = rng.randint(260, 340), rng.randint(90, 120)
        layer, draw = _ink_layer((w, h))
        draw.rectangle([2, 2, w - 3, h - 3], outline=(*ink, alpha), width=4)
        draw.text((16, 12), "RECEIVED", font=font(BOLD, 30), fill=(*ink, alpha))
        draw.text(
            (16, h - 40),
            f"FSA  {rng.randint(10, 28)} OCT 2026",
            font=font(BOLD, 22),
            fill=(*ink, alpha),
        )
    return layer


def stamp_page(rng: random.Random, i: int) -> tuple[Any, list]:
    page = Image.new("RGB", PAGE, (250, 250, 248))
    draw = ImageDraw.Draw(page)
    _form_text(draw, rng, "Application received (fictional)", lines=6)
    ink = rng.choice(((180, 30, 40), (30, 60, 160), (110, 40, 130)))
    layer = stamp_layer(rng, i, ink)
    over_text = i % 3 == 0  # some stamps sit on top of the form text
    xy = (
        (rng.randint(380, 480), rng.randint(140, 220))
        if over_text
        else (rng.randint(560, 700), rng.randint(420, 470))
    )
    box = paste(page, layer, xy, angle=rng.uniform(-18, 18))
    return page, [{"type": "stamp", "entity": "STAMP", "box": box}]


def build() -> None:
    rng = random.Random(SEED)  # noqa: S311 - reproducible fixtures, not security
    images = OUT / "images"
    images.mkdir(parents=True, exist_ok=True)
    pages: list[tuple[str, str, Any, list]] = []
    for i in range(4):
        pages.append(
            (f"scribble-{i + 1:02d}", "scribble", *signature_page(rng, "scribble", i, False))
        )
    for i in range(4):
        pages.append((f"script-{i + 1:02d}", "script", *signature_page(rng, "script", i, False)))
    for i in range(4):
        kind = "scribble" if i % 2 == 0 else "script"
        pages.append((f"scanned-{i + 1:02d}", "scanned", *signature_page(rng, kind, i + 4, True)))
    portraits = _portraits()
    for i in range(6):
        portrait = portraits[(i * 5) % len(portraits)]
        pages.append((f"id-photo-{i + 1:02d}", "id_photo", *id_photo_card(rng, portrait, i)))
    for i in range(6):
        pages.append((f"stamp-{i + 1:02d}", "stamp", *stamp_page(rng, i)))

    manifest: list[dict[str, Any]] = []
    labels: dict[str, Any] = {}
    for ident, kind, image, regions in pages:
        buf = io.BytesIO()
        image.save(buf, format="PNG", optimize=True)
        data = buf.getvalue()
        (images / f"{ident}.png").write_bytes(data)
        sha = hashlib.sha256(data).hexdigest()
        w, h = image.size
        manifest.append(
            {
                "id": ident,
                "country": "GB",
                "language": "en",
                "doc_type": kind,
                "side": "page",
                "file": f"{ident}.png",
                "sha256": sha,
                "width": w,
                "height": h,
                "bytes": len(data),
            }
        )
        labels[sha] = {
            "id": ident,
            "regions": [
                {
                    **r,
                    "box": [
                        round(r["box"][0] / w, 4),
                        round(r["box"][1] / h, 4),
                        round(r["box"][2] / w, 4),
                        round(r["box"][3] / h, 4),
                    ],
                }
                for r in regions
            ],
        }
    (OUT / "manifest.json").write_text(
        json.dumps(
            {
                "version": 1,
                "description": "SAM prompt-study set (LAB-1118): synthetic signatures "
                "(scribble, script font, scanned look), framed ID photos and rubber stamps, "
                "drawn by eval/visual/generate_prompt_set.py. Fictional throughout; "
                "'doc_type' is the variant.",
                "out_dir": "eval/visual/prompt-set/images",
                "specimens": manifest,
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    (OUT / "labels.json").write_text(
        json.dumps(
            {
                "version": 1,
                "description": "Exact regions of the prompt-study set, keyed by image SHA-256.",
                "box_format": "[x1, y1, x2, y2] as fractions of the image width and height",
                "method": "Ink bounding box of each pasted signature or stamp (+3 px); "
                "pasted photo box.",
                "specimens": labels,
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"wrote {len(pages)} images to {images.relative_to(ROOT)}")


if __name__ == "__main__":
    build()
