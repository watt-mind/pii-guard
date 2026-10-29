"""NER v3.3 targeted add-on and replay slice for a short fine-tune of soup S30 (LAB-1512).

Three parts, all fictional and template-based (no model is called), seeded:

- ``names``: names in inflected case forms. Hungarian (the LAB-1494 smoke failure was an
  accusative name): nominative, accusative, dative, instrumental (assimilated), ablative,
  delative, allative, adessive and possessive ``-é``; double given names, hyphenated surnames,
  the married ``-né`` form. Polish: the oblique cases of given names and of ``-ski``/``-cka``
  and consonant surnames. German: the genitive ``-s`` and apostrophe. Spans are ``PERSON``
  and include the case ending, as in the s11 corpus and the fixtures.
- ``payload``: hard negatives for structured payloads (LAB-1477, LAB-1482): JSON, tool-call
  arguments, YAML, logs and CSV whose numbers (ticket, order, issue and PR numbers, counts,
  ports, sizes, PIDs, line numbers, versions, timestamps, UUIDs) are **not** personal data.
  One document in three also carries a fictional person or e-mail in a name field, labelled,
  so the model learns the field, not "payloads never hold PII".
- ``agent``: hard negatives for agent text (LAB-1482, LAB-1485): code, shell commands, tool and
  harness names (``pi``, ``codex``, ``python3``), ``@scope/package`` paths, booleans, algorithm
  eponyms (Luhn, Dijkstra). One document in four also names a fictional person, labelled.

Names come from the hand-written lists below, combined at random, so no generated person is a
real one; a document whose full name occurs in any evaluation text (``eval/fixtures``,
``eval/synthetic``, ``eval/datasets``, ``data/datasets/fixtures``) is redrawn. Train and dev
use different seeds. Nothing is derived from an evaluation or test split::

    uv run --no-sync python training/ner/targeted_v33.py addon --out eval/generated/v33-addon
    uv run --no-sync python training/ner/targeted_v33.py replay \\
        --final eval/generated/v31-final --out eval/generated/v33-replay

The replay slice is a seeded sample of the v3.1-B mix files (``v31_data.derive``), S30's own
training data, so the fine-tune does not forget what the soup knows.
"""

# Seeded synthetic data: the standard PRNG is the point.
# ruff: noqa: S311

from __future__ import annotations

import argparse
import json
import random
import sys
import unicodedata
import uuid
from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pii_guard.eval.fixtures import Document, GoldSpan, load_fixtures, write_fixtures
from pii_guard.types import EntityType
from pii_guard.vault.inflection import inflection_for, restore

SEED = 1512
DEV_SEED = 151200
#: (part, language, train docs, dev docs). Fixed in the protocol README before generation.
PLAN: tuple[tuple[str, str, int, int], ...] = (
    ("names", "hu", 1500, 150),
    ("names", "pl", 300, 30),
    ("names", "de", 300, 30),
    ("payload", "hu", 200, 20),
    ("payload", "en", 200, 20),
    ("payload", "de", 200, 20),
    ("agent", "hu", 200, 20),
    ("agent", "en", 200, 20),
    ("agent", "de", 200, 20),
)
EVAL_DIRS = (
    Path("eval/fixtures"),
    Path("eval/synthetic"),
    Path("eval/datasets"),
    Path("data/datasets/fixtures"),
)
#: Replay sample sizes per v3.1-final file (protocol README). Seeded, without replacement.
REPLAY: dict[str, int] = {
    "openpii/hu-openpii-train-10k.jsonl": 1000,
    "openpii/en-openpii-train.jsonl": 500,
    "openpii/de-openpii-train.jsonl": 500,
    "openpii/pl-openpii-train.jsonl": 250,
    "openpii/cs-openpii-train.jsonl": 250,
    "openpii/sk-openpii-train.jsonl": 250,
    "openpii/ro-openpii-train.jsonl": 250,
    "openpii/hr-openpii-train.jsonl": 250,
    "openpii/sl-openpii-train.jsonl": 250,
    "s11/hu-distill-train.jsonl": 600,
    "s11/en-distill-train.jsonl": 600,
    "negatives/hu-negatives-train.jsonl": 300,
    "negatives/en-negatives-train.jsonl": 300,
    "negatives/de-negatives-train.jsonl": 300,
    "privy/en-privy-train-6k.jsonl": 300,
    "wismut/en-wismut-train.jsonl": 100,
    "wismut/de-wismut-train.jsonl": 100,
    "wismut/pl-wismut-train.jsonl": 100,
    "wismut/cs-wismut-train.jsonl": 100,
    "wismut/ro-wismut-train.jsonl": 100,
    "nemotron/en-nemotron-train.jsonl": 200,
    "gretel/en-gretel-train.jsonl": 200,
}
E = EntityType

# --- building a document --------------------------------------------------------------------


@dataclass
class Builder:
    """Text with gold spans, appended piece by piece."""

    parts: list[str] = field(default_factory=list)
    spans: list[GoldSpan] = field(default_factory=list)
    names: list[str] = field(default_factory=list)
    _len: int = 0

    def add(self, text: str) -> Builder:
        self.parts.append(text)
        self._len += len(text)
        return self

    def gold(self, text: str, entity_type: EntityType, lemma: str | None = None) -> Builder:
        self.spans.append(GoldSpan(self._len, self._len + len(text), entity_type, text))
        if lemma:
            self.names.append(lemma)
        return self.add(text)

    def fill(self, template: str, slots: dict[str, tuple[str, EntityType | None, str | None]]):
        """``template`` with ``{slot}`` markers; each slot is (text, type or None, lemma)."""
        rest = template
        while "{" in rest:
            before, _, tail = rest.partition("{")
            key, _, rest = tail.partition("}")
            self.add(before)
            text, entity_type, lemma = slots[key]
            if entity_type is None:
                self.add(text)
            else:
                self.gold(text, entity_type, lemma)
        self.add(rest)
        return self

    def document(self, doc_id: str, language: str, meta: dict[str, Any]) -> Document:
        text = "".join(self.parts)
        for s in self.spans:
            if text[s.start : s.end] != s.text:  # pragma: no cover - a builder bug
                raise ValueError(f"{doc_id}: span at {s.start} doesn't match its text")
        meta = {**meta, "names": sorted(set(self.names))}
        return Document(doc_id, language, text, tuple(self.spans), meta)


def ascii_fold(text: str) -> str:
    folded = unicodedata.normalize("NFKD", text.replace("ł", "l").replace("Ł", "L"))
    return "".join(ch for ch in folded if not unicodedata.combining(ch))


