"""Generate the fictional specimen-style documents in ``eval/fixtures/visual/`` (LAB-1121).

Everything here is fictional (ADR 0005). **Muse Image** (``muse-image-1.0`` on the Meta Model
API) paints the parts a drawing can't fake: the portraits of people who don't exist, the
handwritten signatures, rubber stamps and neutral paper and card textures. Every word and
number is then laid out and rendered **by us with Pillow**, so each text value, portrait,
signature and MRZ sits in a box we know exactly; those boxes are the labels. The layouts are
our own and deliberately plain: no coat of arms, no national symbol, no official template and
no imitation of a security feature (no guilloche, hologram, ghost image or microprint). The
issuer is a "Fictional Specimen Authority", the MRZ state code is ``UTO`` (ICAO's own fictional
"Utopia"), and every document is overprinted ``MINTA / SPECIMEN``.

Names, dates and numbers come from a seeded generator; the IDs pass their checksums
(``pii_guard.detect.checksums``, ``pii_guard.languages.de.checksums``) and so does every MRZ
check digit, but they belong to no one. E-mail domains are the reserved ``example.*`` ones and
UK phone numbers use Ofcom's drama range (07700 900xxx).

Three steps, each one optional::

    uv run python eval/visual/generate_images.py probe     # whole-document prompts: refused?
    uv run python eval/visual/generate_images.py assets    # portraits, signatures, textures
    uv run python eval/visual/generate_images.py compose   # lay out + label (offline, no cost)

``probe`` and ``assets`` call Muse Image (USD 0.01 per image; ``META_API_KEY`` from the
environment, ``.env`` or the file ``PII_GUARD_ENV_FILE`` names; never logged) and refuse to go
over ``--budget`` (USD 2 by default,
counted over every call recorded in ``generation.json``). Raw images are cached in the
gitignored ``data/muse-image/`` and never regenerated once there. The API takes no seed, so
``generation.json`` records the prompt, the model and the SHA-256 of every image it returned;
``compose`` is deterministic given those images.

If Muse Image refuses a prompt, the refusal is recorded in ``generation.json`` and ``compose``
falls back to what it can draw itself (a flat tint for a texture). Whole-document prompts
were **not** refused in the probe (see ``generation.json``), but the model's own text is
neither exact nor ours to label, so the documents are always composed from parts.
"""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import hashlib
import io
import json
import math
import os
import random
import sys
import time
import unicodedata
from collections.abc import Callable, Iterable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "eval" / "fixtures" / "visual"
CACHE_DIR = ROOT / "data" / "muse-image"
RECORD = OUT_DIR / "generation.json"
API_BASE = "https://api.meta.ai/v1"
MODEL = "muse-image-1.0"
COST_PER_IMAGE = 0.01
DEFAULT_BUDGET = 2.0
SPECIMEN = "MINTA / SPECIMEN"
STATE = "UTO"  # ICAO 9303's fictional issuing state, used on its own specimen documents
LANGUAGES = ("hu", "de", "en")
COUNTRY = {"hu": "HU", "de": "DE", "en": "GB"}  # whose number formats a variant uses

# --- Muse Image prompts --------------------------------------------------------------------

_PORTRAIT = (
    "Passport-style head-and-shoulders photograph of a fictional {who}, {hair}, wearing "
    "{clothes}, neutral expression, looking straight at the camera, plain light grey "
    "background, even soft studio lighting, photorealistic, no text, no watermark"
)
#: (who, hair, clothes): 18 people who don't exist, varied in age, sex and appearance.
PEOPLE: tuple[tuple[str, str, str], ...] = (
    ("woman in her thirties", "shoulder-length brown hair", "a dark blue blouse"),
    ("man in his fifties", "short grey hair and a trimmed beard", "a grey sweater"),
    ("young woman in her twenties", "long blond hair tied back", "a white t-shirt"),
    ("man in his forties", "dark curly hair", "a light blue shirt"),
    ("woman in her sixties", "short white hair", "a burgundy cardigan"),
    ("young man in his twenties", "short black hair", "a green hoodie"),
    ("woman in her forties", "auburn bob haircut and glasses", "a black turtleneck"),
    ("man in his seventies", "bald with a white moustache", "a brown jacket"),
    ("woman in her fifties", "dark hair in a bun", "a teal top"),
    ("man in his thirties", "red hair and freckles", "a navy polo shirt"),
    ("young woman in her twenties", "black braided hair", "a yellow blouse"),
    ("man in his sixties", "thinning grey hair and glasses", "a checked shirt"),
    ("woman in her thirties", "straight black hair with a fringe", "a grey blazer"),
    ("man in his twenties", "wavy brown hair", "a white shirt"),
    ("woman in her seventies", "curly grey hair", "a lilac jumper"),
    ("man in his forties", "shaved head and a dark beard", "a black t-shirt"),
    ("woman in her twenties", "pixie-cut light brown hair", "an orange top"),
    ("man in his fifties", "salt-and-pepper side-parted hair", "a dark suit jacket"),
)
_SIGNATURE = (
    "A single handwritten signature in {ink} ink on plain white paper, {style}, fluid pen "
    "stroke, illegible, nothing else on the page, no printed text, no lines, top-down scan"
)
SIGNATURES: tuple[tuple[str, str], ...] = (
    ("dark blue", "a looping cursive scrawl"),
    ("black", "a short angular scribble with an underline"),
    ("blue", "a wide flowing signature with a large initial"),
    ("black", "a tight slanted cursive signature"),
    ("dark blue", "a signature with two loops and a flourish"),
    ("blue", "a compact zigzag signature"),
)
_STAMP = (
    "A {shape} rubber stamp impression in {ink} ink on plain white paper, slightly uneven and "
    "faded, {inside}, no letters, no words, no numbers, no flag, no coat of arms, top-down scan"
)
STAMPS: tuple[tuple[str, str, str], ...] = (
    ("round", "violet", "a double border ring around a simple five-pointed star"),
    ("oval", "blue", "a double border ring around an abstract leaf"),
)
_TEXTURE = (
    "Seamless abstract background texture, {look}, soft and low contrast, flat, no text, no "
    "letters, no numbers, no symbols, no emblem, no pattern of lines, no border"
)
TEXTURES: tuple[tuple[str, str], ...] = (
    ("card-blue", "pale blue and white watercolour wash with gentle diagonal gradients"),
    ("card-green", "pale sage green and cream watercolour clouds"),
    ("card-rose", "pale rose and sand coloured soft gradient with faint paper fibres"),
    ("card-grey", "light warm grey brushed paper with faint speckles"),
    ("paper", "off-white recycled writing paper with very faint fibres"),
    ("badge", "light lavender and white soft bokeh gradient"),
)
#: Whole-document prompts, sent once by ``probe`` to record whether the model refuses them.
PROBES: tuple[tuple[str, str], ...] = (
    (
        "probe-id-card",
        "A fictional specimen identity card, front side, with a portrait photo of a generated "
        "person, the words MINTA / SPECIMEN printed across it, plain neutral design, no "
        "national symbols",
    ),
    (
        "probe-passport",
        "The data page of a fictional specimen passport with a portrait photo of a generated "
        "person, a machine readable zone, the words MINTA / SPECIMEN printed across it, plain "
        "neutral design, no national symbols",
    ),
    (
        "probe-driving-licence",
        "A fictional specimen driving licence card with a portrait photo of a generated "
        "person and a signature, the words MINTA / SPECIMEN printed across it, plain neutral "
        "design, no national symbols",
    ),
)


@dataclass(frozen=True, slots=True)
class Asset:
    id: str
    kind: str  # portrait | signature | stamp | texture | probe
    prompt: str


