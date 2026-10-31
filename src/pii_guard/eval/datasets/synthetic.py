"""Seeded synthetic agent traffic: what an AI gateway actually sees, with gold from construction.

```
python -m pii_guard.eval.datasets fetch agent-traffic        # writes eval/synthetic/
python -m pii_guard.eval.datasets check agent-traffic        # rebuild, compare, write nothing
```

Every document is assembled from templates and fictional values (:mod:`pii_guard.eval.identities`
for Hungarian and English people and companies, :class:`GermanIdentities` here), so the gold
spans are the offsets where values were inserted: **no model labels anything**. Same seed, same
bytes. Nothing here is a real person: names are common first and last names combined at
random, e-mail domains are the reserved ``example.*`` ones, and checksummed identifiers are
valid in form but issued to nobody.

**Shapes** (``meta.shape``): an OpenAI tool call (arguments as a JSON string inside JSON), a
nested JSON record, YAML, CSV, log lines, code with secrets and e-mail addresses, an e-mail
thread with a quoted reply, a multi-turn chat transcript, and (Hungarian) inflected names in
prose (``Kovács Annának``).

**Checksums.** Tax IDs, TAJ numbers, Steuer-IDs, IBANs and card numbers pass their check
digits, except a controlled share (:data:`INVALID_SHARE`) altered so they fail; the gold spans
of those are listed in ``meta.checksum`` with ``valid: false`` so the report can split leak by
validity (as LAB-1201 does for the public sets). A mistyped identifier is still personal data,
so they stay in the headline leak rate.

**Adversarial perturbations** (``meta.perturbed``, :data:`PERTURB_SHARE` of the values):
spaced or dotted digits, homoglyphs (Cyrillic look-alike letters), zero-width characters
inside a value, a value broken over two lines, and leetspeak e-mail addresses
(``anna [at] example [dot] com``). The gold span covers the perturbed surface.

**Hard negatives**, never labelled: order and invoice numbers, SKUs, tracking and request ids,
amounts, dates that aren't birth dates, and the names of large public companies in context
(``Siemens``, ``OTP Bank``). A masked span on them is over-masking. Secrets in code (API keys)
are ignore regions (``meta.ignore``): pii-guard's text policy has no secret type.

**Splits.** ``test`` (the committed ``eval/synthetic/<lang>-agent-traffic.jsonl``) and ``dev``
(``eval/synthetic/dev/<lang>-agent-traffic-dev.jsonl``) are drawn from different seeds; a test
asserts no document text is shared. Tune on ``dev`` only.
"""

# Seeded synthetic data: the standard PRNG is the point.
# ruff: noqa: S311

from __future__ import annotations

import copy
import datetime as dt
import random
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from pii_guard.eval.datasets.spec import Dataset
from pii_guard.eval.datasets.synthetic_primitives import (
    Built as Built,
)
from pii_guard.eval.datasets.synthetic_primitives import (
    Gold as Gold,
)
from pii_guard.eval.datasets.synthetic_primitives import (
    Piece as Piece,
)
from pii_guard.eval.datasets.synthetic_primitives import (
    Secret as Secret,
)
from pii_guard.eval.datasets.synthetic_primitives import (
    _luhn_digit as _luhn_digit,
)
from pii_guard.eval.datasets.synthetic_primitives import (
    _shift as _shift,
)
from pii_guard.eval.datasets.synthetic_primitives import (
    break_checksum as break_checksum,
)
from pii_guard.eval.datasets.synthetic_primitives import (
    card_number as card_number,
)
from pii_guard.eval.datasets.synthetic_primitives import (
    escape_built as escape_built,
)
from pii_guard.eval.datasets.synthetic_primitives import (
    json_string as json_string,
)
from pii_guard.eval.datasets.synthetic_primitives import (
    steuer_id as steuer_id,
)
from pii_guard.eval.datasets.synthetic_primitives import (
    to_json as to_json,
)
from pii_guard.eval.fixtures import Document, parse_document
from pii_guard.eval.identities import email_address, iban, identity_generator
from pii_guard.types import EntityType
from pii_guard.vault.inflection import inflection_for, restore