def email_for(rng: random.Random, given: str, family: str) -> str:
    g, f = (ascii_fold(x).lower().replace(" ", "").replace("-", "") for x in (given, family))
    local = rng.choice((f"{g}.{f}", f"{g[0]}.{f}", f"{f}.{g}", f"{g}{rng.randint(1, 99)}"))
    domain = rng.choice(("example.com", "example.org", "example.net", "pelda.example"))
    return f"{local}@{domain}"


# --- Hungarian names and cases ----------------------------------------------------------------

# Given names whose vowel harmony follows the simple rule in :func:`hu_harmony` (names that
# break it, like Dániel, Ágnes, Róbert, József, Noémi, are left out on purpose).
HU_GIVEN_M = (
    "Béla", "László", "István", "Ferenc", "Imre", "Endre", "Gergely", "Ödön", "Tibor", "Sándor",
    "Miklós", "Lajos", "Árpád", "Szabolcs", "Zsolt", "Attila", "Barnabás", "Márton", "Benedek",
    "Vilmos", "Elemér", "Csongor", "Ottó", "Kálmán", "Dezső", "Zsigmond", "Gábor", "Zoltán",
    "Tamás", "János", "Kristóf", "Gergő", "Ákos", "Márk", "Bence", "Levente", "Botond",
    "Bálint", "Csaba", "Patrik", "Martin", "Norbert", "Henrik", "Erik", "Ádám", "Dávid",
    "Balázs", "Viktor", "Krisztián", "Lőrinc", "Huba", "Bulcsú", "Nándor", "Iván", "Oszkár",
)  # fmt: skip
HU_GIVEN_F = (
    "Anna", "Eszter", "Katalin", "Zsófia", "Erzsébet", "Éva", "Orsolya", "Petra", "Nóra",
    "Dóra", "Lilla", "Gréta", "Hajnalka", "Boglárka", "Melinda", "Csilla", "Ildikó", "Enikő",
    "Tünde", "Gyöngyi", "Mária", "Rozália", "Krisztina", "Tímea", "Edit", "Judit", "Kinga",
    "Réka", "Ilona", "Viktória", "Emese", "Andrea", "Beáta", "Szilvia", "Mónika", "Zita",
    "Fruzsina", "Vivien", "Rita", "Klára", "Margit", "Piroska", "Erika", "Hanna", "Luca",
)  # fmt: skip
HU_SURNAMES = (
    "Kovács", "Szabó", "Tóth", "Nagy", "Horváth", "Varga", "Kiss", "Molnár", "Németh",
    "Farkas", "Balogh", "Papp", "Takács", "Juhász", "Lakatos", "Mészáros", "Oláh", "Simon",
    "Rácz", "Fekete", "Szilágyi", "Török", "Fehér", "Balázs", "Gál", "Kis", "Szűcs", "Kocsis",
    "Pintér", "Fodor", "Szalai", "Sipos", "Magyar", "Lukács", "Gulyás", "Biró", "Király",
    "Katona", "Jakab", "Bogdán", "Boros", "Fazekas", "Kelemen", "Antal", "Orosz", "Somogyi",
    "Fülöp", "Veres", "Budai", "Vincze", "Hegedűs", "Deák", "Illés", "Vass", "Szőke",
    "Fábián", "Vörös", "Lengyel", "Bognár", "Jónás", "Szekeres", "Halász", "Dudás", "Hajdu",
    "Kozma", "Bakos", "Major", "Hegyi", "Virág", "Orbán", "Barta", "Csizmadia", "Bodnár",
    "Sárközi", "Erdős", "Bartos", "Pásztor", "Kardos", "Szénási", "Berki", "Duka", "Tamási",
)  # fmt: skip

_HU_VOWELS = set("aáeéiíoóöőuúüű")
_HU_BACK = set("aáoóuú")
_HU_ROUND = set("öőüű")
_HU_LONG = {"a": "á", "e": "é"}
_HU_PLAIN_ACC = ("ly", "ny", "sz", "zs", "j", "l", "n", "r", "s", "z")


def hu_harmony(word: str) -> str:
    """``back``, ``front`` or ``round`` (front rounded) for the suffixes of ``word``."""
    vowels = [ch for ch in word.lower() if ch in _HU_VOWELS]
    if any(v in _HU_BACK for v in vowels):
        return "back"
    return "round" if vowels and vowels[-1] in _HU_ROUND else "front"


#: Case -> suffix by harmony (back, front, round). ``acc`` and ``é`` are handled apart.
HU_CASES: dict[str, tuple[str, str, str]] = {
    "dat": ("nak", "nek", "nek"),
    "ins": ("val", "vel", "vel"),
    "abl": ("tól", "től", "től"),
    "del": ("ról", "ről", "ről"),
    "all": ("hoz", "hez", "höz"),
    "ade": ("nál", "nél", "nél"),
    "ter": ("ig", "ig", "ig"),
    "cau": ("ért", "ért", "ért"),
}
_MATCHER = None


def _hu_matcher():
    global _MATCHER
    if _MATCHER is None:
        _MATCHER = inflection_for("hu")
    return _MATCHER


def hu_accusative(word: str) -> str:
    last = word[-1]
    if last in _HU_LONG:
        return word[:-1] + _HU_LONG[last] + "t"
    if last.lower() in _HU_VOWELS:
        return word + "t"
    if word.lower().endswith("cs") or not word.lower().endswith(_HU_PLAIN_ACC):
        link = {"back": "ot", "front": "et", "round": "öt"}[hu_harmony(word)]
        return word + link
    return word + "t"


def hu_inflect(full: str, case: str) -> str:
    """``full`` (``Kovács Béla``) with its last word in ``case`` (``nom``, ``acc``, ``dat`` …)."""
    if case == "nom":
        return full
    head, _, last = full.rpartition(" ")
    prefix = f"{head} " if head else ""
    if case == "acc":
        return prefix + hu_accusative(last)
    if case == "poss":
        return prefix + (last[:-1] + _HU_LONG[last[-1]] if last[-1] in _HU_LONG else last) + "é"
    back, front, rnd = HU_CASES[case]
    suffix = {"back": back, "front": front, "round": rnd}[hu_harmony(last)]
    return prefix + restore(_hu_matcher(), last, suffix, E.PERSON)