def asset_plan() -> list[Asset]:
    assets = [
        Asset(f"portrait-{i:02d}", "portrait", _PORTRAIT.format(who=w, hair=h, clothes=c))
        for i, (w, h, c) in enumerate(PEOPLE)
    ]
    assets += [
        Asset(f"signature-{i:02d}", "signature", _SIGNATURE.format(ink=ink, style=style))
        for i, (ink, style) in enumerate(SIGNATURES)
    ]
    assets += [
        Asset(f"stamp-{i:02d}", "stamp", _STAMP.format(shape=s, ink=ink, inside=inside))
        for i, (s, ink, inside) in enumerate(STAMPS)
    ]
    assets += [Asset(f"texture-{n}", "texture", _TEXTURE.format(look=look)) for n, look in TEXTURES]
    return assets


# --- Muse Image client ---------------------------------------------------------------------


def _api_key() -> str:
    key = os.environ.get("META_API_KEY")
    env = Path(os.environ.get("PII_GUARD_ENV_FILE", ROOT / ".env"))
    if not key and env.is_file():
        for line in env.read_text("utf-8").splitlines():
            if line.startswith("META_API_KEY="):
                key = line.split("=", 1)[1].strip().strip("\"'")
    if not key:
        raise SystemExit("META_API_KEY is not set (environment or .env)")
    return key


def _load_record() -> dict[str, Any]:
    if RECORD.is_file():
        return json.loads(RECORD.read_text("utf-8"))
    return {
        "version": 1,
        "description": "How eval/fixtures/visual/ was made: every Muse Image call (prompt, "
        "model, outcome, SHA-256 of the image), then the composed documents. All fictional.",
        "model": MODEL,
        "endpoint": f"{API_BASE}/images/generations",
        "seed": "not supported by the API (an unknown parameter); images are identified by "
        "SHA-256 and cached in data/muse-image/",
        "cost_per_image_usd": COST_PER_IMAGE,
        "calls": [],
    }


def _save_record(record: dict[str, Any]) -> None:
    calls = record["calls"]
    billed = sum(1 for c in calls if c["status"] == "ok")
    record["spend"] = {
        "calls": len(calls),
        "images": billed,
        "refused": sum(1 for c in calls if c["status"] == "refused"),
        "estimated_usd": round(billed * COST_PER_IMAGE, 2),
        # If refused prompts are billed too (the API doesn't say), this is the ceiling.
        "upper_bound_usd": round(len(calls) * COST_PER_IMAGE, 2),
    }
    RECORD.parent.mkdir(parents=True, exist_ok=True)
    RECORD.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n", "utf-8")


def _generate(asset: Asset, key: str) -> dict[str, Any]:
    import httpx

    entry: dict[str, Any] = {"asset": asset.id, "kind": asset.kind, "prompt": asset.prompt}
    started = time.perf_counter()
    try:
        response = httpx.post(
            f"{API_BASE}/images/generations",
            headers={"Authorization": f"Bearer {key}"},
            json={"model": MODEL, "prompt": asset.prompt, "response_format": "b64_json"},
            timeout=240,
        )
    except httpx.HTTPError as exc:
        return entry | {"status": "error", "error": type(exc).__name__}
    entry["latency_s"] = round(time.perf_counter() - started, 1)
    if response.status_code != 200:
        try:
            message = response.json().get("error", {}).get("message", "")
        except ValueError:
            message = response.text[:200]
        refused = response.status_code in (400, 403, 422) and any(
            w in message.lower() for w in ("safety", "policy", "refus", "moderat", "not allowed")
        )
        status = "refused" if refused else "error"
        return entry | {"status": status, "http": response.status_code, "error": message[:300]}
    body = response.json()
    items = body.get("data") or []
    if not items or not items[0].get("b64_json"):
        return entry | {"status": "refused", "http": 200, "error": "no image in the response"}
    raw = base64.b64decode(items[0]["b64_json"])
    path = CACHE_DIR / f"{asset.id}.{body.get('output_format', 'webp')}"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    from PIL import Image

    with Image.open(io.BytesIO(raw)) as image:
        size = list(image.size)
    return entry | {
        "status": "ok",
        "file": path.name,
        "format": body.get("output_format"),
        "size": size,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "usage": body.get("usage"),
        "created": body.get("created"),
    }


def cached_path(asset_id: str) -> Path | None:
    hits = sorted(CACHE_DIR.glob(f"{asset_id}.*"))
    return hits[0] if hits else None


def run_calls(assets: Sequence[Asset], budget: float, workers: int) -> int:
    record = _load_record()
    done = {c["asset"] for c in record["calls"] if c["status"] in ("ok", "refused")}
    todo = [a for a in assets if a.id not in done or (a.kind != "probe" and not cached_path(a.id))]
    spent = sum(1 for c in record["calls"] if c["status"] == "ok") * COST_PER_IMAGE
    allowed = int(round((budget - spent) / COST_PER_IMAGE, 6))
    if len(todo) > allowed:
        print(f"budget: {len(todo)} images needed, {max(0, allowed)} left in USD {budget}")
        return 1
    if not todo:
        print("nothing to generate (all assets cached)")
        return 0
    key = _api_key()
    print(f"generating {len(todo)} images (USD {len(todo) * COST_PER_IMAGE:.2f})")
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for entry in pool.map(lambda a: _generate(a, key), todo):
            print(f"  {entry['asset']}: {entry['status']} {entry.get('error', '')}".rstrip())
            record["calls"].append(entry)
            _save_record(record)
    _save_record(record)
    print(f"spend so far: USD {record['spend']['estimated_usd']:.2f}")
    return 0


# --- fictional people and their numbers ----------------------------------------------------

_HU_SURNAMES = ("Fiktív", "Példa", "Kitalált", "Próba", "Képzelt", "Tesztes", "Mintás", "Álnév")
_HU_GIVEN_F = ("Mária", "Zsófia", "Eszter", "Réka", "Ilona", "Boglárka", "Anna", "Dóra")
_HU_GIVEN_M = ("Bence", "Gábor", "Ádám", "Levente", "Ferenc", "Márton", "Zoltán", "Péter")
_DE_SURNAMES = ("Mustermann", "Beispiel", "Probe", "Musterle", "Platzhalter", "Fiktiv")
_DE_GIVEN_F = ("Erika", "Lena", "Hanna", "Greta", "Ilse", "Sophie", "Clara", "Jana")
_DE_GIVEN_M = ("Max", "Jonas", "Lukas", "Karl", "Felix", "Paul", "Moritz", "Otto")
_EN_SURNAMES = ("Placeholder", "Sample", "Specimen", "Example", "Fictional", "Dummy")
_EN_GIVEN_F = ("Jane", "Olivia", "Amelia", "Grace", "Edith", "Chloe", "Ruby", "Alice")
_EN_GIVEN_M = ("John", "Oliver", "Harry", "Jack", "Arthur", "George", "Noah", "Leo")
_HU_STREETS = ("Minta utca", "Kitalált köz", "Példa tér", "Próba sor", "Képzelt út")
_HU_CITIES = (("1052", "Budapest"), ("6720", "Szeged"), ("9021", "Győr"), ("4024", "Debrecen"))
_DE_STREETS = ("Musterstraße", "Beispielweg", "Probeallee", "Platzhalterring")
_DE_CITIES = (("10115", "Berlin"), ("80331", "München"), ("50667", "Köln"), ("20095", "Hamburg"))
_EN_STREETS = ("Sample Road", "Example Street", "Placeholder Lane", "Specimen Close")
_EN_CITIES = (("EX1 2AB", "Exeter"), ("YO1 7HH", "York"), ("BA1 1AA", "Bath"))
_BIRTH_PLACES = {
    "hu": ("Budapest", "Szeged", "Pécs", "Eger", "Győr"),
    "de": ("Berlin", "Leipzig", "Bremen", "Dresden", "Mainz"),
    "en": ("London", "Leeds", "Bristol", "Norwich", "Oxford"),
}
#: Whether PEOPLE[i] is a woman (picks a matching fictional given name).
_FEMALE = (True, False, True, False, True, False, True, False, True, False, True, False, True,
           False, True, False, True, False)  # fmt: skip