__all__ = [
    "DEFAULT_SEED",
    "DEV_SEED",
    "GENERATOR",
    "INVALID_SHARE",
    "LANGUAGES",
    "PERTURB_SHARE",
    "SHAPES",
    "build_split",
    "document",
]

GENERATOR = "pii-guard synthetic agent-traffic v1 (LAB-1226)"
LANGUAGES = ("hu", "en", "de")
DEFAULT_SEED = 1226
DEV_SEED = 61226
TEST_SIZE = 330
DEV_SIZE = 100
INVALID_SHARE = 0.15
PERTURB_SHARE = 0.18
OUT_DIR = Path("eval/synthetic")

E = EntityType


_DE_GIVEN_F = (
    "Anna", "Julia", "Laura", "Sophie", "Katharina", "Lena", "Sarah", "Lisa", "Hannah", "Marie",
    "Johanna", "Franziska", "Sabine", "Petra", "Claudia", "Monika", "Ursula", "Birgit",
)  # fmt: skip
_DE_GIVEN_M = (
    "Lukas", "Jonas", "Felix", "Maximilian", "Paul", "Leon", "Tobias", "Florian", "Stefan",
    "Thomas", "Andreas", "Michael", "Jürgen", "Klaus", "Matthias", "Sebastian", "Jan", "Tim",
)  # fmt: skip
_DE_FAMILY = (
    "Müller", "Schmidt", "Schneider", "Fischer", "Weber", "Meyer", "Wagner", "Becker",
    "Schulz", "Hoffmann", "Koch", "Richter", "Klein", "Wolf", "Schröder", "Neumann",
    "Schwarz", "Braun", "Zimmermann", "Hartmann", "Krüger", "Lange", "Werner", "Lehmann",
)  # fmt: skip
_DE_TOWNS = (
    ("Berlin", "10"), ("Hamburg", "20"), ("München", "80"), ("Köln", "50"), ("Leipzig", "04"),
    ("Dresden", "01"), ("Hannover", "30"), ("Nürnberg", "90"), ("Bremen", "28"),
    ("Freiburg im Breisgau", "79"), ("Kassel", "34"), ("Augsburg", "86"),
)  # fmt: skip
_DE_STREETS = (
    "Hauptstraße", "Schulstraße", "Gartenstraße", "Bahnhofstraße", "Lindenweg", "Birkenallee",
    "Am Markt", "Kirchgasse", "Bergstraße", "Rosenweg", "Mühlenweg", "Waldstraße",
)  # fmt: skip
_DE_COMPANY_A = ("Nordlicht", "Weiden", "Elbtal", "Kranich", "Sonnenhof", "Bergwerk", "Lindner")
_DE_COMPANY_B = ("Logistik GmbH", "Haustechnik GmbH", "Software UG", "Baustoffe KG", "Druck GmbH")


@dataclass(frozen=True, slots=True)
class Person:
    """The fields a template may use. Language-specific ones are ``None`` elsewhere."""

    given: str
    family: str
    name: str
    email: str
    phone: str
    address: str
    date_of_birth: str
    bank_account: str
    id_document: str
    tax_id: str | None = None
    taj: str | None = None
    steuer_id: str | None = None

    def __repr__(self) -> str:
        return "Person(<redacted>)"


class GermanIdentities:
    """German people (given name first), addresses, phones, IBANs, Steuer-IDs, companies."""

    def __init__(self, rng: random.Random) -> None:
        self.rng = rng

    def person(self) -> Person:
        rng = self.rng
        given = rng.choice(_DE_GIVEN_F + _DE_GIVEN_M)
        family = rng.choice(_DE_FAMILY)
        born = dt.date(1945, 1, 1) + dt.timedelta(days=rng.randint(0, 21900))
        town, area = rng.choice(_DE_TOWNS)
        address = (
            f"{rng.choice(_DE_STREETS)} {rng.randint(1, 140)}, {area}{rng.randint(100, 999)} {town}"
        )
        bban = "".join(str(rng.randrange(10)) for _ in range(18))
        phone = rng.choice(
            [
                f"+49 30 {rng.randint(1000000, 9999999)}",
                f"0{rng.randint(151, 179)} {rng.randint(1000000, 99999999)}",
                f"+49 {rng.randint(151, 179)} {rng.randint(1000000, 9999999)}",
                f"089 {rng.randint(100000, 9999999)}",
            ]
        )
        return Person(
            given=given,
            family=family,
            name=f"{given} {family}",
            email=email_address(rng, given, family, born.year),
            phone=phone,
            address=address,
            date_of_birth=rng.choice(
                [f"{born.day:02d}.{born.month:02d}.{born.year}", born.isoformat()]
            ),
            bank_account=iban("DE", bban),
            id_document="".join(rng.choice("CFGHJKLMNPRTVWXYZ0123456789") for _ in range(9)),
            steuer_id=steuer_id(rng),
        )

    def company(self) -> str:
        return f"{self.rng.choice(_DE_COMPANY_A)} {self.rng.choice(_DE_COMPANY_B)}"