def hu_person(rng: random.Random) -> tuple[str, str, str]:
    """(full name, given names, surname): ``Nagy-Kovács Anna Mária``, ``Kiss Béláné`` …"""
    female = rng.random() < 0.5
    pool = HU_GIVEN_F if female else HU_GIVEN_M
    given = rng.choice(pool)
    surname = rng.choice(HU_SURNAMES)
    roll = rng.random()
    if roll < 0.12:
        other = rng.choice([s for s in HU_SURNAMES if s != surname])
        surname = f"{surname}-{other}"
    elif roll < 0.24:
        second = rng.choice([g for g in pool if g != given])
        given = f"{given} {second}"
    elif roll < 0.30 and not female:  # married form: Kiss Béláné, "wife of Béla Kiss"
        last = given[:-1] + _HU_LONG[given[-1]] if given[-1] in _HU_LONG else given
        return f"{surname} {last}né", f"{given}né", surname
    return f"{surname} {given}", given, surname


# Sentence frames by the case of the name slot {n}. Written for this ticket; none is a copy of
# a fixture sentence (decontam.py checks the documents).
HU_FRAMES: dict[str, tuple[str, ...]] = {
    "nom": (
        "{n} jelezte, hogy a jövő héten nem tud részt venni az egyeztetésen.",
        "A beszámolót {n} állította össze, a táblázatokat csatoltuk.",
        "Ügyintéző: {n}.",
        "Tegnap {n} is bejött az irodába, és átnézte a terveket.",
        "Az ügyfél neve {n}, a kérelmet március elején adta be.",
        "{n} szerint a szállítás csúszik két napot.",
    ),
    "acc": (
        "Kérem, értesítsék {n} a döntésről.",
        "Megbízom {n}, hogy a nevemben eljárjon a hivatalban.",
        "Holnap délelőtt felhívjuk {n}, hogy pontosítsuk a részleteket.",
        "A bizottság {n} javasolta a projekt vezetésére.",
        "Szeretettel üdvözöljük {n} a csapatban!",
        "Kinevezték {n} a pénzügyi osztály élére.",
        "Kérlek, keresd meg {n}, mert ő tudja a jelszó nélküli belépés menetét.",
        "Felkérjük {n}, hogy a következő ülésen ismertesse a jelentést.",
        "Az ügyben {n} hallgatták meg tanúként.",
        "Jelölöm {n} a kapcsolattartó szerepére.",
    ),
    "dat": (
        "A szerződés tervezetét elküldtük {n} jóváhagyásra.",
        "Kérlek, írj egy rövid választ {n} a késésről.",
        "A számlát {n} kell címezni.",
        "Köszönjük {n} a gyors segítséget.",
        "A díjat {n} utaltuk át pénteken.",
        "{n} a kérése az, hogy a határidőt tolják ki.",
        "Az igazoláshoz {n} kell aláírnia a kérelmet.",
    ),
    "ins": (
        "Holnap egyeztetek {n} a költségvetésről.",
        "A megbeszélést {n} együtt tartjuk meg.",
        "Telefonon beszéltem {n}, és megerősítette az időpontot.",
        "A projekten {n} dolgozunk együtt.",
        "Kérlek, vedd fel a kapcsolatot {n} a szállítás ügyében.",
    ),
    "abl": (
        "Levelet kaptunk {n} a reklamáció ügyében.",
        "A kérdést {n} érdemes megkérdezni.",
        "Az aláírt példányt {n} vettük át.",
        "{n} még várjuk a hiányzó igazolást.",
    ),
    "del": (
        "A jegyzőkönyv {n} is említést tesz.",
        "Sok jót hallottam {n}.",
        "Az értékelés {n} szól, nem a csapatról.",
        "Kérlek, írj egy rövid összefoglalót {n} a hírlevélbe.",
    ),
    "all": (
        "A csomagot {n} kell kézbesíteni.",
        "Az ügyet {n} irányítottuk át.",
        "Fordulj bizalommal {n}, ha kérdésed van.",
        "A panasz {n} érkezett be először.",
    ),
    "ade": (
        "A dokumentumok jelenleg {n} vannak.",
        "Az eredeti példány {n} maradt.",
        "{n} kell jelentkezni a belépőkártyáért.",
    ),
    "poss": (
        "Ez a laptop {n}, ne vigyétek el.",
        "A sarokban álló íróasztal {n}.",
    ),
    "ter": ("A kulcsot {n} kell elvinni, ott átveszik.",),
    "cau": ("Aggódunk {n}, napok óta nem válaszol.", "A csapat {n} is kiállt a vitában."),
}
HU_OPENERS = (
    "Tárgy: egyeztetés\n\n", "Kedves Kollégák!\n\n", "Jegyzet a mai hívásról:\n", "",
    "Szia!\n", "Feladat a következő sprintre:\n", "Ügyfélszolgálati bejegyzés\n",
    "Kérés az asszisztensnek: ",
)  # fmt: skip
HU_CLOSERS = (
    "\n\nÜdvözlettel:\nAz ügyfélszolgálat", "", "\nKöszönöm!", "\n\nKérlek, jelezz vissza.",
    "\nA határidő péntek.",
)  # fmt: skip
HU_CASE_WEIGHTS = (
    ("acc", 5), ("dat", 4), ("ins", 3), ("abl", 2), ("del", 2), ("all", 2), ("ade", 1),
    ("poss", 1), ("ter", 1), ("cau", 1), ("nom", 3),
)  # fmt: skip


def _weighted(rng: random.Random, pairs: Sequence[tuple[str, int]]) -> str:
    return rng.choices([p for p, _ in pairs], [w for _, w in pairs])[0]


def hu_names_doc(rng: random.Random) -> Builder:
    b = Builder().add(rng.choice(HU_OPENERS))
    people = [hu_person(rng) for _ in range(rng.choice((1, 1, 2, 2, 3)))]
    for i in range(rng.randint(2, 5)):
        full, given, surname = people[i % len(people)]
        case = _weighted(rng, HU_CASE_WEIGHTS)
        frame = rng.choice(HU_FRAMES[case])
        surface = hu_inflect(full, case)
        if frame.startswith("{n}"):
            surface = surface[0].upper() + surface[1:]
        b.fill(frame, {"n": (surface, E.PERSON, full)})
        b.add(rng.choice((" ", " ", "\n")))
    if rng.random() < 0.3:
        full, given, surname = people[0]
        b.add("Elérhetőség: ").gold(
            email_for(rng, given.split()[0].removesuffix("né"), surname), E.EMAIL
        ).add(".")
    b.add(rng.choice(HU_CLOSERS))
    return b


# --- Polish -----------------------------------------------------------------------------------