@dataclass
class Person:
    lang: str
    surname: str
    given: str
    female: bool
    born: dt.date
    birth_place: str
    street: str
    postcode: str
    city: str
    email: str
    phone: str
    ids: dict[str, str] = field(default_factory=dict)

    @property
    def full_name(self) -> str:  # Hungarian order is surname first
        return (
            f"{self.surname} {self.given}" if self.lang == "hu" else f"{self.given} {self.surname}"
        )

    @property
    def address(self) -> str:
        if self.lang == "hu":
            return f"{self.postcode} {self.city}, {self.street}"
        if self.lang == "de":
            return f"{self.street}, {self.postcode} {self.city}"
        return f"{self.street}, {self.city} {self.postcode}"


def _ascii(text: str) -> str:
    """Accents dropped (``Ő`` -> ``O``, ``ß`` -> ``ss``), as in e-mail addresses and the MRZ."""
    decomposed = unicodedata.normalize("NFKD", text.replace("ß", "ss"))
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def hu_personal_id(rng: random.Random, born: dt.date, female: bool) -> str:
    first = ("2" if female else "1") if born.year < 2000 else ("6" if female else "5")
    from pii_guard.detect.checksums import hu_personal_id_check_digit

    while True:
        head = f"{first}{born:%y%m%d}{rng.randrange(1000):03d}"
        check = hu_personal_id_check_digit(head)
        if check is not None:
            return head + str(check)


def hu_taj(rng: random.Random) -> str:
    from pii_guard.detect.checksums import taj_check_digit

    head = f"{rng.randrange(10**7, 10**8)}"
    return head + str(taj_check_digit(head))


def hu_tax_id(rng: random.Random, born: dt.date) -> str:
    from pii_guard.detect.checksums import hu_tax_id_check_digit

    days = (born - dt.date(1867, 1, 1)).days
    while True:
        head = f"8{days:05d}{rng.randrange(1000):03d}"
        check = hu_tax_id_check_digit(head)
        if check is not None:
            return head + str(check)


def de_steuer_id(rng: random.Random) -> str:
    from pii_guard.languages.de.checksums import is_valid_steuer_id, steuer_id_check_digit

    while True:
        digits = [str(rng.randrange(1, 10))] + [str(rng.randrange(10)) for _ in range(9)]
        head = "".join(digits)
        value = head + str(steuer_id_check_digit(head))
        if is_valid_steuer_id(value):
            return value


def de_sv_number(rng: random.Random, born: dt.date, surname: str) -> str:
    from pii_guard.languages.de.checksums import sv_number_check_digit

    area, serial = rng.randrange(2, 90), rng.randrange(100)
    head = f"{area:02d}{born:%d%m%y}{_ascii(surname)[0].upper()}{serial:02d}"
    return head + str(sv_number_check_digit(head))


def uk_nino(rng: random.Random) -> str:
    first, second = "ABCEGHJKLMNPRSTWXYZ", "ABCEGHJKLMNPRSTWXYZ"
    while True:
        prefix = rng.choice(first) + rng.choice(second)
        if prefix not in {"BG", "GB", "KN", "NK", "NT", "TN", "ZZ"}:
            break
    return f"{prefix}{rng.randrange(10**6):06d}{rng.choice('ABCD')}"


def make_person(lang: str, index: int, female: bool) -> Person:
    rng = random.Random(f"pii-guard-lab-1121-{lang}-{index}")  # noqa: S311 (fictional data)
    surnames, given_f, given_m = {
        "hu": (_HU_SURNAMES, _HU_GIVEN_F, _HU_GIVEN_M),
        "de": (_DE_SURNAMES, _DE_GIVEN_F, _DE_GIVEN_M),
        "en": (_EN_SURNAMES, _EN_GIVEN_F, _EN_GIVEN_M),
    }[lang]
    surname = surnames[index % len(surnames)]
    given = (given_f if female else given_m)[index % 8]
    born = dt.date(rng.randrange(1950, 2004), rng.randrange(1, 13), rng.randrange(1, 29))
    streets, cities = {
        "hu": (_HU_STREETS, _HU_CITIES),
        "de": (_DE_STREETS, _DE_CITIES),
        "en": (_EN_STREETS, _EN_CITIES),
    }[lang]
    postcode, city = rng.choice(cities)
    number = rng.randrange(1, 90)
    street = (
        f"{rng.choice(streets)} {number}."
        if lang == "hu"
        else (
            f"{rng.choice(streets)} {number}" if lang == "de" else f"{number} {rng.choice(streets)}"
        )
    )
    local = f"{_ascii(given).lower()}.{_ascii(surname).lower()}"
    email = f"{local}@example.{('org', 'com', 'net')[index % 3]}"
    if lang == "hu":
        mobile = rng.choice(("20", "30", "70"))
        phone = f"+36 {mobile} {rng.randrange(100, 1000)} {rng.randrange(1000, 10000)}"
    elif lang == "de":
        phone = f"0{rng.choice(('151', '160', '172'))} {rng.randrange(10**7, 10**8)}"
    else:
        phone = f"07700 900{rng.randrange(1000):03d}"
    person = Person(
        lang, surname, given, female, born, rng.choice(_BIRTH_PLACES[lang]), street, postcode,
        city, email, phone,
    )  # fmt: skip
    if lang == "hu":
        person.ids = {
            "personal_id": hu_personal_id(rng, born, female),
            "taj": hu_taj(rng),
            "tax_id": hu_tax_id(rng, born),
            "id_card": f"{rng.randrange(10**6):06d}"
            f"{rng.choice('ABCDEHKLMN')}{rng.choice('ABCEHKLMNPRST')}",
            "passport": f"{rng.choice('BCEHK')}{rng.choice('ABCDEHK')}{rng.randrange(10**7):07d}",
            "licence": f"{rng.choice('BCEHK')}{rng.choice('ABCDEHK')}{rng.randrange(10**6):06d}",
            "member": f"{rng.randrange(10**8):08d}",
        }
    elif lang == "de":
        person.ids = {
            "steuer_id": de_steuer_id(rng),
            "sv_number": de_sv_number(rng, born, surname),
            "id_card": "".join(rng.choice("CFGHJKLMNPRTVWXYZ0123456789") for _ in range(9)),
            "passport": "C" + "".join(rng.choice("FGHJKLMNPRTVWXYZ0123456789") for _ in range(8)),
            "licence": "B" + "".join(rng.choice("0123456789ABCDEFGHJK") for _ in range(10)),
            "member": f"M-{rng.randrange(10**6):06d}",
        }
    else:
        person.ids = {
            "nino": uk_nino(rng),
            "id_card": f"ID{rng.randrange(10**7):07d}",
            "passport": f"{rng.randrange(10**9):09d}",
            "licence": f"{_ascii(surname).upper()[:5]:9<5}{rng.randrange(10**6):06d}AB9CD",
            "member": f"LIB-{rng.randrange(10**7):07d}",
        }
    return person


# --- MRZ (ICAO 9303 layout, fictional state) -----------------------------------------------