def make_person(language: str, rng: random.Random) -> tuple[Person, str]:
    """A fictional person and a fictional company name for ``language``."""
    if language == "de":
        g = GermanIdentities(rng)
        return g.person(), g.company()
    ids = identity_generator(language, rng)
    p = ids.person()
    company = ids.company().org_name
    return (
        Person(
            given=p.given,
            family=p.family,
            name=p.name,
            email=p.email,
            phone=p.phone,
            address=p.address,
            date_of_birth=p.date_of_birth,
            bank_account=p.bank_account,
            id_document=p.id_document,
            tax_id=p.tax_id,
            taj=p.taj,
        ),
        company,
    )


#: Public companies: kept in context, never labelled (hard negatives).
PUBLIC_COMPANIES = {
    "hu": ("OTP Bank", "MOL", "Magyar Telekom", "Richter Gedeon", "MÁV", "Wizz Air"),
    "en": ("Microsoft", "Barclays", "Tesco", "Vodafone", "British Airways", "Amazon"),
    "de": ("Siemens", "Deutsche Bahn", "Allianz", "SAP", "Lufthansa", "Deutsche Telekom"),
}


class Values:
    """Gold values for one document: checksum validity and perturbations drawn per value."""

    def __init__(self, language: str, rng: random.Random) -> None:
        self.language = language
        self.rng = rng
        self.person, self.company = make_person(language, rng)
        self.other, _ = make_person(language, rng)
        #: A value may be broken over two lines only where a newline can't break the format.
        self.multiline = False

    def with_person(self, who: Person) -> Values:
        """The same document's draws for another person (a CSV row)."""
        other = copy.copy(self)
        other.person = who
        return other

    def _gold(self, entity_type: EntityType, text: str, *, checksum: bool = False) -> Gold:
        valid: bool | None = None
        if checksum:
            valid = self.rng.random() >= INVALID_SHARE
            if not valid:
                text = break_checksum(self.rng, text)
        perturbed = None
        if self.rng.random() < PERTURB_SHARE:
            text, perturbed = perturb(self.rng, entity_type, text, multiline=self.multiline)
        return Gold(entity_type, text, valid, perturbed)

    def name(self, who: Person | None = None) -> Gold:
        return self._gold(E.PERSON, (who or self.person).name)

    def email(self, who: Person | None = None) -> Gold:
        return self._gold(E.EMAIL, (who or self.person).email)

    def phone(self) -> Gold:
        return self._gold(E.PHONE, self.person.phone)

    def address(self) -> Gold:
        return Gold(E.ADDRESS, self.person.address)

    def dob(self) -> Gold:
        return Gold(E.DATE_OF_BIRTH, self.person.date_of_birth)

    def iban(self) -> Gold:
        account = self.person.bank_account
        return self._gold(E.BANK_ACCOUNT, account, checksum=account[:2].isalpha())

    def card(self) -> Gold:
        return self._gold(E.BANK_ACCOUNT, card_number(self.rng), checksum=True)

    def national_id(self) -> Gold:
        """The language's checksummed personal number (adóazonosító, Steuer-ID) or an ID."""
        p = self.person
        if self.language == "hu" and p.tax_id:
            return self._gold(E.NATIONAL_ID_HU_TAX, p.tax_id, checksum=True)
        if self.language == "de" and p.steuer_id:
            return self._gold(E.ID_DOCUMENT, p.steuer_id, checksum=True)
        return self._gold(E.ID_DOCUMENT, p.id_document)

    def taj(self) -> Gold:
        if self.language == "hu" and self.person.taj:
            return self._gold(E.NATIONAL_ID_HU_TAJ, self.person.taj, checksum=True)
        return self.national_id()

    def org(self) -> Gold:
        return Gold(E.ORGANIZATION, self.company)

    def public_company(self) -> str:
        return self.rng.choice(PUBLIC_COMPANIES[self.language])


