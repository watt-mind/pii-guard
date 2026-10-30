"""Template generators for NER v4.2 (LAB-1625): the failure modes v4.1 showed on the smoke gate.

v4.1 (LAB-1547) failed the hu/en/de smoke gate in two ways the LAB-1417 smoke-style split did
not see (it scored 0 % leak for v2.0, A1 and A2 alike):

- **German genitive names** leak (``Annas Termin``, ``Frau Beckers Antrag``, ``Jonas' Handy``).
- **Birth-date over-masking:** non-birth dates (appointments, invoice dates, start dates, even
  old ones such as ``seit 1998``) are masked as ``DATE_OF_BIRTH``; ``BANK_ACCOUNT`` false alarms
  on order and customer numbers rose as well.

And one v2.0 miss the next model should fix (LAB-1606, LAB-1646): a **Hungarian common-word
surname with an inflected given name** (``Fekete Eleknek``, ``Kovács Jakabot``), including given
names outside the name lexicon.

Each generator here writes one short smoke-style document (chat, e-mail or note) for one of
those *slices*. Two disjoint **pools** keep the selection split honest:

- ``sel`` (``selection_v42.py``): the dev-side selection split;
- ``train`` (``v42_data.py``): the targeted training documents.

The pools use different sentence frames and different halves of every name list, so a model
cannot score on the selection split by remembering a training template or a training name.

Fictional data only (ADR 0005): names are invented combinations of common given names and
surnames, contact details come from ``smoke_style_dev._People`` (reserved ``example.*`` domains,
drama phone ranges, IBANs with random bank codes). No GDPR special-category content. Labels
follow ``docs/entities.md``: a German genitive ending and a Hungarian case suffix that leaves the
name intact stay outside the ``PERSON`` span (``{{PERSON|Anna}}s``, ``{{PERSON|Fekete Elek}}nek``);
a stem-changing form is labelled as a whole word (``{{PERSON|Fekete Gézának}}``). Only birth
dates are ``DATE_OF_BIRTH``; every other date is ``O``.
"""

from __future__ import annotations

import datetime as dt
import random
import sys
from collections.abc import Callable
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import smoke_style_dev as ssd
import targeted_v33 as t33
from targeted_v33 import Builder

from pii_guard.types import EntityType as E

POOLS = ("train", "sel")
SLICES = ("de-genitive", "hu-surname-given", "dates", "numbers")
SLICE_LANGS: dict[str, tuple[str, ...]] = {
    "de-genitive": ("de",),
    "hu-surname-given": ("hu",),
    "dates": ("hu", "en", "de"),
    "numbers": ("hu", "en", "de"),
}


def _half(items: tuple[str, ...], pool: str) -> tuple[str, ...]:
    """Every other item of the sorted, de-duplicated list: ``train`` even, ``sel`` odd."""
    ordered = sorted(set(items))
    return tuple(ordered[(0 if pool == "train" else 1) :: 2])


# --- names -------------------------------------------------------------------------------------

