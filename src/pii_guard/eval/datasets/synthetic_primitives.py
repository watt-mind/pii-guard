"""Span-preserving text/JSON builders and checksum primitives for synthetic datasets."""

from __future__ import annotations

import json
import random
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from pii_guard.languages.de.checksums import is_valid_steuer_id, steuer_id_check_digit
from pii_guard.types import EntityType

# --- Building text with spans ---------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Gold:
    """A labelled value to insert. ``valid`` is ``None`` for types without a checksum."""

    entity_type: EntityType
    text: str
    valid: bool | None = None
    perturbed: str | None = None


@dataclass(frozen=True, slots=True)
class Secret:
    """A secret (API key): an ignore region, neither credited nor charged."""

    text: str


Piece = str | Gold | Secret


@dataclass(slots=True)
class Built:
    text: str = ""
    spans: list[tuple[int, int, Gold]] = field(default_factory=list)
    ignore: list[tuple[int, int, str]] = field(default_factory=list)

    def add(self, piece: Piece) -> None:
        start = len(self.text)
        if isinstance(piece, Gold):
            self.text += piece.text
            self.spans.append((start, len(self.text), piece))
        elif isinstance(piece, Secret):
            self.text += piece.text
            self.ignore.append((start, len(self.text), "SECRET"))
        else:
            self.text += piece

    def extend(self, pieces: Sequence[Piece]) -> Built:
        for p in pieces:
            self.add(p)
        return self


def _shift(b: Built, other: Built) -> None:
    """Append ``other`` to ``b``, moving its spans."""
    offset = len(b.text)
    b.text += other.text
    b.spans.extend((s + offset, e + offset, g) for s, e, g in other.spans)
    b.ignore.extend((s + offset, e + offset, lab) for s, e, lab in other.ignore)


def json_string(pieces: Sequence[Piece] | Piece) -> Built:
    """A JSON string literal of the concatenated pieces, spans inside the quotes.

    Values never contain characters JSON escapes, so a value's text is unchanged; the text
    around it is escaped with :func:`json.dumps` (non-ASCII kept).
    """
    items: Sequence[Piece] = [pieces] if isinstance(pieces, str | Gold | Secret) else pieces
    out = Built('"')
    for p in items:
        if isinstance(p, Gold | Secret):
            assert json.dumps(p.text, ensure_ascii=False)[1:-1] == p.text  # noqa: S101
            out.add(p)
        else:
            out.add(json.dumps(p, ensure_ascii=False)[1:-1])
    out.add('"')
    return out


def escape_built(inner: Built) -> Built:
    """``inner`` as a JSON string literal (a tool call's ``arguments``), spans remapped."""
    out = Built('"')
    cursor = 0
    marks = sorted([(s, e, g) for s, e, g in inner.spans], key=lambda t: t[0])
    for s, e, g in marks:
        out.add(json.dumps(inner.text[cursor:s], ensure_ascii=False)[1:-1])
        out.add(g)
        cursor = e
    out.add(json.dumps(inner.text[cursor:], ensure_ascii=False)[1:-1])
    out.add('"')
    return out


def to_json(value: Any, indent: int | None = 2, level: int = 0) -> Built:
    """Serialise a structure whose leaves may be :class:`Gold`, :class:`Secret`, lists of pieces
    or :class:`Built` (already a JSON literal)."""
    b = Built()
    pad = "" if indent is None else "\n" + " " * (indent * (level + 1))
    end = "" if indent is None else "\n" + " " * (indent * level)
    sep = ", " if indent is None else ","
    if isinstance(value, Built):
        _shift(b, value)
    elif isinstance(value, dict):
        b.add("{")
        for i, (k, v) in enumerate(value.items()):
            b.add((sep if i else "") + pad + json.dumps(k, ensure_ascii=False) + ": ")
            _shift(b, to_json(v, indent, level + 1))
        b.add(end + "}")
    elif isinstance(value, list) and value and all(isinstance(x, dict) for x in value):
        b.add("[")
        for i, v in enumerate(value):
            b.add((sep if i else "") + pad)
            _shift(b, to_json(v, indent, level + 1))
        b.add(end + "]")
    elif isinstance(value, Gold | Secret) or (isinstance(value, list) and value):
        _shift(b, json_string(value))
    elif isinstance(value, str):
        b.add(json.dumps(value, ensure_ascii=False))
    else:
        b.add(json.dumps(value))
    return b


# --- Values ---------------------------------------------------------------------------------


def _luhn_digit(payload: str) -> int:
    total = 0
    for i, ch in enumerate(reversed(payload)):
        d = int(ch)
        if i % 2 == 0:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return (10 - total % 10) % 10


def card_number(rng: random.Random) -> str:
    """A Luhn-valid 16-digit Visa- or Mastercard-style number, grouped in fours."""
    head = rng.choice(["4", "51", "52", "53", "54", "55"])
    payload = head + "".join(str(rng.randrange(10)) for _ in range(15 - len(head)))
    digits = payload + str(_luhn_digit(payload))
    return " ".join(digits[i : i + 4] for i in range(0, 16, 4))


def steuer_id(rng: random.Random) -> str:
    """A Steuer-ID with a valid structure and check digit."""
    while True:
        head = str(rng.randint(1, 9)) + "".join(str(rng.randrange(10)) for _ in range(9))
        value = head + str(steuer_id_check_digit(head))
        if is_valid_steuer_id(value):
            return value


def break_checksum(rng: random.Random, value: str) -> str:
    """``value`` with its last digit changed (the check digit no longer matches)."""
    idx = max(i for i, ch in enumerate(value) if ch.isdigit())
    old = int(value[idx])
    new = (old + rng.randint(1, 9)) % 10
    return value[:idx] + str(new) + value[idx + 1 :]