_HOMOGLYPHS = {  # Latin -> Cyrillic look-alike
    "a": "\u0430",
    "e": "\u0435",
    "o": "\u043e",
    "p": "\u0440",
    "c": "\u0441",
    "x": "\u0445",
    "i": "\u0456",
}
_ZW = "\u200b"


def perturb(
    rng: random.Random, entity_type: EntityType, text: str, *, multiline: bool = False
) -> tuple[str, str | None]:
    """One adversarial rewrite of ``text`` that a person would still read as the value."""
    digits = sum(ch.isdigit() for ch in text)
    options: list[str] = ["zero-width"]
    if digits >= 6:
        options += ["spaced-digits", "dotted-digits"]
    if entity_type is E.EMAIL:
        options += ["leetspeak-email", "homoglyph"]
    if entity_type is E.PERSON:
        options += ["homoglyph", "line-break"] if multiline and " " in text else ["homoglyph"]
    kind = rng.choice(options)
    if kind == "spaced-digits":
        compact = "".join(ch for ch in text if ch.isalnum())
        return " ".join(compact), kind
    if kind == "dotted-digits":
        compact = "".join(ch for ch in text if ch.isalnum())
        return ".".join(compact[i : i + 3] for i in range(0, len(compact), 3)), kind
    if kind == "leetspeak-email":
        local, _, domain = text.partition("@")
        local = local.translate(str.maketrans("oeai", "0341"))
        return f"{local} [at] {domain.replace('.', ' [dot] ')}", kind
    if kind == "homoglyph":
        positions = [i for i, ch in enumerate(text) if ch in _HOMOGLYPHS]
        if positions:
            i = rng.choice(positions)
            return text[:i] + _HOMOGLYPHS[text[i]] + text[i + 1 :], kind
        kind = "zero-width"
    if kind == "line-break" and " " in text:
        i = text.index(" ")
        return text[:i] + "\n" + text[i + 1 :], kind
    mid = max(1, len(text) // 2)
    while mid < len(text) - 1 and not text[mid - 1].isalnum():
        mid += 1
    return text[:mid] + _ZW + text[mid:], "zero-width"


# --- Negatives ------------------------------------------------------------------------------


def order_number(rng: random.Random) -> str:
    return rng.choice(
        [
            f"ORD-{rng.randint(2024, 2026)}-{rng.randint(100000, 999999)}",
            str(rng.randint(10**9, 10**12)),
            f"SO{rng.randint(1000000, 9999999)}",
        ]
    )


def sku(rng: random.Random) -> str:
    letters = "ABCDEFGHKLMNPRSTXZ"
    return f"{rng.choice(letters)}{rng.choice(letters)}-{rng.randint(1000, 99999)}"


def request_id(rng: random.Random) -> str:
    return "".join(rng.choice("0123456789abcdef") for _ in range(16))


def amount(rng: random.Random, language: str, *, plain: bool = False) -> str:
    whole, cents = rng.randint(3, 98000), rng.randint(0, 99)
    if plain:  # a CSV cell: no thousands separator, a decimal point
        return f"{whole}.{cents:02d}"
    if language == "hu":
        return f"{whole * 10:,} Ft".replace(",", " ")
    if language == "de":
        return (
            f"{whole:,},{cents:02d} €".replace(",", ".", 1)
            if whole >= 1000
            else f"{whole},{cents:02d} €"
        )
    return f"£{whole:,}.{cents:02d}"


def some_date(rng: random.Random, language: str) -> str:
    day = dt.date(2026, 1, 1) + dt.timedelta(days=rng.randint(0, 360))
    if language == "hu":
        return f"{day.year}.{day.month:02d}.{day.day:02d}."
    if language == "de":
        return f"{day.day:02d}.{day.month:02d}.{day.year}"
    return day.isoformat()


def api_key(rng: random.Random) -> Secret:
    return Secret(
        "sk-test-" + "".join(rng.choice("abcdefghijkmnopqrstuvwxyz0123456789") for _ in range(32))
    )


# --- Phrases --------------------------------------------------------------------------------

PHRASES: dict[str, dict[str, str]] = {
    "hu": {
        "tool_ask": "Küldd el a számlát az ügyfélnek, és rögzítsd a CRM-ben.",
        "note": "Ügyfél visszahívást kért, a szállítás késik.",
        "subject": "Re: Rendelés módosítása",
        "greeting": "Kedves",
        "body": "A rendelését módosítottuk, az új szállítási dátum",
        "thanks": "Köszönöm,",
        "wrote": "írta:",
        "user1": "Szia! Frissíteni szeretném a számlázási adataimat.",
        "bot1": "Persze, kérem adja meg az új adatokat.",
        "user2": "A nevem",
        "user2b": ", az e-mail címem",
        "user2c": ". A bankszámlaszámom",
        "bot2": "Köszönöm, rögzítettem. A rendelésszáma továbbra is",
        "born": "született",
        "log_login": "felhasználó belépett",
        "log_pay": "fizetés jóváhagyva",
        "csv_head": "nev,email,telefon,adoazonosito,rendeles,osszeg",
        "partner": "partnerünk",
    },
    "en": {
        "tool_ask": "Send the invoice to the customer and log it in the CRM.",
        "note": "Customer asked for a call back, delivery is late.",
        "subject": "Re: Change to your order",
        "greeting": "Dear",
        "body": "We have updated your order; the new delivery date is",
        "thanks": "Thanks,",
        "wrote": "wrote:",
        "user1": "Hi! I'd like to update my billing details.",
        "bot1": "Of course, please share the new details.",
        "user2": "My name is",
        "user2b": ", my email is",
        "user2c": ". My account number is",
        "bot2": "Thanks, saved. Your order number is still",
        "born": "born",
        "log_login": "user logged in",
        "log_pay": "payment approved",
        "csv_head": "name,email,phone,national_id,order,amount",
        "partner": "our partner",
    },
    "de": {
        "tool_ask": "Schick die Rechnung an den Kunden und trag sie im CRM ein.",
        "note": "Kunde bittet um Rückruf, die Lieferung verspätet sich.",
        "subject": "AW: Änderung Ihrer Bestellung",
        "greeting": "Sehr geehrte/r",
        "body": "wir haben Ihre Bestellung geändert, neuer Liefertermin ist der",
        "thanks": "Danke,",
        "wrote": "schrieb:",
        "user1": "Hallo! Ich möchte meine Rechnungsdaten aktualisieren.",
        "bot1": "Gern, bitte nennen Sie die neuen Daten.",
        "user2": "Ich heiße",
        "user2b": ", meine E-Mail ist",
        "user2c": ". Meine IBAN ist",
        "bot2": "Danke, gespeichert. Ihre Bestellnummer bleibt",
        "born": "geboren am",
        "log_login": "Benutzer angemeldet",
        "log_pay": "Zahlung freigegeben",
        "csv_head": "name,email,telefon,steuer_id,bestellung,betrag",
        "partner": "unser Partner",
    },
}


# --- Shapes ---------------------------------------------------------------------------------

Shape = Callable[[Values, random.Random], Built]


def tool_call(v: Values, rng: random.Random) -> Built:
    lang = v.language
    args = to_json(
        {
            "customer": {"name": v.name(), "email": v.email(), "phone": v.phone()},
            "invoice": {"order": order_number(rng), "amount": amount(rng, lang), "iban": v.iban()},
            "vendor": v.public_company(),
        },
        indent=None,
    )
    message = {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": "call_" + request_id(rng),
                "type": "function",
                "function": {"name": "send_invoice", "arguments": escape_built(args)},
            }
        ],
    }
    body = {
        "model": "gpt-4o-mini",
        "messages": [{"role": "user", "content": PHRASES[lang]["tool_ask"]}, message],
    }
    return to_json(body, indent=rng.choice([None, 2]))