DE_GIVEN = (
    "Anna", "Lena", "Laura", "Julia", "Sophie", "Marie", "Katharina", "Sabine", "Ursula", "Clara",
    "Hannah", "Miriam", "Ines", "Petra", "Franziska", "Johanna", "Greta", "Frieda", "Carla", "Ida",
    "Lukas", "Felix", "Paul", "Leon", "Jan", "Moritz", "Tobias", "Florian", "Sebastian", "Jakob",
    "Niklas", "Elias", "Jonas", "Lars", "Max", "Fritz", "Hans", "Markus", "Andreas", "Thomas",
    "Matthias", "Klaus", "Franz", "Linus", "Benedikt", "Konrad", "Ulrich", "Rainer",
    "Ida", "Eva", "Lea", "Mia", "Pia", "Ella", "Nina", "Tim", "Ben", "Ole", "Uwe", "Kai", "Tom",
    "Leo", "Jens", "Timo",
)  # fmt: skip
DE_FAMILY = (
    "Wagner", "Becker", "Hoffmann", "Schäfer", "Koch", "Richter", "Klein", "Wolf", "Neumann",
    "Schwarz", "Zimmermann", "Braun", "Krüger", "Hartmann", "Lange", "Werner", "Krause", "Bauer",
    "Schuster", "Vogt", "Winkler", "Böhm", "Busch", "Ziegler", "Engel", "Pohl", "Horn", "Sommer",
    "Seifert", "Kühn", "Ludwig", "Dietrich", "Jäger", "Arnold", "Schulte", "Lorenz", "Fuchs",
    "Kraus", "Seitz", "Voss", "Marx", "Haas", "Peters", "Brandt", "Graf", "Roth", "Kaiser",
    "Lehmann",
)  # fmt: skip
#: Hungarian surnames that are also common words (LAB-1606: black, smith, tailor, miller ...).
HU_WORD_SURNAMES = (
    "Fekete", "Kovács", "Szabó", "Molnár", "Takács", "Nagy", "Kis", "Fehér", "Varga", "Szűcs",
    "Fazekas", "Pásztor", "Halász", "Virág", "Király", "Katona", "Magyar", "Lengyel", "Orosz",
    "Török", "Kocsis", "Juhász", "Bíró", "Vadász", "Barát", "Bognár", "Vörös", "Szőke", "Ács",
    "Kertész", "Erdős", "Sas", "Farkas", "Bárány", "Hegedűs", "Deák", "Sipos", "Mészáros",
)  # fmt: skip
#: Given names, many outside the name lexicon (Elek, Jakab, Kelemen ...), chosen so the simple
#: vowel-harmony rule of ``targeted_v33.hu_harmony`` gives the right suffix.
HU_GIVEN = (
    "Elek", "Jakab", "Kelemen", "Kende", "Csanád", "Vazul", "Bendegúz", "Örs", "Zente", "Ernő",
    "Jenő", "Géza", "Aladár", "Benő", "Döme", "Bertalan", "Ibolya", "Jolán", "Emőke", "Csenge",
    "Hédi", "Kincső", "Anikó", "Etelka", "Panna", "Dorka", "Bíborka", "Ildikó", "Béla", "Imre",
    "Endre", "Tibor", "Ottó", "Kálmán", "Márton", "Gergely", "Eszter", "Katalin", "Nóra",
    "Lilla", "Tünde", "Edit", "Judit", "Réka", "Zita", "Rita", "Klára", "Piroska",
)  # fmt: skip
HU_CASES = ("dat", "acc", "del", "ins", "abl", "all", "ade", "nom", "poss")


class Names:
    """Draw fictional names from one pool, never one in ``avoid``, never twice per document."""

    def __init__(self, pool: str, rng: random.Random, avoid: frozenset[str]) -> None:
        self.rng, self.avoid, self.used = rng, avoid, set[str]()
        self.de_given, self.de_family = _half(DE_GIVEN, pool), _half(DE_FAMILY, pool)
        self.hu_given, self.hu_family = _half(HU_GIVEN, pool), _half(HU_WORD_SURNAMES, pool)

    def _fresh(self, draw: Callable[[], tuple[str, str]]) -> tuple[str, str]:
        for _ in range(200):
            given, family = draw()
            parts = {given, family, f"{given} {family}", f"{family} {given}"}
            if not parts & self.avoid and given not in self.used and family not in self.used:
                self.used.update((given, family))
                return given, family
        raise RuntimeError("could not draw a fresh fictional name")  # pragma: no cover

    def de(self) -> tuple[str, str]:
        return self._fresh(
            lambda: (self.rng.choice(self.de_given), self.rng.choice(self.de_family))
        )

    def hu(self) -> tuple[str, str]:
        return self._fresh(
            lambda: (self.rng.choice(self.hu_given), self.rng.choice(self.hu_family))
        )


