"""A generated, unseen hu/en/de dev split in the style of the smoke sets (LAB-1417).

Why: ``train.py`` keeps the epoch with the best F1 on its ``dev`` files (OpenPII and distill
dev), and that split does not track the smoke gate. v3.1 candidate A's chosen epoch had dev F1
0.976 / 0.938 and leaked 8 PERSON values (5.8 %) on hu/en/de smoke, against 0 for v2.0
(``eval/results/2026-10-28-ner-v31/``); v4-A repeated it. The smoke sets are short chats,
e-mails and letters with a few names, contact details and an account number; the training dev
has almost none of those.

This module writes such texts from templates and seeded fictional identities, never the smoke
fixtures themselves:

- names come from :mod:`pii_guard.eval.identities` (hu, en) and from invented German name
  lists below, plus placeholder-style surnames like the smoke sets use (``Mockford``,
  ``Kitalált``, ``Fiktivberg``), none of them a smoke-set name: a name that equals a person
  value of any ``eval/fixtures/*-smoke.jsonl`` or ``hu-inflection.jsonl`` is redrawn;
- :func:`write` loads every document through the decontamination gate (``decontam.py``) and
  drops any that is an exact or near copy of an evaluation text, which includes the smoke
  fixtures and the ``agent-traffic-dev`` selection set;
- ``train.py`` reads the files as ``report_dev``: scored and reported every epoch (span F1 and
  the share of gold values no prediction covers, per type) but never used to pick the epoch,
  and indexed so no training document may copy one.

Fictional data only (ADR 0005): e-mail domains are the reserved ``example.*``, English phone
numbers come from the Ofcom drama ranges, German numbers are random digits after a city area
code, and IBANs carry valid check digits with random bank codes.

::

    uv run --no-sync python training/ner/smoke_style_dev.py            # write the split
    uv run --extra ner python training/ner/train.py --config <cfg> \\
        --report-dev eval/generated/smoke-style-dev/hu-smoke-style-dev.jsonl ...
"""

# Seeded synthetic data: the standard PRNG is the point.
# ruff: noqa: S311

from __future__ import annotations

import argparse
import json
import random
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from pii_guard.eval.fixtures import Document, from_markup, label, load_fixtures, write_fixtures
from pii_guard.eval.identities import email_address, iban, identity_generator

sys.path.insert(0, str(Path(__file__).resolve().parent))
import decontam

ROOT = Path(__file__).resolve().parents[2]
OUT = Path("eval/generated/smoke-style-dev")
LANGS = ("hu", "en", "de")
KINDS = ("chat", "email", "letter")
VERSION = 1
PER_KIND = 25
SEED = 1417

# Placeholder-style surnames, as the smoke sets use (``Teszt``, ``Example``, ``Muster``), but
# none of the smoke ones.
_PLACEHOLDER = {
    "hu": ("Kitalált", "Mintavári", "Próbás", "Képzeletes", "Tesztelő", "Álnév"),
    "en": ("Mockford", "Samplewell", "Fictonby", "Dummington", "Placewood", "Exemplar-Hart"),
    "de": ("Fiktivberg", "Probemann", "Musterhagen", "Erdachtl", "Testfeld", "Platzmann"),
}
_DE_GIVEN = (
    "Lukas", "Mia", "Felix", "Hannah", "Jan", "Sophie", "Moritz", "Clara", "Niklas", "Laura",
    "Tobias", "Julia", "Florian", "Katharina", "Sebastian", "Miriam", "Jakob", "Ines",
)  # fmt: skip
_DE_FAMILY = (
    "Wagner", "Becker", "Hoffmann", "Schäfer", "Koch", "Richter", "Klein", "Wolf", "Neumann",
    "Schwarz", "Zimmermann", "Braun", "Krüger", "Hartmann", "Lange", "Werner", "Krause",
)  # fmt: skip
_DE_STREETS = ("Lindenweg", "Gartenstraße", "Am Mühlbach", "Bergstraße", "Kirchplatz", "Uferweg")
_DE_TOWNS = (
    ("10437", "Berlin", "30"), ("20255", "Hamburg", "40"), ("80469", "München", "89"),
    ("50667", "Köln", "221"), ("04109", "Leipzig", "341"), ("28195", "Bremen", "421"),
)  # fmt: skip