#: given name -> (nom, gen, dat, acc, ins, loc)
PL_GIVEN_M = {
    "Jan": ("Jan", "Jana", "Janowi", "Jana", "Janem", "Janie"),
    "Piotr": ("Piotr", "Piotra", "Piotrowi", "Piotra", "Piotrem", "Piotrze"),
    "Tomasz": ("Tomasz", "Tomasza", "Tomaszowi", "Tomasza", "Tomaszem", "Tomaszu"),
    "Paweł": ("Paweł", "Pawła", "Pawłowi", "Pawła", "Pawłem", "Pawle"),
    "Marek": ("Marek", "Marka", "Markowi", "Marka", "Markiem", "Marku"),
    "Krzysztof": (
        "Krzysztof",
        "Krzysztofa",
        "Krzysztofowi",
        "Krzysztofa",
        "Krzysztofem",
        "Krzysztofie",
    ),
    "Andrzej": ("Andrzej", "Andrzeja", "Andrzejowi", "Andrzeja", "Andrzejem", "Andrzeju"),
    "Michał": ("Michał", "Michała", "Michałowi", "Michała", "Michałem", "Michale"),
    "Łukasz": ("Łukasz", "Łukasza", "Łukaszowi", "Łukasza", "Łukaszem", "Łukaszu"),
    "Wojciech": ("Wojciech", "Wojciecha", "Wojciechowi", "Wojciecha", "Wojciechem", "Wojciechu"),
    "Adam": ("Adam", "Adama", "Adamowi", "Adama", "Adamem", "Adamie"),
    "Jakub": ("Jakub", "Jakuba", "Jakubowi", "Jakuba", "Jakubem", "Jakubie"),
}
PL_GIVEN_F = {
    "Anna": ("Anna", "Anny", "Annie", "Annę", "Anną", "Annie"),
    "Katarzyna": ("Katarzyna", "Katarzyny", "Katarzynie", "Katarzynę", "Katarzyną", "Katarzynie"),
    "Magdalena": ("Magdalena", "Magdaleny", "Magdalenie", "Magdalenę", "Magdaleną", "Magdalenie"),
    "Agnieszka": ("Agnieszka", "Agnieszki", "Agnieszce", "Agnieszkę", "Agnieszką", "Agnieszce"),
    "Joanna": ("Joanna", "Joanny", "Joannie", "Joannę", "Joanną", "Joannie"),
    "Monika": ("Monika", "Moniki", "Monice", "Monikę", "Moniką", "Monice"),
    "Ewa": ("Ewa", "Ewy", "Ewie", "Ewę", "Ewą", "Ewie"),
    "Małgorzata": (
        "Małgorzata",
        "Małgorzaty",
        "Małgorzacie",
        "Małgorzatę",
        "Małgorzatą",
        "Małgorzacie",
    ),
    "Barbara": ("Barbara", "Barbary", "Barbarze", "Barbarę", "Barbarą", "Barbarze"),
    "Zofia": ("Zofia", "Zofii", "Zofii", "Zofię", "Zofią", "Zofii"),
    "Marta": ("Marta", "Marty", "Marcie", "Martę", "Martą", "Marcie"),
    "Aleksandra": (
        "Aleksandra",
        "Aleksandry",
        "Aleksandrze",
        "Aleksandrę",
        "Aleksandrą",
        "Aleksandrze",
    ),
}
#: Adjectival surnames by their masculine stem: Kowal + ski / ska.
PL_ADJ = (
    ("Kowal", "ski"), ("Wiśniew", "ski"), ("Lewandow", "ski"), ("Zieliń", "ski"),
    ("Szymań", "ski"), ("Dąbrow", "ski"), ("Kozłow", "ski"), ("Jankow", "ski"),
    ("Kwiatkow", "ski"), ("Wróblew", "ski"), ("Nowi", "cki"), ("Wyso", "cki"), ("Zawa", "dzki"),
)  # fmt: skip
#: Noun surnames, masculine (nom, gen, dat, acc, ins, loc); the feminine form doesn't decline.
PL_NOUN = {
    "Nowak": ("Nowak", "Nowaka", "Nowakowi", "Nowaka", "Nowakiem", "Nowaku"),
    "Wójcik": ("Wójcik", "Wójcika", "Wójcikowi", "Wójcika", "Wójcikiem", "Wójciku"),
    "Mazur": ("Mazur", "Mazura", "Mazurowi", "Mazura", "Mazurem", "Mazurze"),
    "Krawczyk": ("Krawczyk", "Krawczyka", "Krawczykowi", "Krawczyka", "Krawczykiem", "Krawczyku"),
    "Kaczmarek": (
        "Kaczmarek",
        "Kaczmarka",
        "Kaczmarkowi",
        "Kaczmarka",
        "Kaczmarkiem",
        "Kaczmarku",
    ),
    "Zając": ("Zając", "Zająca", "Zającowi", "Zająca", "Zającem", "Zającu"),
    "Król": ("Król", "Króla", "Królowi", "Króla", "Królem", "Królu"),
    "Pawlak": ("Pawlak", "Pawlaka", "Pawlakowi", "Pawlaka", "Pawlakiem", "Pawlaku"),
}
PL_CASES = ("nom", "gen", "dat", "acc", "ins", "loc")
_PL_ADJ_M = {"nom": "i", "gen": "iego", "dat": "iemu", "acc": "iego", "ins": "im", "loc": "im"}
_PL_ADJ_F = {"nom": "a", "gen": "iej", "dat": "iej", "acc": "ą", "ins": "ą", "loc": "iej"}


def pl_surname(stem: str, ending: str, female: bool, case: str) -> str:
    base = stem + ending[:-1]  # Kowal + sk, Nowi + ck, Zawa + dzk
    return base + (_PL_ADJ_F if female else _PL_ADJ_M)[case]


def pl_person(rng: random.Random) -> tuple[Callable[[str], str], str]:
    female = rng.random() < 0.5
    given = rng.choice(list(PL_GIVEN_F if female else PL_GIVEN_M))
    table = (PL_GIVEN_F if female else PL_GIVEN_M)[given]
    if rng.random() < 0.6:
        stem, ending = rng.choice(PL_ADJ)

        def surname(case: str) -> str:
            return pl_surname(stem, ending, female, case)
    else:
        noun = rng.choice(list(PL_NOUN))

        def surname(case: str) -> str:
            return noun if female else PL_NOUN[noun][PL_CASES.index(case)]

    def form(case: str) -> str:
        return f"{table[PL_CASES.index(case)]} {surname(case)}"

    return form, form("nom")