def contact(lang: str, rng: random.Random) -> dict[str, str]:
    """E-mail, phone, IBAN and address of a fictional person (``smoke_style_dev._People``)."""
    return ssd._People(lang, rng, frozenset()).person()


def email(rng: random.Random, given: str, family: str) -> str:
    return ssd.email_address(rng, given, family)


# --- labelled pieces ---------------------------------------------------------------------------


def de_gen_suffix(name: str, rng: random.Random) -> str:
    """The genitive ending: ``'`` after s/ß/x/z, else ``s``; colloquial ``'s`` now and then."""
    if name.endswith(("s", "ß", "x", "z")):
        return "'"
    return "'s" if rng.random() < 0.12 else "s"


def add_de_genitive(b: Builder, name: str, lemma: str, rng: random.Random) -> Builder:
    """``name`` in the genitive: the name is the ``PERSON`` span, the ending stays outside."""
    return b.gold(name, E.PERSON, lemma).add(de_gen_suffix(name, rng))


def add_hu_case(b: Builder, full: str, case: str, *, capital: bool = False) -> Builder:
    """``full`` with its last word in ``case``; an intact stem keeps the suffix outside."""
    surface = t33.hu_inflect(full, case)
    if capital:
        surface, full_c = surface[0].upper() + surface[1:], full[0].upper() + full[1:]
    else:
        full_c = full
    if surface.startswith(full_c) and surface != full_c:
        return b.gold(full_c, E.PERSON, full).add(surface[len(full_c) :])
    return b.gold(surface, E.PERSON, full)


# --- dates -------------------------------------------------------------------------------------

HU_MONTHS = (
    "január", "február", "március", "április", "május", "június", "július", "augusztus",
    "szeptember", "október", "november", "december",
)  # fmt: skip
EN_MONTHS = (
    "January", "February", "March", "April", "May", "June", "July", "August", "September",
    "October", "November", "December",
)  # fmt: skip
DE_MONTHS = (
    "Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September",
    "Oktober", "November", "Dezember",
)  # fmt: skip


def fmt_date(lang: str, day: dt.date, rng: random.Random, *, year: bool = True) -> str:
    d, m, y = day.day, day.month, day.year
    if lang == "hu":
        if not year:
            return f"{HU_MONTHS[m - 1]} {d}."
        return rng.choice((f"{y}. {HU_MONTHS[m - 1]} {d}.", f"{y}.{m:02d}.{d:02d}.",
                           f"{y}. {m:02d}. {d:02d}.", f"{y}-{m:02d}-{d:02d}"))  # fmt: skip
    if lang == "en":
        if not year:
            return rng.choice((f"{d} {EN_MONTHS[m - 1]}", f"{EN_MONTHS[m - 1]} {d}"))
        return rng.choice((f"{d} {EN_MONTHS[m - 1]} {y}", f"{d:02d}/{m:02d}/{y}",
                           f"{EN_MONTHS[m - 1]} {d}, {y}", f"{y}-{m:02d}-{d:02d}"))  # fmt: skip
    if not year:
        return f"{d}. {DE_MONTHS[m - 1]}"
    return rng.choice((f"{d}. {DE_MONTHS[m - 1]} {y}", f"{d:02d}.{m:02d}.{y}",
                       f"{y}-{m:02d}-{d:02d}"))  # fmt: skip


def birth_day(rng: random.Random) -> dt.date:
    start = dt.date(1946, 1, 1).toordinal()
    return dt.date.fromordinal(rng.randint(start, dt.date(2005, 12, 31).toordinal()))


def other_day(rng: random.Random, *, old: bool = False) -> dt.date:
    """A non-birth date: recent or coming, or (``old``) years back, like a start date."""
    lo, hi = (dt.date(1985, 1, 1), dt.date(2015, 12, 31)) if old else (
        dt.date(2023, 1, 1), dt.date(2027, 12, 31))  # fmt: skip
    return dt.date.fromordinal(rng.randint(lo.toordinal(), hi.toordinal()))


