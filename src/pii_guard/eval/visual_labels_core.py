"""Fixtures, OCR cache, near-namesakes, and baseline matchers for visual label eval."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import random
import unicodedata
from collections.abc import Sequence
from pathlib import Path
from typing import Any, ClassVar

from PIL import Image

from pii_guard.types import EntityType, Span
from pii_guard.vault import VaultSession, normalize_value
from pii_guard.visual.fuzzy import Candidate, Match
from pii_guard.visual.image import load_image
from pii_guard.visual.labels import VaultMatcher
from pii_guard.visual.ocr import OcrWord
from pii_guard.visual.regions import Box, Region

FIXTURES = Path("eval/fixtures/visual")
OCR_CACHE = FIXTURES / "ocr" / "tesseract.json"
NAMESAKES = FIXTURES / "near-namesakes.json"
#: The vault key of the eval (fictional data, a throwaway session).
EVAL_KEY = b"pii-guard-eval-lab-1156-vault-key"
#: Gold value keys in generation.json and their entity types.
GOLD_TYPES: dict[str, EntityType] = {
    "name": EntityType.PERSON,
    "signer": EntityType.PERSON,
    "doc": EntityType.ID_DOCUMENT,
    "born": EntityType.DATE_OF_BIRTH,
    "email": EntityType.EMAIL,
    "phone": EntityType.PHONE,
    "address": EntityType.ADDRESS,
}
_CONFUSIONS = {
    "o": "0",
    "O": "0",
    "0": "O",
    "i": "1",
    "I": "1",
    "l": "1",
    "1": "I",
    "s": "5",
    "S": "5",
    "B": "8",
    "Z": "2",
    "e": "c",
    "u": "v",
}


# --- fixtures --------------------------------------------------------------------------------


def load_gold(root: Path = FIXTURES) -> dict[str, dict[str, str]]:
    """Document id -> ``{key: value}`` of the printed personal values (``mrz`` dropped)."""
    record = json.loads((root / "generation.json").read_text(encoding="utf-8"))
    out: dict[str, dict[str, str]] = {}
    for doc in record.get("documents", []):
        values = {k: v for k, v in doc["values"].items() if k in GOLD_TYPES and v}
        out[doc["id"]] = values
    return out


def _manifest(root: Path = FIXTURES) -> list[dict[str, Any]]:
    return json.loads((root / "manifest.json").read_text(encoding="utf-8"))["specimens"]


def pixel_key(image: Image.Image) -> str:
    """The OCR cache key of a decoded image: SHA-256 of its size and RGB pixels."""
    digest = hashlib.sha256(f"{image.width}x{image.height}".encode())
    digest.update(image.convert("RGB").tobytes())
    return digest.hexdigest()


def _word_to_json(word: OcrWord) -> list[Any]:
    return [word.text, *word.box.to_list(), list(word.line)]


def _word_from_json(item: Sequence[Any]) -> OcrWord:
    text, x1, y1, x2, y2, line = item
    return OcrWord(str(text), Box(int(x1), int(y1), int(x2), int(y2)), tuple(int(n) for n in line))


class CachedOcr:
    """An OCR engine that returns recorded words, keyed by the image's pixels."""

    name = "tesseract-cached"

    def __init__(self, words: dict[str, list[OcrWord]] | None = None) -> None:
        self._words = dict(words or {})

    @classmethod
    def load(cls, path: Path = OCR_CACHE) -> CachedOcr:
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            {
                key: [_word_from_json(w) for w in entry["words"]]
                for key, entry in data["images"].items()
            }
        )

    def add(self, image: Image.Image, words: list[OcrWord]) -> None:
        self._words[pixel_key(image)] = list(words)

    def words(self, image: Image.Image) -> list[OcrWord]:
        key = pixel_key(image)
        if key not in self._words:
            raise KeyError("no recorded OCR words for this image (run --record-ocr)")
        return list(self._words[key])