def _smoke_names(root: Path = ROOT) -> frozenset[str]:
    paths = sorted((root / "eval/fixtures").glob("*-smoke.jsonl"))
    paths.append(root / "eval/fixtures/hu-inflection.jsonl")
    names: set[str] = set()
    for doc in load_fixtures([p for p in paths if p.is_file()]):
        for span in doc.spans:
            if span.entity_type.value == "PERSON":
                names.add(span.text)
                names.update(span.text.split())
    return frozenset(names)


class _People:
    """Fictional people for one document: (given, full name), email, phone, iban, address."""

    def __init__(self, lang: str, rng: random.Random, avoid: frozenset[str]) -> None:
        self.lang, self.rng, self.avoid = lang, rng, avoid
        self.ids = identity_generator(lang, rng) if lang in ("hu", "en") else None
        self.used: set[str] = set()

    def _draw(self) -> dict[str, str]:
        rng = self.rng
        if self.ids is not None:
            p = self.ids.person()
            given, family, full = p.given, p.family, p.name
            out = {"email": p.email, "phone": p.phone, "iban": p.bank_account}
            out["address"] = p.address
        else:
            given, family = rng.choice(_DE_GIVEN), rng.choice(_DE_FAMILY)
            full = f"{given} {family}"
            postcode, town, area = rng.choice(_DE_TOWNS)
            out = {
                "email": email_address(rng, given, family),
                "phone": f"+49 {area} {rng.randint(200, 989)} {rng.randint(1000, 9899)}",
                "iban": iban("DE", f"{rng.randint(10**17, 10**18 - 1)}"),
                "address": f"{rng.choice(_DE_STREETS)} {rng.randint(1, 98)}, {postcode} {town}",
            }
        if rng.random() < 0.35:  # placeholder-style surname, like the smoke sets
            family = rng.choice(_PLACEHOLDER[self.lang])
            full = f"{family} {given}" if self.lang == "hu" else f"{given} {family}"
            out["email"] = email_address(rng, given, family)
        out.update(given=given, family=family, full=full)
        return out

    def person(self) -> dict[str, str]:
        for _ in range(100):
            p = self._draw()
            names = {p["full"], p["given"], p["family"]}
            if not names & (self.avoid | self.used):
                self.used.update(names)
                return p
        raise RuntimeError("could not draw a fresh fictional name")  # pragma: no cover


def _hu_dat(name: str) -> str:
    """``name`` + ``-nak/-nek``, labelled as in the smoke sets.

    A suffix that leaves the name intact stays outside the label (``{{PERSON|Kiss Imre}}nek``);
    a final ``a``/``e`` lengthens (``Etelka`` -> ``Etelkának``), and that stem-changing form is
    labelled as a whole word, as ``hu-inflection.jsonl`` does.
    """
    vowels = [c for c in name.lower() if c in "aáeéiíoóöőuúüű"]
    suffix = "nak" if vowels and vowels[-1] in "aáoóuú" else "nek"
    if name.endswith(("a", "e")):
        return _l("PERSON", name[:-1] + {"a": "á", "e": "é"}[name[-1]] + suffix)
    return _l("PERSON", name) + suffix


def _l(entity: str, value: str) -> str:
    return label(entity, value)


Template = Callable[[dict[str, str], dict[str, str], random.Random], str]