#: Birth-date cues and non-birth date frames, per pool and language. ``{p}`` is the person
#: (nominative), ``{dob}`` the birth date, ``{d}`` a non-birth date (``{do}``: an old one).
DOB_FRAMES: dict[str, dict[str, tuple[str, ...]]] = {
    "sel": {
        "hu": ("{p} (szül.: {dob})", "Név: {p}\nSzületési dátum: {dob}", "{p}, született {dob}"),
        "en": ("{p} (DOB {dob})", "Name: {p}\nDate of birth: {dob}", "{p}, born {dob}"),
        "de": ("{p} (geb. {dob})", "Name: {p}\nGeburtsdatum: {dob}", "{p}, geboren am {dob}"),
    },
    "train": {
        "hu": ("{p}, szül. {dob}", "Ügyfél: {p} | születési idő: {dob}",
               "{p} (született: {dob})", "Születési idő: {dob}\nNév: {p}"),
        "en": ("{p}, d.o.b. {dob}", "Customer: {p} | date of birth: {dob}",
               "{p} (born on {dob})", "Birth date: {dob}\nName: {p}"),
        "de": ("{p}, geb. am {dob}", "Kunde: {p} | Geburtsdatum: {dob}",
               "{p} (geboren {dob})", "Geburtstag: {dob}\nName: {p}"),
    },
}  # fmt: skip
OTHER_DATE_FRAMES: dict[str, dict[str, tuple[str, ...]]] = {
    "sel": {
        "hu": ("A következő egyeztetés: {d}.", "Számla kelte: {d}", "Fizetési határidő: {d}",
               "Munkaviszony kezdete: {do}", "A bérleti szerződés {do} óta él.",
               "A csomag {d} érkezik."),
        "en": ("Next check-in: {d}.", "Invoice date: {d}", "Payment due {d}.",
               "Employed since {do}.", "The lease started on {do}.",
               "Your parcel arrives on {d}."),
        "de": ("Nächster Termin: {d}.", "Rechnungsdatum: {d}", "Zahlbar bis {d}.",
               "Beschäftigt seit {do}.", "Der Mietvertrag läuft seit {do}.",
               "Die Lieferung kommt am {d}."),
    },
    "train": {
        "hu": ("Az ülés időpontja {d}.", "Teljesítés dátuma: {d}", "Utalási határidő: {d}",
               "Az ügyfélkapcsolat {do} óta tart.", "Belépés dátuma: {do}",
               "A szerződést {do} írták alá.", "Rendelés leadva: {d}", "Utolsó belépés: {d}"),
        "en": ("The meeting is on {d}.", "Service date: {d}", "Please pay by {d}.",
               "Customer since {do}.", "Joined the team on {do}.",
               "The contract was signed on {do}.", "Order placed: {d}", "Last login: {d}"),
        "de": ("Die Sitzung findet am {d} statt.", "Leistungsdatum: {d}",
               "Bitte bis {d} überweisen.", "Kunde seit {do}.", "Eintritt am {do}.",
               "Der Vertrag wurde am {do} unterschrieben.", "Bestellt am: {d}",
               "Letzte Anmeldung: {d}"),
    },
}  # fmt: skip
OPENERS: dict[str, dict[str, tuple[str, ...]]] = {
    "sel": {
        "hu": ("Szia!\n", "Tárgy: adategyeztetés\n\n", "", "Jegyzet:\n"),
        "en": ("Hi,\n", "Subject: account details\n\n", "", "Note:\n"),
        "de": ("Hallo,\n", "Betreff: Kundendaten\n\n", "", "Notiz:\n"),
    },
    "train": {
        "hu": ("Kedves Kolléga!\n\n", "Ügyfélszolgálati jegy\n", "", "Kérés az asszisztensnek: ",
               "Összefoglaló a hívásról:\n"),
        "en": ("Dear team,\n\n", "Support ticket\n", "", "Request for the assistant: ",
               "Call summary:\n"),
        "de": ("Liebes Team,\n\n", "Support-Ticket\n", "", "Bitte an den Assistenten: ",
               "Gesprächszusammenfassung:\n"),
    },
}  # fmt: skip