PL_FRAMES: dict[str, tuple[str, ...]] = {
    "nom": (
        "{n} prosi o przesunięcie terminu spotkania.",
        "Sprawę prowadzi {n}.",
        "{n} przesyła poprawioną wersję umowy.",
    ),
    "gen": (
        "Na prośbę {n} wysyłamy zestawienie kosztów.",
        "Czekamy na podpis {n} pod aneksem.",
        "Dokumenty {n} są już w archiwum.",
        "Nie mamy jeszcze odpowiedzi od {n}.",
    ),
    "dat": (
        "Przekazaliśmy {n} wszystkie załączniki.",
        "Proszę wysłać {n} fakturę do piątku.",
        "Dziękujemy {n} za szybką pomoc.",
    ),
    "acc": (
        "Upoważniam {n} do odbioru przesyłki.",
        "Proszę poinformować {n} o decyzji zarządu.",
        "Zaprosiliśmy {n} na jutrzejsze spotkanie.",
    ),
    "ins": (
        "Wczoraj rozmawiałem z {n} o budżecie.",
        "Spotkanie z {n} odbędzie się w środę.",
        "Proszę skontaktować się z {n} w sprawie dostawy.",
    ),
    "loc": ("Rozmawialiśmy o {n} na ostatnim zebraniu.", "W notatce o {n} brakuje daty."),
}
PL_OPENERS = ("Dzień dobry,\n", "Notatka ze spotkania:\n", "", "Temat: dostawa\n\n", "Cześć!\n")
PL_CLOSERS = ("\n\nPozdrawiam serdecznie", "", "\nDziękuję.", "\nTermin: piątek.")


def pl_names_doc(rng: random.Random) -> Builder:
    b = Builder().add(rng.choice(PL_OPENERS))
    people = [pl_person(rng) for _ in range(rng.choice((1, 2, 2)))]
    for i in range(rng.randint(2, 4)):
        form, lemma = people[i % len(people)]
        case = rng.choice(PL_CASES[1:] if rng.random() < 0.8 else PL_CASES)
        frame = rng.choice(PL_FRAMES[case])
        b.fill(frame, {"n": (form(case), E.PERSON, lemma)})
        b.add(rng.choice((" ", "\n")))
    b.add(rng.choice(PL_CLOSERS))
    return b


# --- German -----------------------------------------------------------------------------------

DE_GIVEN_M = (
    "Jonas", "Lukas", "Felix", "Maximilian", "Paul", "Leon", "Elias", "Niklas", "Tobias",
    "Matthias", "Hans", "Klaus", "Moritz",
)  # fmt: skip
DE_GIVEN_F = (
    "Anna", "Lena", "Laura", "Julia", "Sophie", "Marie", "Katharina", "Sabine", "Ursula",
    "Claudia", "Petra", "Franziska", "Johanna",
)  # fmt: skip
DE_GIVEN = DE_GIVEN_M + DE_GIVEN_F
DE_SURNAMES = (
    "Müller", "Schmidt", "Schneider", "Fischer", "Weber", "Meyer", "Wagner", "Becker", "Schulz",
    "Hoffmann", "Koch", "Richter", "Klein", "Wolf", "Schröder", "Neumann", "Schwarz", "Braun",
    "Zimmermann", "Krüger", "Hartmann", "Lange", "Werner", "Krause", "Lehmann", "Kaiser",
    "Fuchs", "Peters", "Vogel", "Jung", "Seidel", "Brandt", "Haas", "Graf", "Roth", "Frank",
)  # fmt: skip


def de_genitive(name: str) -> str:
    return name + "'" if name.endswith(("s", "ß", "x", "z", "tz")) else name + "s"


DE_FRAMES: dict[str, tuple[str, ...]] = {
    "gen": (
        "{n} Antrag liegt seit Montag vor.",
        "Bitte prüfen Sie {n} Einwand bis Freitag.",
        "Laut {n} Notiz fehlt noch eine Unterschrift.",
        "{n} Vertrag läuft Ende des Jahres aus.",
    ),
    "nom": (
        "{n} hat den Termin bestätigt.",
        "Die Unterlagen hat {n} gestern geschickt.",
        "Zuständig ist {n}.",
    ),
    "obj": (
        "Bitte leiten Sie die Rechnung an {n} weiter.",
        "Wir haben mit {n} telefoniert.",
        "Die Akte wurde {n} übergeben.",
        "Ich habe {n} um Rückruf gebeten.",
    ),
}
DE_OPENERS = ("Hallo zusammen,\n", "Gesprächsnotiz:\n", "", "Betreff: Unterlagen\n\n")
DE_CLOSERS = ("\n\nViele Grüße", "", "\nDanke!", "\nFrist: Freitag.")


def de_names_doc(rng: random.Random) -> Builder:
    b = Builder().add(rng.choice(DE_OPENERS))
    people = [
        f"{rng.choice(DE_GIVEN)} {rng.choice(DE_SURNAMES)}" for _ in range(rng.choice((1, 2)))
    ]
    for i in range(rng.randint(2, 4)):
        full = people[i % len(people)]
        kind = rng.choice(("gen", "gen", "nom", "obj"))
        frame = rng.choice(DE_FRAMES[kind])
        if kind == "gen":
            surface = de_genitive(full)
        elif kind == "obj" and rng.random() < 0.4:  # Herrn/Frau stays outside the span
            surname = full.split()[-1]
            title = "Frau " if full.split()[0] in DE_GIVEN_F else "Herrn "
            b.fill(frame.replace("{n}", title + "{n}"),
                   {"n": (surname, E.PERSON, full)})  # fmt: skip
            b.add(rng.choice((" ", "\n")))
            continue
        else:
            surface = full
        b.fill(frame, {"n": (surface, E.PERSON, full)})
        b.add(rng.choice((" ", "\n")))
    b.add(rng.choice(DE_CLOSERS))
    return b


# --- (b) structured payloads ------------------------------------------------------------------

