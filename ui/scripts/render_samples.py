"""Render the fictional sample images for the UI's Images tab (ADR 0005: synthetic only).

Everything is drawn with Pillow: the faces are ellipses with dots for eyes, signatures are
sine-wave scribbles, the stamp is two circles and some text. Every name, number and address is
fictional; the TAJ and tax IDs pass their checksums but belong to no one.

    uv run python ui/scripts/render_samples.py      # writes ui/public/samples/*.png

The PNGs are committed; re-run this only when the drawings change, and re-record the demo
regions afterwards (see ui/README.md, "Images").
"""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parent.parent / "public" / "samples"


#: Fonts with Hungarian accents (ő, ű), first one found wins. Pillow's built-in font lacks them.
FONT_CANDIDATES = (
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    "C:/Windows/Fonts/arial.ttf",
)


def font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in FONT_CANDIDATES:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    raise SystemExit("no font with Hungarian accents found; add one to FONT_CANDIDATES")


def taj(first8: str) -> str:
    digits = [int(c) for c in first8]
    check = sum(d * (3 if i % 2 == 0 else 7) for i, d in enumerate(digits)) % 10
    raw = first8 + str(check)
    return f"{raw[:3]} {raw[3:6]} {raw[6:]}"


def tax_id(first9: str) -> str:
    digits = [int(c) for c in first9]
    check = sum(d * (i + 1) for i, d in enumerate(digits)) % 11
    if check == 10:
        raise ValueError("pick other digits: checksum 10 is not allowed")
    return first9 + str(check)


def draw_face(d: ImageDraw.ImageDraw, box: tuple[int, int, int, int], skin, hair) -> None:
    x1, y1, x2, y2 = box
    w, h = x2 - x1, y2 - y1
    d.ellipse([x1, y1, x2, y2], fill=skin, outline=(120, 80, 60), width=2)
    d.chord([x1 - 2, y1 - 4, x2 + 2, y1 + h * 0.55], 180, 360, fill=hair)
    ey = y1 + h * 0.45
    for ex in (x1 + w * 0.3, x1 + w * 0.62):
        d.ellipse([ex, ey, ex + w * 0.1, ey + h * 0.08], fill="black")
    nose = [
        (x1 + w * 0.5, ey + h * 0.1),
        (x1 + w * 0.44, ey + h * 0.25),
        (x1 + w * 0.56, ey + h * 0.25),
    ]
    d.polygon(nose, fill=(205, 155, 125))
    mouth = [x1 + w * 0.32, y1 + h * 0.6, x1 + w * 0.68, y1 + h * 0.85]
    d.arc(mouth, 20, 160, fill=(150, 40, 40), width=3)


def scribble(d: ImageDraw.ImageDraw, x: float, y: float, length: int, scale: float = 1.0) -> None:
    pts = [
        (x + t * 2.0 * scale, y + 16 * scale * math.sin(t / 5.5) + 7 * scale * math.sin(t / 2.1))
        for t in range(length)
    ]
    d.line(pts, fill=(15, 25, 120), width=3)
    loop = [(x + 20 + 14 * math.cos(a / 8), y - 4 + 18 * math.sin(a / 8)) for a in range(0, 52)]
    d.line(loop, fill=(15, 25, 120), width=3)


def id_card() -> Image.Image:
    w, h = 720, 450
    img = Image.new("RGB", (w, h), (232, 238, 248))
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, w - 1, 56], fill=(28, 58, 118))
    d.text((22, 14), "SAMPLE ID CARD - FICTIONAL", fill="white", font=font(24))
    d.rectangle([30, 86, 230, 352], fill=(198, 210, 228), outline=(80, 80, 80), width=3)
    draw_face(d, (72, 116, 188, 262), (240, 202, 172), (90, 60, 40))
    d.rectangle([62, 262, 198, 352], fill=(58, 82, 140))
    lines = [
        "Name: Minta Mária",
        "Born: 1985-03-14",
        f"TAJ: {taj('20456789')}",
        f"Adóazonosító jel: {tax_id('812345670')}",
    ]
    for i, text in enumerate(lines):
        d.text((262, 96 + i * 44), text, fill="black", font=font(22))
    scribble(d, 270, 330, 160)
    d.line([262, 372, 640, 372], fill=(120, 120, 120), width=1)
    d.text((262, 380), "Signature", fill=(90, 90, 90), font=font(15))
    return img