def nested_json(v: Values, rng: random.Random) -> Built:
    lang = v.language
    record = {
        "id": request_id(rng),
        "contact": {
            "full_name": v.name(),
            "born": v.dob(),
            "address": v.address(),
            "ids": {"national": v.national_id()},
        },
        "accounts": [{"iban": v.iban(), "opened": some_date(rng, lang)}],
        "employer": v.org(),
        "notes": PHRASES[lang]["note"],
        "sku": sku(rng),
    }
    return to_json(record, indent=2)


def yaml_doc(v: Values, rng: random.Random) -> Built:
    lang = v.language
    b = Built()
    b.extend(
        [
            f"ticket: {order_number(rng)}\n",
            f"created: {some_date(rng, lang)}\n",
            "requester:\n  name: ",
            v.name(),
            "\n  email: ",
            v.email(),
            '\n  phone: "',
            v.phone(),
            '"\nbilling:\n  card: "',
            v.card(),
            '"\n  amount: ',
            amount(rng, lang),
            f"\n  vendor: {v.public_company()}\n",
            f"items:\n  - sku: {sku(rng)}\n    qty: {rng.randint(1, 9)}\n",
        ]
    )
    return b


def csv_doc(v: Values, rng: random.Random) -> Built:
    lang = v.language
    b = Built(PHRASES[lang]["csv_head"] + "\n")
    for i in range(rng.randint(2, 4)):
        who = v.person if i == 0 else make_person(lang, rng)[0]
        sub = v.with_person(who)
        name = sub.name()
        quoted = "," in name.text or rng.random() < 0.3
        b.extend(
            [
                *(['"', name, '"'] if quoted else [name]),
                ",",
                sub.email(),
                ",",
                sub.phone(),
                ",",
                sub.national_id(),
                ",",
                order_number(rng),
                ",",
                amount(rng, lang, plain=True),
                "\n",
            ]
        )
    return b