PAYLOAD_INTRO = {
    "hu": (
        "Itt a lekérdezés eredménye:", "Az eszközhívás válasza:", "A naplóból kimásolva:",
        "Ezt adta vissza az API:", "A jegykezelő exportja:", "Futtasd le ezt a hívást:",
    ),
    "en": (
        "Here is the tool result:", "The API returned:", "Copied from the log:",
        "Ticket export below:", "Run this call:", "Response body:",
    ),
    "de": (
        "Hier ist das Ergebnis des Tool-Aufrufs:", "Die API hat geantwortet:",
        "Aus dem Log kopiert:", "Export aus dem Ticketsystem:", "Bitte diesen Aufruf ausführen:",
    ),
}  # fmt: skip
PAYLOAD_OUTRO = {
    "hu": (
        "A {k} mező alapján zárd le a jegyet.", "Ellenőrizd, hogy a {k} egyezik-e.", "",
        "Ha hibát látsz, nyiss új jegyet.",
    ),
    "en": ("Close it based on the {k} field.", "Check that {k} matches.", "", "Retry on 5xx."),
    "de": ("Schließe es anhand des Felds {k}.", "Prüfe, ob {k} passt.", "", "Bei 5xx erneut."),
}  # fmt: skip
NUMERIC_KEYS = (
    "ticket", "ticket_id", "order", "order_id", "issue", "pr", "pull_request", "count", "total",
    "port", "pid", "size", "bytes", "line", "column", "status", "exit_code", "retries",
    "attempt", "build", "run_id", "job", "page", "per_page", "limit", "offset", "duration_ms",
    "elapsed_ms", "timeout", "max_tokens", "tokens", "items", "quantity", "invoice_no", "seq",
    "version_code", "shard", "replicas", "workers", "threads", "depth", "rank", "score",
)  # fmt: skip
NAME_KEYS = ("assignee", "reporter", "customer_name", "contact", "owner", "requested_by")
EMAIL_KEYS = ("customer_email", "contact_email", "reply_to", "notify")


def small_int(rng: random.Random) -> int:
    return rng.choice(
        (rng.randint(1, 99), rng.randint(100, 9999), rng.randint(1000, 99999),
         rng.randint(10000, 999999), rng.choice((80, 443, 3000, 5432, 6379, 8080, 9090)))
    )  # fmt: skip


def scalar(rng: random.Random, key: str) -> Any:
    if key in ("status",):
        return rng.choice((200, 201, 204, 301, 400, 401, 403, 404, 409, 422, 500, 502, 503))
    if key == "score":
        return round(rng.random(), 3)
    return small_int(rng)


def extra_fields(rng: random.Random) -> dict[str, Any]:
    out: dict[str, Any] = {}
    roll = rng.random()
    if roll < 0.3:
        out["id"] = str(uuid.UUID(int=rng.getrandbits(128)))
    elif roll < 0.5:
        out["created_at_unix_ms"] = rng.randint(1_700_000_000_000, 1_830_000_000_000)
    if rng.random() < 0.4:
        out["version"] = f"{rng.randint(0, 9)}.{rng.randint(0, 40)}.{rng.randint(0, 99)}"
    if rng.random() < 0.3:
        out["sha"] = "".join(rng.choice("0123456789abcdef") for _ in range(rng.choice((7, 12, 40))))
    if rng.random() < 0.3:
        out[rng.choice(("enabled", "draft", "cached", "analytics_enabled"))] = rng.choice(
            (True, False, None)
        )
    if rng.random() < 0.3:
        out["state"] = rng.choice(("open", "closed", "merged", "pending", "failed", "done"))
    return out


EN_GIVEN = (
    "Oliver", "Emily", "James", "Grace", "Thomas", "Hannah", "Daniel", "Chloe", "Samuel",
    "Megan", "Ethan", "Lucy", "Owen", "Isla",
)  # fmt: skip


def _person_for(language: str, rng: random.Random) -> tuple[str, str, str]:
    if language == "hu":
        return hu_person(rng)
    if language == "de":
        given, family = rng.choice(DE_GIVEN), rng.choice(DE_SURNAMES)
    else:
        given = rng.choice(EN_GIVEN)
        family = rng.choice(("Hartley", "Pembroke", "Ashworth", "Fairbanks", "Whitlock",
                             "Calloway", "Thornbury", "Ellison", "Marlowe", "Kingsley",
                             "Radcliffe", "Holloway", "Prescott", "Winslow"))  # fmt: skip
    return f"{given} {family}", given, family


def payload_doc(language: str, rng: random.Random) -> Builder:
    keys = rng.sample(NUMERIC_KEYS, rng.randint(2, 6))
    data: dict[str, Any] = {k: scalar(rng, k) for k in keys}
    data.update(extra_fields(rng))
    pii: tuple[str, str, str, EntityType] | None = None
    if rng.random() < 1 / 3:
        full, given, family = _person_for(language, rng)
        if rng.random() < 0.6:
            pii = (rng.choice(NAME_KEYS), full, full, E.PERSON)
        else:
            mail = email_for(rng, given.split()[0].removesuffix("né"), family)
            pii = (rng.choice(EMAIL_KEYS), mail, "", E.EMAIL)
    b = Builder().add(rng.choice(PAYLOAD_INTRO[language]) + "\n")
    shape = rng.choice(("json", "json", "tool", "yaml", "log", "csv"))
    items = list(data.items())
    if pii:
        items.insert(rng.randrange(len(items) + 1), (pii[0], "\0PII\0"))

    def value(v: Any) -> str:
        return json.dumps(v)

    if shape in ("json", "tool"):
        indent = rng.choice((None, 2))
        if shape == "tool":
            name = rng.choice(("update_ticket", "get_order", "create_issue", "list_jobs",
                               "close_pr", "query_metrics", "bash", "http_request"))  # fmt: skip
            b.add(f'{{"type": "tool_use", "name": "{name}", "input": ')
        b.add("{" + ("\n" if indent else ""))
        for i, (k, v) in enumerate(items):
            sep = "," if i < len(items) - 1 else ""
            pad = "  " if indent else ("" if i == 0 else " ")
            b.add(f'{pad}"{k}": ')
            if v == "\0PII\0" and pii:
                b.add('"').gold(pii[1], pii[3], pii[2] or None).add('"')
            else:
                b.add(value(v))
            b.add(sep + ("\n" if indent else ""))
        b.add("}" + ("}" if shape == "tool" else ""))
    elif shape == "yaml":
        for k, v in items:
            b.add(f"{k}: ")
            if v == "\0PII\0" and pii:
                b.gold(pii[1], pii[3], pii[2] or None)
            else:
                b.add("null" if v is None else str(v).lower() if isinstance(v, bool) else str(v))
            b.add("\n")
    elif shape == "log":
        level = rng.choice(("INFO", "WARN", "DEBUG", "ERROR"))
        b.add(f"2026-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}T{rng.randint(0, 23):02d}:"
              f"{rng.randint(0, 59):02d}:{rng.randint(0, 59):02d}Z {level} ")  # fmt: skip
        for k, v in items:
            b.add(f"{k}=")
            if v == "\0PII\0" and pii:
                b.gold(pii[1], pii[3], pii[2] or None)
            else:
                b.add(json.dumps(v) if isinstance(v, str) else str(v))
            b.add(" ")
    else:  # csv
        b.add(",".join(k for k, _ in items) + "\n")
        for row in range(rng.randint(1, 3)):
            cells = []
            for k, v in items:
                if v == "\0PII\0":
                    cells.append(None)
                else:
                    cells.append(str(scalar(rng, k) if row and k in NUMERIC_KEYS else v))
            for i, cell in enumerate(cells):
                if cell is None and pii and row == 0:
                    b.gold(pii[1], pii[3], pii[2] or None)
                elif cell is None:
                    b.add("")
                else:
                    b.add(cell)
                b.add("," if i < len(cells) - 1 else "\n")
    outro = rng.choice(PAYLOAD_OUTRO[language]).replace("{k}", rng.choice(keys))
    if outro:
        b.add("\n" + outro)
    return b