def _hu(kind: str) -> list[Template]:
    if kind == "chat":
        return [
            lambda a, b, r: (
                f"Szia {_l('PERSON', a['given'])}! Holnap 9-kor jó? Ha nem, hívj a "
                f"{_l('PHONE', b['phone'])} számon. {_l('PERSON', b['given'])}"
            ),
            lambda a, b, r: (
                f"[{r.randint(7, 21)}:{r.randint(10, 29)}] "
                f"{_l('PERSON', a['full'])}: átküldted már {_hu_dat(b['full'])} a számlaszámot?"
                f"\n[{r.randint(22, 23)}:{r.randint(30, 59)}] "
                f"{_l('PERSON', b['full'])}: igen, {_l('BANK_ACCOUNT', b['iban'])}"
            ),
            lambda a, b, r: (
                f"{_l('PERSON', a['given'])}, írd meg {_hu_dat(b['full'])} az "
                f"e-mail címét: {_l('EMAIL', b['email'])} köszi!"
            ),
        ]
    if kind == "email":
        return [
            lambda a, b, r: (
                f"Tárgy: Időpont\n\nKedves {_l('PERSON', a['full'])}!\n\nA "
                f"szerződést a {_l('ADDRESS', a['address'])} címre küldjük. Kérdés esetén: "
                f"{_l('EMAIL', b['email'])}.\n\nÜdvözlettel:\n{_l('PERSON', b['full'])}"
            ),
            lambda a, b, r: (
                f"Tárgy: Befizetés\n\nTisztelt {_l('PERSON', a['full'])}!\n\nAz "
                f"összeget a {_l('BANK_ACCOUNT', b['iban'])} számlára kérjük utalni. Telefon: "
                f"{_l('PHONE', b['phone'])}\n\nÜdv,\n{_l('PERSON', b['given'])}"
            ),
        ]
    return [
        lambda a, b, r: (
            f"{_l('PERSON', a['full'])}\n{_l('ADDRESS', a['address'])}\n\nTárgy: "
            f"értesítés\n\nTisztelt {_l('PERSON', a['full'])}!\n\nTájékoztatjuk, hogy kérelmét "
            f"befogadtuk. Ügyintéző: {_l('PERSON', b['full'])}, {_l('PHONE', b['phone'])}.\n\n"
            "Tisztelettel:"
        ),
        lambda a, b, r: (
            f"Kedves {_l('PERSON', a['given'])}!\n\nKöszönöm a levelet. "
            f"{_l('PERSON', b['full'])} új címe: {_l('ADDRESS', b['address'])}.\n\n"
            f"Baráti üdvözlettel:\n{_l('PERSON', a['full'])}"
        ),
    ]


def _en(kind: str) -> list[Template]:
    if kind == "chat":
        return [
            lambda a, b, r: (
                f"hey {_l('PERSON', a['given'])}, can you ring "
                f"{_l('PERSON', b['full'])} on {_l('PHONE', b['phone'])} before 5?"
            ),
            lambda a, b, r: (
                f"{_l('PERSON', a['full'])}: did {_l('PERSON', b['given'])} send "
                f"the bank details?\n{_l('PERSON', b['full'])}: yes - "
                f"{_l('BANK_ACCOUNT', b['iban'])}"
            ),
            lambda a, b, r: (
                f"{_l('PERSON', a['given'])} pls forward it to "
                f"{_l('EMAIL', b['email'])}, thx - {_l('PERSON', b['given'])}"
            ),
        ]
    if kind == "email":
        return [
            lambda a, b, r: (
                f"Subject: Viewing on Thursday\n\nHi {_l('PERSON', a['full'])},\n\n"
                f"The keys are at {_l('ADDRESS', a['address'])}. Any questions, call me on "
                f"{_l('PHONE', b['phone'])}.\n\nBest,\n{_l('PERSON', b['full'])}"
            ),
            lambda a, b, r: (
                f"Subject: Deposit\n\nDear {_l('PERSON', a['full'])},\n\nPlease pay "
                f"the deposit to {_l('BANK_ACCOUNT', b['iban'])} and reply to "
                f"{_l('EMAIL', b['email'])}.\n\nKind regards\n{_l('PERSON', b['given'])}"
            ),
        ]
    return [
        lambda a, b, r: (
            f"{_l('PERSON', a['full'])}\n{_l('ADDRESS', a['address'])}\n\n"
            f"Dear {_l('PERSON', a['full'])},\n\nThank you for your application. Your case officer "
            f"is {_l('PERSON', b['full'])} ({_l('EMAIL', b['email'])}).\n\nYours sincerely,"
        ),
        lambda a, b, r: (
            f"Dear {_l('PERSON', a['given'])},\n\nI'm writing on behalf of "
            f"{_l('PERSON', b['full'])}, who has moved to {_l('ADDRESS', b['address'])}.\n\n"
            f"Yours,\n{_l('PERSON', a['full'])}"
        ),
    ]