def _person(lang: str, names: Names) -> tuple[str, str, str]:
    """(full name as written, given, family) for ``lang``."""
    if lang == "hu":
        given, family = names.hu()
        return f"{family} {given}", given, family
    if lang == "de":
        given, family = names.de()
        return f"{given} {family}", given, family
    p = ssd._People("en", names.rng, names.avoid).person()
    return p["full"], p["given"], p["family"]


def dates_doc(lang: str, pool: str, rng: random.Random, avoid: frozenset[str]) -> Builder:
    """A person with (most of the time) a birth date, and 1-3 other dates that are ``O``."""
    names = Names(pool, rng, avoid)
    b = Builder().add(rng.choice(OPENERS[pool][lang]))
    full, given, family = _person(lang, names)
    if rng.random() < 0.75:
        dob = fmt_date(lang, birth_day(rng), rng)
        frame = rng.choice(DOB_FRAMES[pool][lang])
        b.fill(frame, {"p": (full, E.PERSON, full), "dob": (dob, E.DATE_OF_BIRTH, None)})
    else:  # no birth date at all: only the other dates
        b.gold(full, E.PERSON, full)
    b.add("\n")
    frames = list(OTHER_DATE_FRAMES[pool][lang])
    rng.shuffle(frames)
    for frame in frames[: rng.randint(1, 3)]:
        old = "{do}" in frame
        day = other_day(rng, old=old)
        text = fmt_date(lang, day, rng, year=old or rng.random() < 0.8)
        b.fill(frame.replace("{do}", "{d}"), {"d": (text, None, None)}).add("\n")
    if rng.random() < 0.4:
        b.add({"hu": "E-mail: ", "en": "Email: ", "de": "E-Mail: "}[lang])
        b.gold(email(rng, given, family), E.EMAIL).add("\n")
    return b


# --- numbers that are not bank accounts --------------------------------------------------------

NUMBER_FRAMES: dict[str, dict[str, tuple[str, ...]]] = {
    "sel": {
        "hu": ("Rendelésszám: {n}", "Ügyfélazonosító: {n}", "Hivatkozási szám: {n}"),
        "en": ("Order number: {n}", "Customer ID: {n}", "Reference: {n}"),
        "de": ("Bestellnummer: {n}", "Kundennummer: {n}", "Vorgangsnummer: {n}"),
    },
    "train": {
        "hu": ("Számla sorszáma: {n}", "Csomagkövetési szám: {n}", "Jegyszám: {n}",
               "Szerződésszám: {n}"),
        "en": ("Invoice no. {n}", "Tracking number: {n}", "Ticket #{n}", "Contract no. {n}"),
        "de": ("Rechnungsnr. {n}", "Sendungsnummer: {n}", "Ticket-Nr. {n}", "Vertragsnummer: {n}"),
    },
}  # fmt: skip
ACCOUNT_FRAMES = {
    "hu": "Számlaszám: {iban}", "en": "Bank account: {iban}", "de": "IBAN: {iban}",
}  # fmt: skip


def _number(rng: random.Random) -> str:
    d = lambda n: "".join(rng.choice("0123456789") for _ in range(n))  # noqa: E731
    return rng.choice((
        f"{rng.randint(1, 9)}{d(9)}", f"INV-{rng.randint(2023, 2026)}-{d(6)}",
        f"{d(4)}-{d(4)}-{d(4)}", f"{rng.choice('ABCDEFGHKLMNPRSTVWXZ')}{d(10)}",
        f"{d(3)} {d(3)} {d(3)} {d(3)}", f"{d(8)}",
    ))  # fmt: skip