def record_ocr(root: Path = FIXTURES, path: Path = OCR_CACHE) -> int:  # pragma: no cover
    """Re-record :data:`OCR_CACHE` with Tesseract (needs the ``ocr`` extra and the binary)."""
    import pytesseract

    from pii_guard.visual.ocr import TesseractOcr

    ocr = TesseractOcr()
    images: dict[str, Any] = {}
    for entry in _manifest(root):
        image = load_image((root / "images" / entry["file"]).read_bytes())
        images[pixel_key(image)] = {
            "id": entry["id"],
            "words": [_word_to_json(w) for w in ocr.words(image)],
        }
    from pii_guard.eval.visual_labels import _demo_card_words

    base, demo_words = _demo_card_words(CachedOcrFromDict(images), root)
    images[pixel_key(base)] = {"id": "demo-expired-card", "words": demo_words}
    payload = {
        "version": 1,
        "description": "Tesseract words of the fictional documents in manifest.json (LAB-1121) "
        "and of the demo's reprinted card, recorded by pii_guard.eval.visual_labels "
        "--record-ocr. All fictional. Key: SHA-256 of the decoded image size and RGB pixels.",
        "engine": f"tesseract {pytesseract.get_tesseract_version()} hun+eng, upscale_to 2000",
        "images": images,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"recorded OCR words of {len(images)} images to {path}")
    return 0


class CachedOcrFromDict(CachedOcr):  # pragma: no cover - only for record_ocr
    def __init__(self, images: dict[str, Any]) -> None:
        super().__init__({k: [_word_from_json(w) for w in v["words"]] for k, v in images.items()})


# --- near-namesakes and noise ---------------------------------------------------------------

_VOWELS = "aeiou"
_SWAP = {"a": "o", "o": "a", "e": "a", "i": "a", "u": "a"}
#: OCR-confusable letters for the namesakes (LAB-1211, LAB-1225): a letter OCR reads for
#: another. Names swap the last ``l``/``i`` of a token (either direction, case kept);
#: document numbers the last capital ``I``/``L``, ``U``/``V`` or ``C``/``E``. Small
#: ``e``/``c`` and ``u``/``v`` are never swapped: the ``--noise`` model produces those,
#: so a noisy read would *be* the namesake.
_CONFUSABLE_NAME = {"l": "i", "i": "l", "L": "I", "I": "L"}
_CONFUSABLE_DOC = {"I": "L", "L": "I", "U": "V", "V": "U", "C": "E", "E": "C"}