def log_lines(v: Values, rng: random.Random) -> Built:
    lang = v.language
    p = PHRASES[lang]
    stamp = f"2026-10-{rng.randint(1, 27):02d}T{rng.randint(0, 23):02d}:{rng.randint(0, 59):02d}"
    b = Built()
    b.extend(
        [
            f"{stamp}:01Z INFO  auth  req={request_id(rng)} {p['log_login']} email=",
            v.email(),
            "\n",
            f'{stamp}:02Z DEBUG crm   req={request_id(rng)} lookup name="',
            v.name(),
            '" phone=',
            v.phone(),
            "\n",
            f"{stamp}:04Z INFO  pay   req={request_id(rng)} {p['log_pay']} "
            f'order={order_number(rng)} amount="{amount(rng, lang)}" iban=',
            v.iban(),
            "\n",
            f"{stamp}:05Z WARN  ship  req={request_id(rng)} sku={sku(rng)} "
            f"carrier={v.public_company()}\n",
        ]
    )
    return b


def code_doc(v: Values, rng: random.Random) -> Built:
    b = Built()
    b.extend(
        [
            "import os\n\n",
            'ADMIN_EMAIL = "',
            v.email(),
            '"\n',
            'OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "',
            api_key(rng),
            '")\n\n\n',
            "def notify(order_id: str) -> None:\n",
            f'    """Order {order_number(rng)} escalation; owner: ',
            v.name(),
            '."""\n',
            '    send_mail(to=ADMIN_EMAIL, cc="',
            v.email(v.other),
            '", subject=order_id)\n',
            f"    # SKU {sku(rng)}, see the {v.public_company()} integration\n",
        ]
    )
    return b