# --- (c) agent text ---------------------------------------------------------------------------

HARNESSES = ("pi", "codex", "opencode", "claude", "aider", "goose")
EXECUTABLES = ("python3", "npm", "node", "git", "uv", "pytest", "make", "docker", "jq", "rg")
EPONYMS = (
    "Luhn", "Dijkstra", "Levenshtein", "Kalman", "Huffman", "Markov", "Bayes", "Fourier",
    "Gauss", "Euler", "Hamming", "Bloom", "Kruskal", "Prim", "Boyer-Moore", "Bellman-Ford",
)  # fmt: skip
SCOPES = ("acme-works", "lumen-labs", "quill-tools", "orbit-dev", "fable-kit", "nordwind-io")
PACKAGES = ("coding-agent", "cli", "sdk", "core", "mcp-server", "plugin-git")
FUNCS = ("parse_args", "load_config", "build_index", "flush", "retry_with_backoff", "to_dict",
         "validate", "render", "handleSubmit", "fetchUser", "mergeSorted", "normalize")  # fmt: skip

AGENT_PROSE = {
    "hu": (
        "A {h} harness a {x} parancsot futtatta, de a teszt elbukott.",
        "A {e}-algoritmus lassú nagy gráfokon, nézd meg a {f} függvényt.",
        "A {e}-ellenőrzés hibát jelez a 13. sorban.",
        "Telepítsd a @{s}/{h}-{p} csomagot, majd indítsd újra a {h} munkamenetet.",
        "A {f} visszatérési értéke false, ezért a {x} kilép 1-es kóddal.",
        "A {h} dokumentációja szerint a {x} -m kapcsoló kell.",
    ),
    "en": (
        "{h} ran `{x}` and the test failed on line {d}.",
        "Use {e}'s algorithm here; `{f}` is the bottleneck.",
        "The {e} check rejects the input at offset {d}.",
        "Install @{s}/{h}-{p}, then restart the {h} session.",
        "`{f}` returns false, so `{x}` exits with code 1.",
        "Per {h}'s docs, pass `-m` to `{x}`.",
    ),
    "de": (
        "{h} hat `{x}` ausgeführt, der Test schlägt in Zeile {d} fehl.",
        "Nimm hier den {e}-Algorithmus; `{f}` ist der Engpass.",
        "Die {e}-Prüfung lehnt die Eingabe an Position {d} ab.",
        "Installiere @{s}/{h}-{p} und starte die {h}-Sitzung neu.",
        "`{f}` liefert false, daher beendet sich `{x}` mit Code 1.",
        "Laut Doku von {h} braucht `{x}` den Schalter `-m`.",
    ),
}  # fmt: skip
AGENT_PERSON = {
    "hu": ("Kérlek, küldd el az összefoglalót {n}.", "A hibajegyet {n} rendeld hozzá."),
    "en": ("Send the summary to {n} when done.", "Assign the bug to {n}."),
    "de": ("Schick die Zusammenfassung an {n}.", "Weise den Fehler {n} zu."),
}
#: Hungarian case used by each AGENT_PERSON frame (dative, dative).
AGENT_PERSON_CASE = ("dat", "dat")


def code_block(rng: random.Random) -> str:
    f, x = rng.choice(FUNCS), rng.choice(EXECUTABLES)
    d, d2 = rng.randint(2, 4096), rng.randint(1, 999)
    kind = rng.randrange(5)
    if kind == 0:
        return (f"```python\ndef {f}(items, limit={d}):\n    seen = set()\n    for i, item in "
                f"enumerate(items):\n        if i >= limit:\n            return False\n"
                f"        seen.add(item)\n    return None\n```")  # fmt: skip
    if kind == 1:
        return (f"```js\nexport async function {f}(id) {{\n  const res = await fetch(`/api/v1/"
                f"items/${{id}}?page={d2}`);\n  if (res.status === 404) return null;\n"
                f"  return res.json();\n}}\n```")  # fmt: skip
    if kind == 2:
        return (f"```sh\ncd repo && {x} --version && {x} run build -- --port {d} "
                f"&& python3 -c 'print({d2})'\n```")  # fmt: skip
    if kind == 3:
        scope, pkg = rng.choice(SCOPES), rng.choice(PACKAGES)
        return (f"~/.local/share/fnm/lib/node_modules/@{scope}/{rng.choice(HARNESSES)}-{pkg}/"
                f"README.md\n$ ls -la\n-rw-r--r--  1 user  staff  {d}  Oct 12 09:{d2 % 60:02d}"
                f" {f}.py")  # fmt: skip
    return (f"{rng.choice(HARNESSES)} > tool: read_file path=src/{f}.ts lines={d2}-{d2 + 40}\n"
            f"{rng.choice(HARNESSES)} > tool: bash cmd=\"{x} test -k {f}\" exit=0 "
            f"duration_ms={d}")  # fmt: skip


def agent_doc(language: str, rng: random.Random) -> Builder:
    b = Builder()
    slots = {
        "h": rng.choice(HARNESSES), "x": rng.choice(EXECUTABLES), "e": rng.choice(EPONYMS),
        "f": rng.choice(FUNCS), "s": rng.choice(SCOPES), "p": rng.choice(PACKAGES),
        "d": str(rng.randint(2, 999)),
    }  # fmt: skip
    pieces = rng.sample(AGENT_PROSE[language], rng.randint(1, 3))
    for i, piece in enumerate(pieces):
        text = piece
        for k, v in slots.items():
            text = text.replace("{" + k + "}", v)
        b.add(text + "\n")
        if i == 0 or rng.random() < 0.5:
            b.add(code_block(rng) + "\n")
    if rng.random() < 0.25:
        k = rng.randrange(len(AGENT_PERSON[language]))
        full, _, _ = _person_for(language, rng)
        surface = hu_inflect(full, AGENT_PERSON_CASE[k]) if language == "hu" else full
        b.fill(AGENT_PERSON[language][k], {"n": (surface, E.PERSON, full)})
    return b