def _mrz_name(surname: str, given: str, width: int) -> str:
    name = f"{_ascii(surname).upper()}<<{_ascii(given).upper().replace(' ', '<')}"
    name = "".join(ch if ch.isalnum() or ch == "<" else "<" for ch in name)
    return name[:width].ljust(width, "<")


def _check(field_: str) -> str:
    from pii_guard.detect.checksums import mrz_check_digit

    return str(mrz_check_digit(field_))


def mrz_td3(person: Person, number: str, expiry: dt.date, personal: str = "") -> tuple[str, str]:
    """Passport MRZ: 2 x 44, every check digit valid."""
    doc = number.upper()[:9].ljust(9, "<")
    born, exp = f"{person.born:%y%m%d}", f"{expiry:%y%m%d}"
    sex = "F" if person.female else "M"
    optional = personal.upper()[:14].ljust(14, "<")
    opt_check = _check(optional) if personal else "<"
    line1 = f"P<{STATE}{_mrz_name(person.surname, person.given, 39)}"
    body = f"{doc}{_check(doc)}{STATE}{born}{_check(born)}{sex}{exp}{_check(exp)}"
    line2 = f"{body}{optional}{opt_check}"
    composite = line2[0:10] + line2[13:20] + line2[21:43]
    return line1, line2 + _check(composite)


def mrz_td1(person: Person, number: str, expiry: dt.date, optional: str = "") -> tuple[str, ...]:
    """ID card MRZ: 3 x 30, every check digit valid."""
    doc = number.upper()[:9].ljust(9, "<")
    born, exp = f"{person.born:%y%m%d}", f"{expiry:%y%m%d}"
    line1 = f"I<{STATE}{doc}{_check(doc)}{optional.upper()[:15].ljust(15, '<')}"
    line2 = f"{born}{_check(born)}{'F' if person.female else 'M'}{exp}{_check(exp)}{STATE}"
    line2 = line2.ljust(29, "<")
    composite = line1[5:30] + line2[0:7] + line2[8:15] + line2[18:29]
    line2 += _check(composite)
    return line1, line2, _mrz_name(person.surname, person.given, 30)


# --- composition ----------------------------------------------------------------------------

_FONT_DIRS = (
    Path("/System/Library/Fonts/Supplemental"),
    Path("/usr/share/fonts/truetype/dejavu"),
    Path("/usr/share/fonts/dejavu"),
    Path("C:/Windows/Fonts"),
)
_FONTS = {
    "sans": ("Arial.ttf", "DejaVuSans.ttf", "arial.ttf"),
    "bold": ("Arial Bold.ttf", "DejaVuSans-Bold.ttf", "arialbd.ttf"),
    "serif": ("Georgia.ttf", "DejaVuSerif.ttf", "georgia.ttf"),
    "mono": ("Courier New Bold.ttf", "DejaVuSansMono-Bold.ttf", "courbd.ttf"),
}
_font_cache: dict[tuple[str, int], Any] = {}


def font(kind: str, size: int) -> Any:
    from PIL import ImageFont

    key = (kind, size)
    if key not in _font_cache:
        for name in _FONTS[kind]:
            for folder in _FONT_DIRS:
                if (folder / name).is_file():
                    _font_cache[key] = ImageFont.truetype(str(folder / name), size)
                    break
            if key in _font_cache:
                break
        else:
            raise SystemExit(f"no {kind} font found (needs Hungarian accents); see _FONTS")
    return _font_cache[key]


Box = tuple[int, int, int, int]  # x1, y1, x2, y2 in pixels, exclusive end