def email_thread(v: Values, rng: random.Random) -> Built:
    lang = v.language
    v.multiline = True
    p = PHRASES[lang]
    b = Built()
    b.extend(
        [
            "From: ",
            v.name(v.other),
            " <",
            v.email(v.other),
            ">\n",
            "To: ",
            v.name(),
            " <",
            v.email(),
            ">\n",
            f"Subject: {p['subject']} {order_number(rng)}\n\n",
            f"{p['greeting']} ",
            v.name(),
            ",\n\n",
            f"{p['body']} {some_date(rng, lang)}.\n\n{p['thanks']}\n",
            v.name(v.other),
            "\n",
            "\n> ",
            v.name(),
            f" {p['wrote']}\n> ",
            v.phone(),
            " / ",
            v.address(),
            "\n",
        ]
    )
    return b


def chat(v: Values, rng: random.Random) -> Built:
    lang = v.language
    p = PHRASES[lang]
    turns: list[tuple[str, list[Piece]]] = [
        ("user", [p["user1"]]),
        ("assistant", [p["bot1"]]),
        (
            "user",
            [
                f"{p['user2']} ",
                v.name(),
                f" ({p['born']} ",
                v.dob(),
                f"){p['user2b']} ",
                v.email(),
                f"{p['user2c']} ",
                v.iban(),
                ".",
            ],
        ),
        ("assistant", [f"{p['bot2']} {order_number(rng)}."]),
    ]
    if rng.random() < 0.5:
        return to_json({"messages": [{"role": r, "content": c} for r, c in turns]}, indent=2)
    b = Built()
    for role, content in turns:
        b.add(f"{role.capitalize()}: ")
        b.extend(content)
        b.add("\n")
    return b


_HU_INFLECTED = (
    ("Átutaltuk a díjat ", "nak/nek", "."),
    ("Holnap egyeztetünk ", "val/vel", " a szerződésről."),
    ("Levelet kaptunk ", "tól/től", " a TAJ-számáról."),
    ("A jegyzőkönyv ", "ról/ről", " szól."),
)


def _harmony(name: str, pair: str) -> str:
    """The case ending of ``pair`` (``back/front``) in the vowel harmony of ``name``.

    ``i``/``í`` are neutral: the vowel before them decides (``Dávid`` -> ``Dávidnak``,
    ``Emil`` -> ``Emilnek``); a name with only neutral vowels is front (``Kitti`` -> ``Kittinek``).
    """
    back, front = pair.split("/")
    vowels = [ch for ch in name.lower() if ch in "aáoóuúeéöőüű"]
    return back if vowels and vowels[-1] in "aáoóuú" else front


def inflected(v: Values, rng: random.Random) -> Built:
    """Hungarian prose with a name in several cases; other languages get a plain message."""
    lang = v.language
    if lang != "hu":
        return prose_note(v, rng)
    v.multiline = True
    matcher = inflection_for("hu")
    name = v.person.name
    b = Built()
    for before, pair, after in rng.sample(_HU_INFLECTED, 3):
        surface = restore(matcher, name, _harmony(name, pair), E.PERSON)
        b.extend([before, Gold(E.PERSON, surface), after, " "])
    b.extend(
        [
            "TAJ: ",
            v.taj(),
            ", adóazonosító: ",
            v.national_id(),
            ". ",
            f"Rendelésszám: {order_number(rng)}, összeg: {amount(rng, lang)}, "
            f"{PHRASES[lang]['partner']}: {v.public_company()}.",
        ]
    )
    return b


_NOTE = {
    "en": (
        "Call note: spoke to ",
        "; ",
        "'s new address is ",
        ". Reach them on ",
        ". Refund the order to card ",
        ", not to the ",
        " account. Ticket ",
    ),
    "de": (
        "Gesprächsnotiz: mit ",
        " telefoniert; die neue Anschrift von ",
        " ist ",
        ". Erreichbar unter ",
        ". Erstattung auf Karte ",
        ", nicht auf das ",
        "-Konto. Ticket ",
    ),
}


def prose_note(v: Values, rng: random.Random) -> Built:
    """A free-text support note (en, de): names, an address, a card, a public company."""
    v.multiline = True
    a, b_, c, d, e, f, g = _NOTE[v.language]
    b = Built()
    b.extend(
        [
            a,
            v.name(),
            b_,
            v.name(),
            c,
            v.address(),
            d,
            v.phone(),
            e,
            v.card(),
            f,
            v.public_company(),
            g,
            f"{order_number(rng)}, {amount(rng, v.language)}.",
        ]
    )
    return b