# --- generation -------------------------------------------------------------------------------

BUILDERS: dict[str, Callable[[str, random.Random], Builder]] = {
    "names": lambda lang, rng: {"hu": hu_names_doc, "pl": pl_names_doc, "de": de_names_doc}[lang](
        rng
    ),
    "payload": payload_doc,
    "agent": agent_doc,
}


def eval_texts(dirs: Iterable[Path] = EVAL_DIRS) -> str:
    """Every evaluation text, joined: what a generated full name must not occur in."""
    texts: list[str] = []
    for root in dirs:
        if not root.exists():
            continue
        for path in sorted(root.rglob("*.jsonl")):
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    try:
                        texts.append(json.loads(line).get("text", ""))
                    except (json.JSONDecodeError, AttributeError):
                        continue
    return "\n".join(texts)


def generate(part: str, language: str, n: int, seed: int, blob: str, split: str) -> list[Document]:
    """``n`` documents; one naming a person whose full name occurs in ``blob`` is redrawn."""
    docs: list[Document] = []
    rng = random.Random(f"{seed}-{part}-{language}")
    for index in range(n):
        for _attempt in range(200):
            b = BUILDERS[part](language, rng)
            if not any(name in blob for name in b.names):
                break
        else:  # pragma: no cover - the name lists are far larger than the eval sets' overlap
            raise RuntimeError(f"{part} {language} {index}: every draw names an eval person")
        doc_id = f"{language}-v33-{part}-{split}-{index:05d}"
        docs.append(b.document(doc_id, language, {"source": "v33-addon", "part": part}))
    return docs


def addon(out: Path, blob: str) -> dict[str, Any]:
    out.mkdir(parents=True, exist_ok=True)
    stats: dict[str, Any] = {}
    for part, language, n_train, n_dev in PLAN:
        for split, n, seed in (("train", n_train, SEED), ("dev", n_dev, DEV_SEED)):
            docs = generate(part, language, n, seed, blob, split)
            path = out / f"{language}-v33-{part}-{split}.jsonl"
            write_fixtures(path, docs)
            types = Counter(s.entity_type.value for d in docs for s in d.spans)
            stats[path.name] = {
                "documents": len(docs),
                "pii_free_documents": sum(1 for d in docs if not d.spans),
                "gold_spans": dict(sorted(types.items())),
                "distinct_full_names": len({nm for d in docs for nm in d.meta["names"]}),
            }
    return stats


def name_overlap(paths: Sequence[Path], blob: str) -> int:
    """Generated full names that occur in an evaluation text (must be 0)."""
    names = {nm for d in load_fixtures(list(paths)) for nm in d.meta.get("names", [])}
    return sum(1 for nm in names if nm in blob)


def replay(final: Path, out: Path, seed: int = SEED) -> dict[str, int]:
    """Seeded sample of the v3.1-B mix files into ``out`` (same relative paths)."""
    counts: dict[str, int] = {}
    for rel, n in REPLAY.items():
        docs = load_fixtures([final / rel])
        rng = random.Random(f"{seed}-replay-{rel}")
        chosen = sorted(rng.sample(range(len(docs)), min(n, len(docs))))
        path = out / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        write_fixtures(path, [docs[i] for i in chosen])
        counts[rel] = len(chosen)
    return counts


#: Sets whose closest pair to the add-on is reported (the gates and the selection set).
MAX_J_SETS = {
    "agent-traffic-dev": [f"eval/synthetic/dev/{lang}-agent-traffic-dev.jsonl" for lang in
                          ("hu", "en", "de")],
    "smoke": [f"eval/fixtures/{lang}-smoke.jsonl" for lang in ("hu", "en", "de")],
    "inflection": ["eval/fixtures/hu-inflection.jsonl"],
    "agent-text": sorted(str(p) for p in Path("eval/fixtures/agent-text").glob("*.jsonl")),
}  # fmt: skip


def decontam_report(addon_dir: Path, replay_dir: Path) -> dict[str, Any]:
    """decontam.py's gate over every add-on and replay file, plus max J per gate set."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import decontam

    index = decontam.eval_corpus()
    report = decontam.Report()
    addon_docs: list[Document] = []
    for path in [*sorted(addon_dir.glob("*.jsonl")), *sorted(replay_dir.rglob("*.jsonl"))]:
        docs = load_fixtures([path])
        decontam.gate(docs, index, name=str(path), report=report)
        if path.parent == addon_dir:
            addon_docs.extend(docs)
    out = report.to_dict(index=index)
    out["addon_max_jaccard"] = {
        name: decontam.max_jaccard(addon_docs, load_fixtures(paths))
        for name, paths in MAX_J_SETS.items()
    }
    return out


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    a = sub.add_parser("addon")
    a.add_argument("--out", type=Path, default=Path("eval/generated/v33-addon"))
    a.add_argument("--json", type=Path)
    r = sub.add_parser("replay")
    r.add_argument("--final", type=Path, default=Path("eval/generated/v31-final"))
    r.add_argument("--out", type=Path, default=Path("eval/generated/v33-replay"))
    r.add_argument("--json", type=Path)
    c = sub.add_parser("decontam")
    c.add_argument("--addon", type=Path, default=Path("eval/generated/v33-addon"))
    c.add_argument("--replay", type=Path, default=Path("eval/generated/v33-replay"))
    c.add_argument("--json", type=Path)
    args = parser.parse_args(argv)
    if args.command == "decontam":
        report = decontam_report(args.addon, args.replay)
    elif args.command == "addon":
        blob = eval_texts()
        stats = addon(args.out, blob)
        overlap = name_overlap(sorted(args.out.glob("*.jsonl")), blob)
        if overlap:
            raise SystemExit(f"{overlap} generated full names occur in an evaluation text")
        report: dict[str, Any] = {"seed": SEED, "dev_seed": DEV_SEED, "files": stats,
                                  "eval_name_overlap": overlap}  # fmt: skip
    else:
        report = {"seed": SEED, "files": replay(args.final, args.out)}
    print(json.dumps(report, indent=2, ensure_ascii=False))
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", "utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