def _de(kind: str) -> list[Template]:
    if kind == "chat":
        return [
            lambda a, b, r: (
                f"Hi {_l('PERSON', a['given'])}, kannst du "
                f"{_l('PERSON', b['full'])} unter {_l('PHONE', b['phone'])} anrufen?"
            ),
            lambda a, b, r: (
                f"{_l('PERSON', a['full'])}: Hat {_l('PERSON', b['given'])} die "
                f"Kontodaten geschickt?\n{_l('PERSON', b['full'])}: ja, "
                f"{_l('BANK_ACCOUNT', b['iban'])}"
            ),
            lambda a, b, r: (
                f"{_l('PERSON', a['given'])}, schick es bitte an "
                f"{_l('EMAIL', b['email'])}. Danke! {_l('PERSON', b['given'])}"
            ),
        ]
    if kind == "email":
        return [
            lambda a, b, r: (
                f"Betreff: Termin\n\nHallo {_l('PERSON', a['full'])},\n\ndie "
                f"Unterlagen gehen an {_l('ADDRESS', a['address'])}. Rückfragen gern unter "
                f"{_l('PHONE', b['phone'])}.\n\nViele Grüße\n{_l('PERSON', b['full'])}"
            ),
            lambda a, b, r: (
                f"Betreff: Miete\n\nSehr geehrte/r {_l('PERSON', a['full'])},\n\n"
                f"bitte überweisen Sie auf {_l('BANK_ACCOUNT', b['iban'])}. Antwort bitte an "
                f"{_l('EMAIL', b['email'])}.\n\nBeste Grüße\n{_l('PERSON', b['given'])}"
            ),
        ]
    return [
        lambda a, b, r: (
            f"{_l('PERSON', a['full'])}\n{_l('ADDRESS', a['address'])}\n\n"
            f"Sehr geehrte/r {_l('PERSON', a['full'])},\n\nIhr Antrag ist eingegangen. Ihre "
            f"Ansprechpartnerin ist {_l('PERSON', b['full'])}, Tel. {_l('PHONE', b['phone'])}.\n\n"
            "Mit freundlichen Grüßen"
        ),
        lambda a, b, r: (
            f"Liebe/r {_l('PERSON', a['given'])},\n\n{_l('PERSON', b['full'])} "
            f"wohnt jetzt in {_l('ADDRESS', b['address'])}.\n\nHerzliche Grüße\n"
            f"{_l('PERSON', a['full'])}"
        ),
    ]


_TEMPLATES = {"hu": _hu, "en": _en, "de": _de}


def build(
    *, per_kind: int = PER_KIND, seed: int = SEED, avoid: frozenset[str] | None = None
) -> list[Document]:
    """``per_kind`` documents per language and kind, deterministic for ``seed``."""
    avoid = _smoke_names() if avoid is None else avoid
    docs: list[Document] = []
    for lang in LANGS:
        for kind in KINDS:
            templates = _TEMPLATES[lang](kind)
            for i in range(per_kind):
                rng = random.Random(f"smoke-style-dev/{VERSION}/{seed}/{lang}/{kind}/{i}")
                people = _People(lang, rng, avoid)
                a, b = people.person(), people.person()
                marked = templates[i % len(templates)](a, b, rng)
                docs.append(
                    from_markup(
                        f"{lang}-smokedev-{kind}-{i:04d}",
                        marked,
                        language=lang,
                        meta={"kind": kind, "generator": f"smoke_style_dev/{VERSION}"},
                    )
                )
    return docs


def write(
    out: Path = OUT,
    *,
    per_kind: int = PER_KIND,
    seed: int = SEED,
    index: decontam.EvalIndex | None = None,
) -> list[Path]:
    """Write ``<out>/<lang>-smoke-style-dev.jsonl`` after the decontamination gate."""
    index = decontam.eval_corpus(ROOT) if index is None else index
    report = decontam.Report()
    docs = build(per_kind=per_kind, seed=seed)
    out.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for lang in LANGS:
        path = out / f"{lang}-smoke-style-dev.jsonl"
        kept = decontam.gate(
            [d for d in docs if d.language == lang], index, name=str(path), report=report
        )
        write_fixtures(path, kept)
        paths.append(path)
    summary: dict[str, Any] = {
        "version": VERSION,
        "seed": seed,
        "per_kind": per_kind,
        "decontam": report.to_dict(),
    }
    (out / "manifest.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(decontam.summary_line(report), flush=True)
    return paths


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", type=Path, default=OUT)
    parser.add_argument("--per-kind", type=int, default=PER_KIND)
    parser.add_argument("--seed", type=int, default=SEED)
    args = parser.parse_args(argv)
    for path in write(args.out, per_kind=args.per_kind, seed=args.seed):
        print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