SHAPES: dict[str, Shape] = {
    "tool-call-json": tool_call,
    "nested-json": nested_json,
    "yaml": yaml_doc,
    "csv": csv_doc,
    "log-lines": log_lines,
    "code": code_doc,
    "email-thread": email_thread,
    "chat": chat,
    "inflected-names": inflected,  # prose_note for en and de
}


# --- Documents ------------------------------------------------------------------------------


def document(language: str, index: int, *, seed: int, split: str) -> Document:
    """One synthetic document; same arguments, same document."""
    rng = random.Random(f"pii-guard-agent-traffic/{seed}/{language}/{index}")
    shape = list(SHAPES)[index % len(SHAPES)]
    v = Values(language, rng)
    built = SHAPES[shape](v, rng)
    if shape == "inflected-names" and language != "hu":
        shape = "prose-note"
    name = "agent-traffic" if split == "test" else "agent-traffic-dev"
    doc_id = f"{language}-{name}-{index:04d}"
    record = {
        "id": doc_id,
        "language": language,
        "text": built.text,
        "spans": [
            {"start": s, "end": e, "entity_type": g.entity_type.value} for s, e, g in built.spans
        ],
        "meta": {
            "kind": "synthetic-agent-traffic",
            "source": "synthetic",
            "generator": GENERATOR,
            "seed": seed,
            "split": split,
            "shape": shape,
            "checksum": [
                {"start": s, "end": e, "valid": g.valid}
                for s, e, g in built.spans
                if g.valid is not None
            ],
            "perturbed": [
                {"start": s, "end": e, "kind": g.perturbed}
                for s, e, g in built.spans
                if g.perturbed
            ],
            "ignore": [{"start": s, "end": e, "label": lab} for s, e, lab in built.ignore],
        },
    }
    return parse_document(record, where=doc_id)


def build_split(split: str, sizes: Mapping[str, int] | None = None) -> dict[str, list[Document]]:
    """Every language's documents for ``split`` (``test`` or ``dev``)."""
    seed = DEFAULT_SEED if split == "test" else DEV_SEED
    n = TEST_SIZE if split == "test" else DEV_SIZE
    return {
        lang: [document(lang, i, seed=seed, split=split) for i in range((sizes or {}).get(lang, n))]
        for lang in LANGUAGES
    }


def split_paths(split: str) -> list[Path]:
    if split == "test":
        return [OUT_DIR / f"{lang}-agent-traffic.jsonl" for lang in LANGUAGES]
    return [OUT_DIR / "dev" / f"{lang}-agent-traffic-dev.jsonl" for lang in LANGUAGES]


def _dataset(split: str) -> Dataset:
    name = "agent-traffic" if split == "test" else "agent-traffic-dev"
    return Dataset(
        name=name,
        title="pii-guard synthetic agent traffic" + ("" if split == "test" else " (dev)"),
        homepage="https://github.com/watt-mind/pii-guard/blob/develop/docs/datasets.md",
        revision=GENERATOR,
        license="Apache-2.0",
        license_url="https://www.apache.org/licenses/LICENSE-2.0",
        attribution="pii-guard contributors",
        languages=LANGUAGES,
        source_split=split,
        split="test" if split == "test" else "dev",
        synthetic=True,
        commit_rows=True,
        description="tool-call JSON, YAML, CSV, logs, code, e-mail threads, chat, inflected names",
        sample={lang: TEST_SIZE if split == "test" else DEV_SIZE for lang in LANGUAGES},
        seed=DEFAULT_SEED if split == "test" else DEV_SEED,
        external=tuple(str(p) for p in split_paths(split)),
        builder=lambda: build_split(split),
        notes=(
            "Gold from construction: values are inserted into templates, never labelled by a "
            "model.",
            f"{int(INVALID_SHARE * 100)} % of checksummed identifiers fail their checksum on "
            "purpose (meta.checksum); "
            f"{int(PERTURB_SHARE * 100)} % of values are perturbed (meta.perturbed).",
        ),
    )


DATASET = _dataset("test")
DEV_DATASET = _dataset("dev")