@dataclass
class Canvas:
    image: Any
    regions: list[dict[str, Any]] = field(default_factory=list)
    other: list[dict[str, Any]] = field(default_factory=list)
    values: dict[str, str] = field(default_factory=dict)

    @property
    def draw(self) -> Any:
        from PIL import ImageDraw

        return ImageDraw.Draw(self.image)

    def label(self, type_: str, entity: str, box: Box, pad: int = 2) -> None:
        w, h = self.image.size
        x1, y1, x2, y2 = box
        box = (max(0, x1 - pad), max(0, y1 - pad), min(w, x2 + pad), min(h, y2 + pad))
        self.regions.append({"type": type_, "entity": entity, "px": list(box)})

    def text(
        self,
        xy: tuple[int, int],
        value: str,
        kind: str = "bold",
        size: int = 22,
        fill: tuple[int, int, int] = (20, 20, 25),
        entity: str | None = None,
        type_: str = "text",
    ) -> Box:
        f = font(kind, size)
        self.draw.text(xy, value, font=f, fill=fill)
        box = self.draw.textbbox(xy, value, font=f)
        if entity:
            self.label(type_, entity, box)
        return box

    def field(
        self, xy: tuple[int, int], caption: str, value: str, entity: str | None, size: int = 22
    ) -> int:
        """A caption over a value; returns the y below it."""
        x, y = xy
        self.text((x, y), caption, "sans", max(11, size // 2), (90, 96, 110))
        box = self.text((x, y + size // 2 + 4), value, "bold", size, entity=entity)
        return box[3] + max(8, size // 2)

    def inline(
        self, xy: tuple[int, int], parts: Iterable[tuple[str, str | None]], size: int = 20
    ) -> int:
        """One line of running text; ``(text, entity)`` parts with an entity are labelled."""
        x, y = xy
        f = font("serif", size)
        bottom = y
        for chunk, entity in parts:
            self.draw.text((x, y), chunk, font=f, fill=(25, 25, 30))
            box = self.draw.textbbox((x, y), chunk, font=f)
            if entity:
                self.label("text", entity, box)
            bottom = max(bottom, box[3])
            x += round(self.draw.textlength(chunk, font=f))
        return bottom


def _open(path: Path) -> Any:
    from PIL import Image

    with Image.open(path) as image:
        return image.convert("RGB")


def _cover(image: Any, size: tuple[int, int], focus_y: float = 0.5) -> Any:
    """Scale and crop ``image`` to fill ``size``."""
    from PIL import Image

    w, h = size
    scale = max(w / image.width, h / image.height)
    resized = image.resize(
        (math.ceil(image.width * scale), math.ceil(image.height * scale)),
        Image.Resampling.LANCZOS,
    )
    left = (resized.width - w) // 2
    top = round((resized.height - h) * focus_y)
    return resized.crop((left, top, left + w, top + h))


def texture(name: str, size: tuple[int, int], lighten: float) -> Any:
    from PIL import Image, ImageFilter

    path = cached_path(f"texture-{name}")
    if path is None:  # refused or not generated: a flat tint of our own
        base = Image.new("RGB", size, (228, 232, 238))
    else:
        # Softened: the texture is a backdrop, and fine grain only bloats the palette PNG.
        base = _cover(_open(path), size).filter(ImageFilter.GaussianBlur(4))
    return Image.blend(base, Image.new("RGB", size, (255, 255, 255)), lighten)


def portrait(index: int, size: tuple[int, int]) -> Any:
    path = cached_path(f"portrait-{index:02d}")
    if path is None:
        raise SystemExit(f"portrait-{index:02d} missing: run the 'assets' step first")
    return _cover(_open(path), size, focus_y=0.25)


def ink(asset_id: str, max_size: tuple[int, int], angle: float = 0.0) -> Any:
    """A signature or stamp scan as RGBA ink: paper becomes transparent, cropped to the ink."""
    from PIL import Image, ImageChops, ImageFilter, ImageOps

    path = cached_path(asset_id)
    if path is None:
        raise SystemExit(f"{asset_id} missing: run the 'assets' step first")
    rgb = _open(path)
    mx, my = rgb.width // 12, rgb.height // 12  # scan edges carry vignetting, not ink
    rgb = rgb.crop((mx, my, rgb.width - mx, rgb.height - my))
    gray = ImageOps.grayscale(rgb)
    # Ink is what is darker than the local paper (a median-filtered copy of the scan), so the
    # paper's shading and grain drop out.
    small = gray.resize((gray.width // 4, gray.height // 4))
    paper = small.filter(ImageFilter.MedianFilter(9)).resize(gray.size)
    darker = ImageChops.subtract(paper.filter(ImageFilter.GaussianBlur(8)), gray)
    alpha = darker.point(lambda v: 0 if v < 35 else min(255, round((v - 35) * 3)))
    rgba = rgb.copy()
    rgba.putalpha(alpha)
    if angle:
        rgba = rgba.rotate(angle, expand=True, resample=Image.Resampling.BICUBIC)
    bbox = _ink_bbox(rgba)
    if bbox:
        rgba = rgba.crop(bbox)
    rgba.thumbnail(max_size, Image.Resampling.LANCZOS)
    return rgba


def _ink_bbox(rgba: Any) -> tuple[int, int, int, int] | None:
    """Where the ink is, ignoring isolated specks of paper grain."""
    from PIL import ImageFilter

    alpha = rgba.getchannel("A").filter(ImageFilter.GaussianBlur(2))
    return alpha.point(lambda v: 255 if v > 60 else 0).getbbox()


def paste_ink(canvas: Canvas, rgba: Any, xy: tuple[int, int]) -> Box:
    canvas.image.paste(rgba, xy, rgba)
    bbox = _ink_bbox(rgba)
    if bbox is None:
        raise SystemExit("an ink asset came out empty")
    x, y = xy
    return (x + bbox[0], y + bbox[1], x + bbox[2], y + bbox[3])


def signature(canvas: Canvas, index: int, box: Box) -> None:
    x1, y1, x2, y2 = box
    rgba = ink(f"signature-{index % len(SIGNATURES):02d}", (x2 - x1, y2 - y1), angle=-3)
    pos = (x1 + (x2 - x1 - rgba.width) // 2, y1 + (y2 - y1 - rgba.height) // 2)
    canvas.label("signature", "SIGNATURE", paste_ink(canvas, rgba, pos), pad=3)


def stamp(canvas: Canvas, index: int, center: tuple[int, int], size: int) -> None:
    rgba = ink(f"stamp-{index % len(STAMPS):02d}", (size, size), angle=12)
    alpha = rgba.getchannel("A").point(lambda v: round(v * 0.8))
    rgba.putalpha(alpha)
    pos = (center[0] - rgba.width // 2, center[1] - rgba.height // 2)
    box = paste_ink(canvas, rgba, pos)
    canvas.other.append({"type": "stamp", "entity": "STAMP", "px": list(box)})


def photo(canvas: Canvas, index: int, box: Box) -> None:
    from PIL import ImageDraw

    x1, y1, x2, y2 = box
    canvas.image.paste(portrait(index, (x2 - x1, y2 - y1)), (x1, y1))
    ImageDraw.Draw(canvas.image).rectangle(box, outline=(120, 126, 140), width=1)
    canvas.label("portrait", "FACE", box, pad=0)


def mrz(canvas: Canvas, lines: Sequence[str], xy: tuple[int, int], size: int) -> None:
    f = font("mono", size)
    x, y = xy
    boxes = []
    for line in lines:
        canvas.draw.text((x, y), line, font=f, fill=(15, 15, 20))
        boxes.append(canvas.draw.textbbox((x, y), line, font=f))
        y += round(size * 1.35)
    canvas.label("mrz", "ID_DOCUMENT", (
        min(b[0] for b in boxes), min(b[1] for b in boxes),
        max(b[2] for b in boxes), max(b[3] for b in boxes),
    ), pad=3)  # fmt: skip
    canvas.values["mrz"] = "\n".join(lines)


def overprint(canvas: Canvas, size: int, note: str) -> None:
    """The specimen marks: a diagonal ``MINTA / SPECIMEN`` and a footer line."""
    from PIL import Image, ImageDraw

    w, h = canvas.image.size
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    text = Image.new("RGBA", (w * 2, size * 2), (0, 0, 0, 0))
    d = ImageDraw.Draw(text)
    f = font("bold", size)
    d.text((10, 10), SPECIMEN, font=f, fill=(200, 30, 40, 80))
    text = text.crop(text.getbbox()).rotate(
        math.degrees(math.atan2(h, w)) * 0.7, expand=True, resample=Image.Resampling.BICUBIC
    )
    layer.paste(text, ((w - text.width) // 2, (h - text.height) // 2), text)
    base = canvas.image.convert("RGBA")
    canvas.image = Image.alpha_composite(base, layer).convert("RGB")
    draw = canvas.draw
    line = f"{SPECIMEN} · {note}"
    px = max(11, size // 6)
    while draw.textlength(line, font=font("bold", px)) > w - 80 and px > 11:
        px -= 1
    small = font("bold", px)
    tw = draw.textlength(line, font=small)
    box = draw.textbbox(((w - tw) / 2, h - px - 14), line, font=small)
    draw.rectangle((box[0] - 6, box[1] - 3, box[2] + 6, box[3] + 3), fill=(200, 30, 40))
    draw.text(((w - tw) / 2, h - px - 14), line, font=small, fill=(255, 255, 255))
    canvas.other.append({"type": "overprint", "entity": None, "px": [0, 0, w, h]})


def rounded_card(size: tuple[int, int], bg: Any, margin: int = 18, radius: int = 28) -> Any:
    from PIL import Image, ImageDraw

    w, h = size
    out = Image.new("RGB", (w, h), (246, 246, 244))
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle((margin, margin, w - margin, h - margin), radius, 255)
    out.paste(bg, (0, 0), mask)
    ImageDraw.Draw(out).rounded_rectangle(
        (margin, margin, w - margin, h - margin), radius, outline=(170, 176, 188), width=2
    )
    return out


# Captions per language. The issuer is fictional on purpose; nothing names a real authority.
T: dict[str, dict[str, str]] = {
    "hu": {
        "issuer": "KITALÁLT MINTAHATÓSÁG · FICTIONAL SPECIMEN AUTHORITY",
        "id_card": "AZONOSÍTÓ KÁRTYA · IDENTITY CARD",
        "passport": "ÚTLEVÉL · PASSPORT",
        "licence": "VEZETŐI ENGEDÉLY · DRIVING LICENCE",
        "member": "EGÉSZSÉGKÁRTYA · HEALTH CARD",
        "surname": "Családi név / Surname",
        "given": "Utónév / Given names",
        "name": "Név / Name",
        "born": "Születési idő / Date of birth",
        "place": "Születési hely / Place of birth",
        "doc_no": "Okmányszám / Document no.",
        "personal": "Személyi azonosító / Personal no.",
        "expiry": "Érvényes / Expiry",
        "nationality": "Állampolgárság / Nationality",
        "sex": "Nem / Sex",
        "signature": "Aláírás / Signature",
        "address": "Lakcím / Address",
        "categories": "Kategóriák / Categories",
        "taj": "TAJ szám",
        "note": "MI által generált fiktív minta · AI-generated fictional specimen",
        "form": "JELENTKEZÉSI LAP",
        "email": "E-mail",
        "phone": "Telefon",
        "tax": "Adóazonosító jel",
        "date_format": "%Y.%m.%d.",
    },
    "de": {
        "issuer": "FIKTIVE MUSTERBEHÖRDE · FICTIONAL SPECIMEN AUTHORITY",
        "id_card": "AUSWEISKARTE · IDENTITY CARD",
        "passport": "REISEPASS · PASSPORT",
        "licence": "FAHRERLAUBNIS · DRIVING LICENCE",
        "member": "MITGLIEDSAUSWEIS · MEMBER CARD",
        "surname": "Name / Surname",
        "given": "Vornamen / Given names",
        "name": "Name",
        "born": "Geburtsdatum / Date of birth",
        "place": "Geburtsort / Place of birth",
        "doc_no": "Ausweisnummer / Document no.",
        "personal": "Steuer-ID",
        "expiry": "Gültig bis / Expiry",
        "nationality": "Staatsangehörigkeit / Nationality",
        "sex": "Geschlecht / Sex",
        "signature": "Unterschrift / Signature",
        "address": "Anschrift / Address",
        "categories": "Klassen / Categories",
        "taj": "Versicherungsnummer",
        "note": "KI-generiertes fiktives Muster · AI-generated fictional specimen",
        "form": "ANMELDEFORMULAR",
        "email": "E-Mail",
        "phone": "Telefon",
        "tax": "Steuer-ID",
        "date_format": "%d.%m.%Y",
    },
    "en": {
        "issuer": "FICTIONAL SPECIMEN AUTHORITY",
        "id_card": "IDENTITY CARD",
        "passport": "PASSPORT",
        "licence": "DRIVING LICENCE",
        "member": "LIBRARY CARD",
        "surname": "Surname",
        "given": "Given names",
        "name": "Name",
        "born": "Date of birth",
        "place": "Place of birth",
        "doc_no": "Document no.",
        "personal": "National Insurance no.",
        "expiry": "Expiry",
        "nationality": "Nationality",
        "sex": "Sex",
        "signature": "Signature",
        "address": "Address",
        "categories": "Categories",
        "taj": "Member no.",
        "note": "AI-generated fictional specimen",
        "form": "APPLICATION FORM",
        "email": "Email",
        "phone": "Phone",
        "tax": "National Insurance no.",
        "date_format": "%d %b %Y",
    },
}
_EXPIRY = dt.date(2031, 6, 30)


def _date(person: Person, value: dt.date) -> str:
    return (
        value.strftime(T[person.lang]["date_format"]).upper()
        if person.lang == "en"
        else (value.strftime(T[person.lang]["date_format"]))
    )


def _personal_value(p: Person) -> tuple[str, str]:
    """The national number shown on cards: (value, entity)."""
    if p.lang == "hu":
        return p.ids["personal_id"], "ID_DOCUMENT"
    if p.lang == "de":
        return p.ids["steuer_id"], "ID_DOCUMENT"
    return p.ids["nino"], "ID_DOCUMENT"


def _header(c: Canvas, p: Person, title: str, band: tuple[int, int, int], height: int) -> None:
    w = c.image.width
    c.draw.rectangle((18, 18, w - 18, 18 + height), fill=band)
    c.text((44, 26), T[p.lang]["issuer"], "sans", 15, (240, 242, 246))
    c.text((44, 26 + 22), T[p.lang][title], "bold", 26, (255, 255, 255))


def id_front(p: Person, face: int, sig: int, tex: str, band: tuple[int, int, int]) -> Canvas:
    t = T[p.lang]
    c = Canvas(rounded_card((1012, 638), texture(tex, (1012, 638), 0.45)))
    _header(c, p, "id_card", band, 72)
    photo(c, face, (48, 120, 288, 432))
    x, y = 320, 112
    y = c.field((x, y), t["surname"], p.surname.upper(), "PERSON")
    y = c.field((x, y), t["given"], p.given.upper(), "PERSON")
    y2 = c.field((x, y), t["born"], _date(p, p.born), "DATE_OF_BIRTH")
    c.field((x + 330, y), t["sex"], "F" if p.female else "M", None)
    y = y2
    y2 = c.field((x, y), t["doc_no"], p.ids["id_card"], "ID_DOCUMENT")
    c.field((x + 330, y), t["nationality"], STATE, None)
    y = y2
    if p.lang == "hu":
        y = c.field((x, y), t["personal"], p.ids["personal_id"], "ID_DOCUMENT")
    c.field((x, y), t["expiry"], _date(p, _EXPIRY), None)
    c.text((48, 450), t["signature"], "sans", 12, (90, 96, 110))
    signature(c, sig, (48, 468, 330, 560))
    overprint(c, 120, t["note"])
    c.values.update(name=p.full_name, born=str(p.born), doc=p.ids["id_card"])
    return c


def id_back(p: Person, tex: str) -> Canvas:
    t = T[p.lang]
    c = Canvas(rounded_card((1012, 638), texture(tex, (1012, 638), 0.5)))
    y = c.field((48, 50), t["address"], p.address, "ADDRESS")
    y = c.field((48, y), t["place"], p.birth_place, "PLACE_OF_BIRTH")
    if p.lang == "de":
        y = c.field((48, y), t["personal"], p.ids["steuer_id"], "ID_DOCUMENT")
    c.text((48, y), t["issuer"], "sans", 14, (90, 96, 110))
    c.draw.rectangle((30, 395, 982, 600), fill=(250, 250, 248))
    personal = p.ids.get("personal_id", "")
    mrz(c, mrz_td1(p, p.ids["id_card"], _EXPIRY, personal), (60, 410), 40)
    overprint(c, 120, t["note"])
    c.values.update(address=p.address, doc=p.ids["id_card"])
    return c


def passport(p: Person, face: int, sig: int, tex: str) -> Canvas:
    t = T[p.lang]
    c = Canvas(rounded_card((1250, 880), texture(tex, (1250, 880), 0.5), radius=10))
    c.text((50, 40), t["issuer"], "sans", 18, (70, 76, 90))
    c.text((50, 66), t["passport"], "bold", 30, (40, 50, 80))
    photo(c, face, (50, 130, 340, 510))
    x, y = 380, 120
    y = c.field((x, y), t["surname"], p.surname.upper(), "PERSON", 24)
    y = c.field((x, y), t["given"], p.given.upper(), "PERSON", 24)
    y2 = c.field((x, y), t["nationality"], STATE, None, 24)
    c.field((x + 420, y), t["doc_no"], p.ids["passport"], "ID_DOCUMENT", 24)
    y = y2
    y2 = c.field((x, y), t["born"], _date(p, p.born), "DATE_OF_BIRTH", 24)
    c.field((x + 420, y), t["sex"], "F" if p.female else "M", None, 24)
    y = y2
    y2 = c.field((x, y), t["place"], p.birth_place, "PLACE_OF_BIRTH", 24)
    c.field((x + 420, y), t["expiry"], _date(p, _EXPIRY), None, 24)
    y = y2
    value, entity = _personal_value(p)
    c.field((x, y), t["personal"], value, entity, 24)
    c.text((380, 545), t["signature"], "sans", 13, (90, 96, 110))
    signature(c, sig, (380, 565, 760, 650))
    c.draw.rectangle((30, 690, 1220, 850), fill=(250, 250, 248))
    personal = p.ids.get("personal_id", "")
    mrz(c, mrz_td3(p, p.ids["passport"], _EXPIRY, personal), (50, 708), 42)
    overprint(c, 150, t["note"])
    c.values.update(name=p.full_name, doc=p.ids["passport"])
    return c


def driving_licence(p: Person, face: int, sig: int, tex: str) -> Canvas:
    t = T[p.lang]
    c = Canvas(rounded_card((1012, 638), texture(tex, (1012, 638), 0.4)))
    _header(c, p, "licence", (150, 70, 60), 72)
    photo(c, face, (680, 120, 944, 452))
    x, y = 48, 112
    y = c.field((x, y), t["name"], p.full_name, "PERSON")
    y = c.field((x, y), t["born"], f"{_date(p, p.born)}  {p.birth_place}", "DATE_OF_BIRTH")
    y = c.field((x, y), t["doc_no"], p.ids["licence"], "ID_DOCUMENT")
    y = c.field((x, y), t["expiry"], _date(p, _EXPIRY), None)
    c.field((x, y), t["categories"], "AM  A1  B  BE", None)
    c.text((48, 470), t["signature"], "sans", 12, (90, 96, 110))
    signature(c, sig, (48, 488, 360, 570))
    overprint(c, 110, t["note"])
    c.values.update(name=p.full_name, doc=p.ids["licence"])
    return c


def badge(p: Person, face: int, company: str, tex: str) -> Canvas:
    from PIL import ImageDraw

    t = T[p.lang]
    c = Canvas(rounded_card((640, 960), texture(tex, (640, 960), 0.3), radius=36))
    ImageDraw.Draw(c.image).rounded_rectangle((270, 36, 370, 52), 8, fill=(200, 204, 214))
    c.text((60, 80), company, "bold", 30, (60, 50, 110))
    c.text((60, 120), {"hu": "LÁTOGATÓ · VISITOR", "de": "BESUCHER · VISITOR"}.get(
        p.lang, "VISITOR"), "sans", 18, (90, 96, 110))  # fmt: skip
    photo(c, face, (170, 170, 470, 550))
    c.text((60, 585), p.full_name, "bold", 40, entity="PERSON")
    c.text((60, 650), p.email, "sans", 26, (40, 40, 50), entity="EMAIL")
    c.text((60, 695), p.phone, "sans", 26, (40, 40, 50), entity="PHONE")
    overprint(c, 90, t["note"])
    c.values.update(name=p.full_name, email=p.email, phone=p.phone)
    return c


def member_card(p: Person, face: int, tex: str) -> Canvas:
    t = T[p.lang]
    c = Canvas(rounded_card((1012, 638), texture(tex, (1012, 638), 0.4)))
    _header(c, p, "member", (40, 110, 90), 72)
    photo(c, face, (48, 120, 268, 400))
    x, y = 300, 120
    y = c.field((x, y), t["name"], p.full_name, "PERSON")
    y = c.field((x, y), t["born"], _date(p, p.born), "DATE_OF_BIRTH")
    if p.lang == "hu":
        taj = p.ids["taj"]
        y = c.field((x, y), t["taj"], f"{taj[:3]} {taj[3:6]} {taj[6:]}", "NATIONAL_ID_HU_TAJ")
    elif p.lang == "de":
        y = c.field((x, y), t["taj"], p.ids["sv_number"], "ID_DOCUMENT")
    else:
        y = c.field((x, y), t["taj"], p.ids["member"], "ID_DOCUMENT")
    c.field((x, y), t["address"], p.address, "ADDRESS")
    overprint(c, 110, t["note"])
    c.values.update(name=p.full_name)
    return c


_LETTER = {
    "hu": {
        "company": "Mintavállalat Kft.",
        "company_line": "1111 Budapest, Kitalált körút 1. · info@example.com",
        "subject": "Tárgy: Munkáltatói igazolás",
        "greeting": "Tisztelt {name}!",
        "body": (
            "Ezúton igazoljuk, hogy Ön 2019 óta munkatársunk.",
            "Kérjük, adatait a következő elérhetőségeken erősítse meg:",
        ),
        "regards": "Üdvözlettel:",
        "role": "ügyvezető",
    },
    "de": {
        "company": "Musterfirma GmbH",
        "company_line": "Beispielplatz 1, 10115 Berlin · info@example.com",
        "subject": "Betreff: Arbeitgeberbescheinigung",
        "greeting": "Sehr geehrte(r) {name},",
        "body": (
            "hiermit bestätigen wir Ihre Beschäftigung seit 2019.",
            "Bitte bestätigen Sie Ihre Angaben über folgende Kontakte:",
        ),
        "regards": "Mit freundlichen Grüßen",
        "role": "Geschäftsführung",
    },
    "en": {
        "company": "Example Trading Ltd",
        "company_line": "1 Placeholder Square, York YO1 7HH · info@example.com",
        "subject": "Re: Confirmation of employment",
        "greeting": "Dear {name},",
        "body": (
            "We confirm that you have worked for us since 2019.",
            "Please confirm your details using the contacts below:",
        ),
        "regards": "Yours sincerely,",
        "role": "Managing Director",
    },
}


def letter(p: Person, signer: Person, sig: int, stamp_index: int) -> Canvas:
    from PIL import ImageDraw

    t, L = T[p.lang], _LETTER[p.lang]
    c = Canvas(texture("paper", (1000, 1414), 0.35))
    ImageDraw.Draw(c.image).rectangle((0, 0, 1000, 12), fill=(60, 90, 140))
    c.text((80, 60), L["company"], "bold", 34, (40, 60, 110))
    c.text((80, 106), L["company_line"], "sans", 17, (90, 96, 110))
    c.draw.line((80, 140, 920, 140), fill=(170, 176, 188), width=2)
    c.text((80, 190), p.full_name, "serif", 22, entity="PERSON")
    c.text((80, 222), p.address, "serif", 22, entity="ADDRESS")
    c.text((640, 190), _date(p, dt.date(2026, 10, 12)), "serif", 20)
    c.text((80, 320), L["subject"], "bold", 22)
    y = 380
    c.inline((80, y), [(L["greeting"].split("{name}")[0], None), (p.full_name, "PERSON"),
                       (L["greeting"].split("{name}")[1], None)])  # fmt: skip
    y += 50
    for line in L["body"]:
        c.inline((80, y), [(line, None)])
        y += 36
    y += 10
    c.inline((110, y), [(f"{t['email']}: ", None), (p.email, "EMAIL")])
    y += 36
    c.inline((110, y), [(f"{t['phone']}: ", None), (p.phone, "PHONE")])
    y += 36
    tax = {"hu": p.ids.get("tax_id"), "de": p.ids.get("steuer_id"), "en": p.ids.get("nino")}
    entity = "NATIONAL_ID_HU_TAX" if p.lang == "hu" else "ID_DOCUMENT"
    c.inline((110, y), [(f"{t['tax']}: ", None), (tax[p.lang] or "", entity)])
    y += 80
    c.inline((80, y), [(L["regards"], None)])
    signature(c, sig, (80, y + 40, 420, y + 150))
    stamp(c, stamp_index, (600, y + 100), 190)
    c.text((80, y + 165), signer.full_name, "serif", 22, entity="PERSON")
    c.text((80, y + 197), L["role"], "serif", 18, (90, 96, 110))
    overprint(c, 170, t["note"])
    c.values.update(name=p.full_name, signer=signer.full_name)
    return c


def form(p: Person, face: int, sig: int) -> Canvas:
    t = T[p.lang]
    c = Canvas(texture("paper", (1000, 1414), 0.25))
    c.text((80, 70), t["form"], "bold", 36, (40, 50, 80))
    c.text((80, 120), t["issuer"], "sans", 16, (90, 96, 110))
    photo(c, face, (720, 70, 920, 330))
    rows = [
        (t["name"], p.full_name, "PERSON"),
        (t["born"], _date(p, p.born), "DATE_OF_BIRTH"),
        (t["place"], p.birth_place, "PLACE_OF_BIRTH"),
        (t["address"], p.address, "ADDRESS"),
        (t["email"], p.email, "EMAIL"),
        (t["phone"], p.phone, "PHONE"),
    ]
    value, entity = _personal_value(p)
    rows.append((t["personal"] if p.lang != "hu" else t["tax"],
                 p.ids["tax_id"] if p.lang == "hu" else value,
                 "NATIONAL_ID_HU_TAX" if p.lang == "hu" else entity))  # fmt: skip
    y = 380
    for caption, val, ent in rows:
        c.text((80, y), caption, "sans", 16, (90, 96, 110))
        c.draw.rectangle((80, y + 24, 920, y + 72), outline=(170, 176, 188), width=2)
        c.text((96, y + 34), val, "sans", 24, (20, 30, 90), entity=ent)
        y += 100
    c.text((80, y + 20), t["signature"], "sans", 16, (90, 96, 110))
    c.draw.line((80, y + 150, 520, y + 150), fill=(120, 126, 140), width=2)
    signature(c, sig, (90, y + 45, 500, y + 145))
    c.text((600, y + 120), _date(p, dt.date(2026, 10, 20)), "sans", 22, (20, 30, 90))
    overprint(c, 170, t["note"])
    c.values.update(name=p.full_name, email=p.email)
    return c


@dataclass(frozen=True, slots=True)
class DocSpec:
    id: str
    lang: str
    doc_type: str
    side: str
    build: Callable[[], Canvas]


def document_plan() -> list[DocSpec]:
    """24 documents: 8 types x 3 language variants, 18 generated faces, 6 signatures."""
    specs: list[DocSpec] = []
    faces = iter(range(len(PEOPLE)))
    sig = 0
    company = {"hu": "Mintavállalat Kft.", "de": "Musterfirma GmbH", "en": "Example Trading"}
    for li, lang in enumerate(LANGUAGES):
        f = [next(faces) for _ in range(6)]  # this variant's six faces
        # The first six people have a portrait, and their sex follows it.
        people = [make_person(lang, i, _FEMALE[f[i]] if i < 6 else i % 2 == 0) for i in range(8)]
        tex = ("card-blue", "card-green", "card-rose")[li]
        band = ((40, 70, 120), (60, 100, 80), (110, 60, 90))[li]
        p = people

        def add(doc_type: str, side: str, build: Callable[[], Canvas], lang: str = lang) -> None:
            specs.append(DocSpec(f"{lang}-{doc_type}-{side}", lang, doc_type, side, build))

        s = sig
        add("id_card", "front", lambda p=p, f=f, s=s, tex=tex, band=band: id_front(
            p[0], f[0], s, tex, band))  # fmt: skip
        add("id_card", "back", lambda p=p, tex=tex: id_back(p[0], tex))
        add("passport", "data_page", lambda p=p, f=f, s=s: passport(p[1], f[1], s + 1, "card-grey"))
        add("driving_licence", "front", lambda p=p, f=f, s=s, lang=lang: driving_licence(
            p[2], f[2], s + 2, "card-rose" if lang != "en" else "card-blue"))  # fmt: skip
        add("badge", "front", lambda p=p, f=f, lang=lang: badge(p[3], f[3], company[lang], "badge"))
        add("member_card", "front", lambda p=p, f=f, tex=tex: member_card(p[4], f[4], tex))
        add("form", "page", lambda p=p, f=f, s=s: form(p[5], f[5], s + 3))
        add("letter", "page", lambda p=p, s=s, li=li: letter(p[6], p[7], s + 4, li))
        sig += 2
    return specs


def _optimise_png(image: Any) -> bytes:
    """A palette PNG (256 colours, dithered): photographic parts stay recognisable, and a
    card stays in the low hundreds of kB."""
    from PIL import Image

    quantised = image.quantize(
        colors=256, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.FLOYDSTEINBERG
    )
    buf = io.BytesIO()
    quantised.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def compose(out_dir: Path) -> int:
    record = _load_record()
    images_dir = out_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)
    manifest: list[dict[str, Any]] = []
    labels: dict[str, Any] = {}
    docs: list[dict[str, Any]] = []
    for spec in document_plan():
        canvas = spec.build()
        data = _optimise_png(canvas.image)
        sha = hashlib.sha256(data).hexdigest()
        name = f"{spec.id}.png"
        (images_dir / name).write_bytes(data)
        w, h = canvas.image.size

        def frac(px: Sequence[int], w: int = w, h: int = h) -> list[float]:
            return [
                round(px[0] / w, 4),
                round(px[1] / h, 4),
                round(px[2] / w, 4),
                round(px[3] / h, 4),
            ]

        manifest.append({
            "id": spec.id, "country": COUNTRY[spec.lang], "language": spec.lang,
            "doc_type": spec.doc_type, "side": spec.side, "file": name, "sha256": sha,
            "width": w, "height": h, "bytes": len(data),
        })  # fmt: skip
        labels[sha] = {
            "id": spec.id,
            "regions": [
                {"type": r["type"], "entity": r["entity"], "box": frac(r["px"])}
                for r in canvas.regions
            ],
            "unscored": [
                {"type": r["type"], "entity": r["entity"], "box": frac(r["px"])}
                for r in canvas.other
            ],
        }
        docs.append({"id": spec.id, "values": canvas.values})
        print(f"  {name}: {len(data) // 1024} kB, {len(canvas.regions)} regions")
    (out_dir / "manifest.json").write_text(json.dumps({
        "version": 1,
        "description": "Fictional specimen-style documents (LAB-1121): Muse Image portraits, "
        "signatures, stamps and textures, laid out and labelled by eval/visual/generate_images.py. "
        "'country' names whose number formats a variant uses; every issuer is fictional (UTO).",
        "out_dir": "eval/fixtures/visual/images",
        "specimens": manifest,
    }, indent=2, ensure_ascii=False) + "\n", "utf-8")  # fmt: skip
    (out_dir / "labels.json").write_text(json.dumps({
        "version": 1,
        "description": "Exact personal-data regions of the fictional documents in manifest.json, "
        "keyed by image SHA-256. Known from the composition step (where each value, portrait, "
        "signature and MRZ was drawn), not drawn by hand.",
        "box_format": "[x1, y1, x2, y2] as fractions of the image width and height",
        "method": "Pillow text bounding boxes (+2 px), pasted portrait rectangles, the ink "
        "bounding box of each pasted signature (+3 px) and the MRZ lines (+3 px).",
        "region_types": {
            "portrait": "the generated face photo",
            "signature": "a generated handwritten signature",
            "mrz": "the machine-readable zone (all lines, valid check digits)",
            "text": "one personal-data value; 'entity' says which kind",
        },
        "unscored_types": {
            "stamp": "a generated rubber stamp (STAMP is kept by the default policy)",
            "overprint": "the MINTA / SPECIMEN marks (whole image)",
        },
        "specimens": labels,
    }, indent=2, ensure_ascii=False) + "\n", "utf-8")  # fmt: skip
    record["documents"] = docs
    record["composed_with"] = {
        "script": "eval/visual/generate_images.py",
        "png": "256-colour palette",
    }
    _save_record(record)
    total = sum(m["bytes"] for m in manifest)
    print(f"{len(manifest)} documents, {total / 1e6:.2f} MB")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("step", choices=("probe", "assets", "compose"))
    parser.add_argument("--budget", type=float, default=DEFAULT_BUDGET, help="USD, all calls")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--out", type=Path, default=OUT_DIR)
    args = parser.parse_args(argv)
    if args.step == "probe":
        return run_calls([Asset(i, "probe", p) for i, p in PROBES], args.budget, args.workers)
    if args.step == "assets":
        return run_calls(asset_plan(), args.budget, args.workers)
    return compose(args.out)


if __name__ == "__main__":
    sys.exit(main())