def _strip(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def _namesake_token(token: str) -> str:
    """``token`` with one real (non-OCR-confusion) letter changed: its last vowel swapped."""
    letters = list(token)
    for index in range(len(letters) - 1, -1, -1):
        base = _strip(letters[index]).lower()
        if base in _VOWELS:
            new = _SWAP[base]
            letters[index] = new.upper() if letters[index].isupper() else new
            return "".join(letters)
    return token + ("a" if token[-1:].islower() else "A")


def _confusable_token(token: str) -> str | None:
    """``token`` with its last OCR-confusable letter swapped (``l``<->``i``), or ``None``.

    Accents are ignored when looking (``Fiktív`` confuses like ``Fiktiv``), but the
    replacement is the plain letter, as OCR would read it."""
    base = _strip(token)
    if len(base) != len(token):
        base = token
    for index in range(len(token) - 1, -1, -1):
        if base[index] in _CONFUSABLE_NAME:
            return token[:index] + _CONFUSABLE_NAME[base[index]] + token[index + 1 :]
    return None


def _confusable_doc(value: str) -> str | None:
    """``value`` with its last confusable capital swapped (``I``<->``L`` etc.), or ``None``."""
    for index in range(len(value) - 1, -1, -1):
        if value[index] in _CONFUSABLE_DOC:
            return value[:index] + _CONFUSABLE_DOC[value[index]] + value[index + 1 :]
    return None


def near_namesakes(key: str, value: str) -> list[str]:
    """Different values that look like ``value``: same surname with another given name and
    vice versa for names; one digit changed for numbers; the day moved for dates."
    Names and document numbers also get their OCR-confusable variants (LAB-1211)."""
    entity_type = GOLD_TYPES[key]
    if entity_type is EntityType.PERSON:
        tokens = value.split()
        if len(tokens) < 2:
            out = [_namesake_token(value)]
            if (confusable := _confusable_token(value)) is not None:
                out.append(confusable)
            return out
        first = " ".join([_namesake_token(tokens[0]), *tokens[1:]])
        last = " ".join([*tokens[:-1], _namesake_token(tokens[-1])])
        out = [first, last]
        first_confusable = _confusable_token(tokens[0])
        if first_confusable is not None:
            candidate = " ".join([first_confusable, *tokens[1:]])
            if candidate not in out:
                out.append(candidate)
        last_confusable = _confusable_token(tokens[-1])
        if last_confusable is not None:
            candidate = " ".join([*tokens[:-1], last_confusable])
            if candidate not in out:
                out.append(candidate)
        return out
    if entity_type is EntityType.DATE_OF_BIRTH:
        day = dt.date.fromisoformat(value)
        return [(day + dt.timedelta(days=3)).isoformat()]
    if entity_type is EntityType.ID_DOCUMENT:
        digits = [i for i, c in enumerate(value) if c.isdigit()]
        if not digits:
            return []
        i = digits[len(digits) // 2]
        out = [value[:i] + str((int(value[i]) + 3) % 10) + value[i + 1 :]]
        if (confusable := _confusable_doc(value)) is not None and confusable not in out:
            out.append(confusable)
        return out
    return []


def write_namesakes(root: Path = FIXTURES, path: Path = NAMESAKES) -> int:  # pragma: no cover
    gold = load_gold(root)
    items = [
        {"document": doc, "key": key, "namesakes": names}
        for doc, values in sorted(gold.items())
        for key, value in sorted(values.items())
        if (names := near_namesakes(key, value))
    ]
    payload = {
        "version": 1,
        "description": "Near-namesakes of the personal values in generation.json (LAB-1156): "
        "different people and documents that look alike (one real letter or digit changed). "
        "Matching an image value to one of them is a false merge. All fictional; generated by "
        "pii_guard.eval.visual_labels --write-namesakes, then extended (LAB-1211) with "
        "OCR-confusable namesakes: one letter swapped for a letter OCR reads for it "
        "(names: l/i, Ilse/Iise; document numbers: capital I/L, U/V, C/E, XJXK86KV4/XJXK86KU4). "
        "Regenerating with --write-namesakes drops those; keep them.",
        "items": items,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {len(items)} near-namesake sets to {path}")
    return 0


def load_namesakes(path: Path = NAMESAKES) -> dict[tuple[str, str], list[str]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return {(i["document"], i["key"]): list(i["namesakes"]) for i in data["items"]}


def noisy_words(words: Sequence[OcrWord], probability: float, seed: str) -> list[OcrWord]:
    """``words`` with simulated OCR noise (see the module doc). ``0.0``: unchanged."""
    if probability <= 0:
        return list(words)
    rng = random.Random(seed)  # noqa: S311 - simulation, not security
    out: list[OcrWord] = []
    for word in words:
        text = _strip(word.text) if rng.random() < 0.5 else word.text
        text = "".join(
            _CONFUSIONS[c] if c in _CONFUSIONS and rng.random() < probability else c for c in text
        )
        out.append(OcrWord(text, word.box, word.line))
    return out


# --- matchers ---------------------------------------------------------------------------------


class ExactMatcher(VaultMatcher):
    """The baseline: reuse a placeholder only for a value equal up to case and whitespace."""

    def match(self, value: str, entity_type: EntityType) -> Match:
        normalized = normalize_value(value)
        for candidate in self._candidates:
            if (
                candidate.entity_type is entity_type
                and normalize_value(candidate.value) == normalized
            ):
                return Match(candidate, 1.0, "exact")
        return Match(None, 0.0, "none")

    def match_one(self, value: str, candidate: Candidate) -> Match:
        if normalize_value(value) == normalize_value(candidate.value):
            return Match(candidate, 1.0, "exact")
        return Match(None, 0.0, "none")


# --- the eval ----------------------------------------------------------------------------------


class _NoSam:
    """SAM is not part of placeholder matching: no visual regions."""

    model = "none"
    prompts: ClassVar[dict[EntityType, tuple[str, ...]]] = {EntityType.FACE: ("face",)}

    def segment(self, image: bytes, entity_types: object = None) -> list[Region]:
        return []


def _seed(session: VaultSession, values: Sequence[tuple[str, EntityType]]) -> list[str]:
    """Mask a contract-like text naming ``values``; return each value's placeholder."""
    placeholders: list[str] = []
    for value, entity_type in values:
        text = f"A szerződő fél adata: {value}."
        start = text.index(value)
        span = Span(start, start + len(value), entity_type, value, 1.0, "eval")
        result = session.mask_with_report(text, [span], language="hu")
        placeholders.append(next(p for s, _e, p in result.replacements if s == start))
    return placeholders