def numbers_doc(lang: str, pool: str, rng: random.Random, avoid: frozenset[str]) -> Builder:
    """Order, customer and reference numbers as ``O``; half the time one labelled IBAN."""
    names = Names(pool, rng, avoid)
    b = Builder().add(rng.choice(OPENERS[pool][lang]))
    full, _given, _family = _person(lang, names)
    b.add({"hu": "Ügyfél: ", "en": "Customer: ", "de": "Kunde: "}[lang])
    b.gold(full, E.PERSON, full).add("\n")
    frames = list(NUMBER_FRAMES[pool][lang])
    rng.shuffle(frames)
    lines: list[tuple[str, str | None]] = [(f, _number(rng)) for f in frames[: rng.randint(1, 3)]]
    if rng.random() < 0.5:
        lines.insert(rng.randint(0, len(lines)), (ACCOUNT_FRAMES[lang], None))
    for frame, number in lines:
        if number is None:
            iban = contact(lang, rng)["iban"]
            b.fill(frame, {"iban": (iban, E.BANK_ACCOUNT, None)}).add("\n")
        else:
            b.fill(frame, {"n": (number, None, None)}).add("\n")
    return b


# --- German genitives --------------------------------------------------------------------------

#: ``{g}`` a genitive (given or full name), ``{t}`` Herrn/Frau + surname in the genitive,
#: ``{n}`` a plain name, ``{phone}`` / ``{email}`` / ``{iban}`` contact details.
DE_GEN_FRAMES: dict[str, tuple[str, ...]] = {
    "sel": (
        "Hi, ist {g} Paket schon da? Ruf sonst {n} an: {phone}",
        "{g} Termin wurde auf Donnerstag verschoben.",
        "Betreff: Unterlagen\n\nHallo,\nich habe {t} Antrag geprüft. Rückfragen an {email}.\n",
        "Kannst du {g} Rechnung an {email} schicken?",
        "Laut {t} Schreiben fehlt noch die Unterschrift.",
        "{g} neue Nummer ist {phone}.",
        "Bitte überweise {g} Anteil auf {iban}.",
        "Sehr geehrte Damen und Herren,\n\n{t} Kündigung ist bei uns eingegangen.\n",
    ),
    "train": (
        "{g} Wohnung ist ab Montag frei, Schlüssel bei {n}.",
        "Hast du {g} Adresse? Ich brauche sie für das Formular.",
        "Ich habe {t} Vertrag eingescannt und an {email} geschickt.",
        "Nach {t} Angaben war der Zähler defekt.",
        "{g} Flug landet um 18 Uhr, Handy: {phone}",
        "Die Kaution geht auf {g} Konto {iban}.",
        "Betreff: Rückruf\n\n{t} Anfrage ist offen, bitte unter {phone} melden.\n",
        "Kurze Info: {g} Auto steht noch in der Werkstatt.",
        "Wir warten auf {g} Rückmeldung bis Freitag.",
        "Liebe Grüße an {n}, und danke für {g} Hilfe!",
    ),
}