def signed_letter() -> Image.Image:
    w, h = 640, 820
    img = Image.new("RGB", (w, h), (252, 251, 247))
    d = ImageDraw.Draw(img)
    d.text((48, 40), "Példa Szolgáltató Kft.", fill=(28, 58, 118), font=font(26))
    d.text((48, 76), "1111 Budapest, Minta utca 1.  (fictional)", fill=(90, 90, 90), font=font(15))
    d.line([48, 104, w - 48, 104], fill=(28, 58, 118), width=2)
    body = [
        "Tárgy: Szerződés módosítása",
        "",
        "Tisztelt Kovács Bence!",
        "",
        "Kérjük, a módosított szerződést aláírva küldje vissza",
        "a bence.kovacs@example.com címről, vagy hívjon",
        "a +36 30 555 0142 számon.",
        "",
        f"Adóazonosító jel: {tax_id('812345678')}",
        "",
        "Budapest, 2026. október 26.",
        "",
        "Üdvözlettel:",
    ]
    for i, text in enumerate(body):
        d.text((48, 136 + i * 34), text, fill="black", font=font(20))
    scribble(d, 60, 640, 150)
    d.text((60, 690), "Minta Péter ügyvezető", fill=(60, 60, 60), font=font(17))
    # Round company stamp (kept by policy by default).
    cx, cy, r = 470, 650, 78
    stamp = (150, 30, 60)
    d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=stamp, width=4)
    d.ellipse([cx - r + 14, cy - r + 14, cx + r - 14, cy + r - 14], outline=stamp, width=2)
    d.text((cx - 46, cy - 22), "PÉLDA KFT.", fill=stamp, font=font(18))
    d.text((cx - 42, cy + 4), "BUDAPEST", fill=stamp, font=font(16))
    for a in range(0, 360, 30):
        rad = math.radians(a)
        px, py = cx + (r - 7) * math.cos(rad), cy + (r - 7) * math.sin(rad)
        d.ellipse([px - 2, py - 2, px + 2, py + 2], fill=stamp)
    return img


def visitor_badge() -> Image.Image:
    w, h = 480, 680
    img = Image.new("RGB", (w, h), (244, 244, 240))
    d = ImageDraw.Draw(img)
    card = [20, 20, w - 20, h - 20]
    d.rounded_rectangle(card, radius=24, fill="white", outline=(200, 200, 200), width=2)
    d.rounded_rectangle([200, 34, 280, 50], radius=8, fill=(210, 210, 210))
    d.rectangle([21, 70, w - 21, 130], fill=(196, 92, 30))
    d.text((150, 84), "VISITOR", fill="white", font=font(32))
    d.rounded_rectangle([130, 160, 350, 400], radius=12, fill=(214, 226, 236))
    draw_face(d, (168, 182, 312, 362), (214, 170, 140), (40, 30, 30))
    d.text((60, 430), "Jane Placeholder", fill="black", font=font(30))
    d.text((60, 482), "jane.placeholder@example.net", fill=(40, 40, 40), font=font(20))
    d.text((60, 516), "+44 20 7946 0958", fill=(40, 40, 40), font=font(20))
    d.text((60, 580), "Fictional badge for the pii-guard demo", fill=(120, 120, 120), font=font(15))
    return img


SAMPLES = {"id-card": id_card, "signed-letter": signed_letter, "visitor-badge": visitor_badge}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, render in SAMPLES.items():
        path = OUT / f"{name}.png"
        render().save(path, format="PNG", optimize=True)
        print(f"wrote {path.relative_to(OUT.parent.parent)} ({path.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