def de_genitive_doc(lang: str, pool: str, rng: random.Random, avoid: frozenset[str]) -> Builder:
    names = Names(pool, rng, avoid)
    b = Builder().add(rng.choice(OPENERS[pool]["de"]))
    frames = list(DE_GEN_FRAMES[pool])
    rng.shuffle(frames)
    for frame in frames[: rng.randint(1, 3)]:
        given, family = names.de()
        full = f"{given} {family}"
        info = contact("de", rng)
        rest = frame
        while "{" in rest:
            before, _, tail = rest.partition("{")
            key, _, rest = tail.partition("}")
            b.add(before)
            if key == "g":
                name = rng.choice((given, given, full))
                add_de_genitive(b, name, full, rng)
            elif key == "t":
                b.add(rng.choice(("Frau ", "Herrn ")))
                add_de_genitive(b, family, full, rng)
            elif key == "n":
                other_g, other_f = names.de()
                b.gold(f"{other_g} {other_f}", E.PERSON, f"{other_g} {other_f}")
            elif key == "phone":
                b.gold(info["phone"], E.PHONE)
            elif key == "email":
                b.gold(email(rng, given, family), E.EMAIL)
            elif key == "iban":
                b.gold(info["iban"], E.BANK_ACCOUNT)
        b.add(rest).add(rng.choice((" ", "\n")))
    return b


# --- Hungarian surname + inflected given name ---------------------------------------------------

#: ``{n}`` the name in the case of the frame's key.
HU_FRAMES: dict[str, dict[str, tuple[str, ...]]] = {
    "sel": {
        "dat": ("Átküldöd {n} a linket?", "A számlát {n} kell kiállítani."),
        "acc": ("Holnap hívd fel {n}, kérlek.", "Kérem, tájékoztassák {n} az eredményről."),
        "del": ("Mit tudsz {n}?",),
        "ins": ("Ma beszéltem {n} telefonon.",),
        "abl": ("Kaptál már választ {n}?",),
        "all": ("Irányítsd a kérdést {n}.",),
        "ade": ("A kulcs most {n} van.",),
        "nom": ("{n} írt, hogy késik.",),
        "poss": ("Ez a táska {n}.",),
    },
    "train": {
        "dat": ("Írj egy e-mailt {n} a határidőről.", "Továbbítottam {n} az ajánlatot.",
                "Köszönd meg {n} a segítséget!", "A jelszót ne küldd el {n}."),
        "acc": ("Keresd meg {n} a recepción.", "Meghívtuk {n} a megbeszélésre.",
                "Kérlek, értesítsd {n} a változásról.", "Tegnap láttam {n} a boltban."),
        "del": ("A jegyzőkönyv {n} is szól.", "Sokat hallottam már {n}."),
        "ins": ("Egyeztess {n} a szállításról.", "Holnap {n} találkozom."),
        "abl": ("Kérdezd meg {n}, ő tudja.", "Levelet kaptunk {n}."),
        "all": ("Vidd át a papírokat {n}.", "Fordulj {n} bizalommal."),
        "ade": ("Az eredeti példány {n} maradt.",),
        "nom": ("{n} ma szabadságon van.", "Az ügyintéző {n} lesz."),
        "poss": ("A kék kabát {n}.",),
    },
}  # fmt: skip


def hu_surname_given_doc(
    lang: str, pool: str, rng: random.Random, avoid: frozenset[str]
) -> Builder:
    names = Names(pool, rng, avoid)
    b = Builder().add(rng.choice(OPENERS[pool]["hu"]))
    people = [names.hu() for _ in range(rng.choice((1, 1, 2)))]
    for i in range(rng.randint(1, 3)):
        given, family = people[i % len(people)]
        full = f"{family} {given}"
        case = rng.choice(HU_CASES[:-2] * 2 + HU_CASES[-2:])  # obliques twice as often
        frame = rng.choice(HU_FRAMES[pool][case])
        before, _, after = frame.partition("{n}")
        b.add(before)
        add_hu_case(b, full, case, capital=not before)
        b.add(after).add(rng.choice((" ", "\n")))
    if rng.random() < 0.3:
        given, family = people[0]
        b.add("Elérhetőség: ").gold(email(rng, given, family), E.EMAIL)
    return b


BUILDERS: dict[str, Callable[[str, str, random.Random, frozenset[str]], Builder]] = {
    "de-genitive": de_genitive_doc,
    "hu-surname-given": hu_surname_given_doc,
    "dates": dates_doc,
    "numbers": numbers_doc,
}
