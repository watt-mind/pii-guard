"""Seeded fictional identities for the synthetic corpus (ADR 0005).

Everything here is generated from a :class:`random.Random`: people, addresses, dates of birth,
checksum-valid Hungarian tax IDs / TAJ numbers / giro accounts / IBANs, phone numbers,
e-mail addresses, licence plates, companies, land parcels and institutions. No person record
is looked up; no real person is referenced. Names are common first and last names combined at
random (Hungarian ones drawn by frequency from the language pack's lexicons, ADR 0009, with
real settlements and their own postcodes),
e-mail addresses use the reserved ``example.*`` domains (RFC 2606), English phone numbers come
from the ranges Ofcom sets aside for drama, and checksummed identifiers are valid in form but
issued to nobody.

Language-independent pieces (IBANs, e-mail addresses, number grouping) are shared; each
language adds its names, address format, phone formats and national identifiers::

    rng = random.Random("42/hu/7")
    ids = identity_generator("hu", rng)
    seller = ids.person()
    seller.values(["name", "date_of_birth", "tax_id"])  # -> [Value(...), ...]

A :class:`Value` is what the model is told to write and what the generator then locates in
the output. ``repr()`` of every record here hides the values.
"""

from __future__ import annotations

import datetime as dt
import random
import unicodedata
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

from pii_guard.detect.checksums import (
    giro_check_digit,
    hu_tax_id_check_digit,
    hu_tax_number_check_digit,
    iban_check_digits,
    taj_check_digit,
)
from pii_guard.lang import lexicon, postcode_index
from pii_guard.types import EntityType

__all__ = [
    "FIELD_TYPES",
    "LANGUAGES",
    "Company",
    "EnglishIdentities",
    "HungarianIdentities",
    "IdentityGenerator",
    "Institution",
    "Person",
    "Property",
    "Value",
    "ascii_fold",
    "email_address",
    "group",
    "hu_giro",
    "hu_iban",
    "hu_tax_id",
    "hu_tax_number",
    "iban",
    "identity_generator",
    "taj_number",
]


@dataclass(frozen=True, slots=True)
class Value:
    """A labelled value the model must write (``required``) or may write (optional).

    Optional values are name parts (a given name or surname used alone, a company name
    without its legal form). ``capitalized`` values only count where the match starts with an
    upper-case letter, so a surname that is also a common word isn't labelled in prose.
    """

    field: str
    entity_type: EntityType
    text: str
    required: bool = True
    capitalized: bool = False

    def __repr__(self) -> str:
        return (
            f"Value(field={self.field!r}, entity_type={self.entity_type.value}, "
            f"required={self.required}, text=<redacted>)"
        )

    __str__ = __repr__


#: The entity type of every field a template may request.
FIELD_TYPES: dict[str, EntityType] = {
    "name": EntityType.PERSON,
    "mother_name": EntityType.PERSON,
    "date_of_birth": EntityType.DATE_OF_BIRTH,
    "address": EntityType.ADDRESS,
    "email": EntityType.EMAIL,
    "phone": EntityType.PHONE,
    "tax_id": EntityType.NATIONAL_ID_HU_TAX,
    "taj": EntityType.NATIONAL_ID_HU_TAJ,
    "id_document": EntityType.ID_DOCUMENT,
    "bank_account": EntityType.BANK_ACCOUNT,
    "plate": EntityType.VEHICLE_PLATE,
    "reg_number": EntityType.COMPANY_ID_HU,
    "tax_number": EntityType.COMPANY_ID_HU,
    "parcel": EntityType.PARCEL_NUMBER_HU,
    "org_name": EntityType.ORGANIZATION,
}


class _Record:
    """Shared ``values()`` for the identity records below."""

    __slots__ = ()

    def _optional(self) -> list[Value]:
        return []

    def values(self, fields: Iterable[str]) -> list[Value]:
        """The requested fields as required values, plus optional name parts.

        Raises ``KeyError`` for a field this record doesn't have (for example a TAJ number for
        an English identity), so a template can't silently ask for nothing.
        """
        out: list[Value] = []
        for name in fields:
            text = getattr(self, name, None)
            if not isinstance(text, str) or not text:
                raise KeyError(f"{type(self).__name__} has no field {name!r}")
            out.append(Value(name, FIELD_TYPES[name], text))
        if any(v.field in {"name", "org_name"} for v in out):
            out.extend(self._optional())
        return out

    def __repr__(self) -> str:
        return f"{type(self).__name__}(<redacted>)"

    __str__ = __repr__


@dataclass(frozen=True, slots=True, repr=False)
class Person(_Record):
    given: str
    family: str
    name: str
    gender: str
    birth_date: dt.date
    date_of_birth: str
    address: str
    email: str
    phone: str
    id_document: str
    bank_account: str
    plate: str
    mother_name: str | None = None
    tax_id: str | None = None
    taj: str | None = None

    def _optional(self) -> list[Value]:
        return [
            Value("given", EntityType.PERSON, self.given, required=False, capitalized=True),
            Value("family", EntityType.PERSON, self.family, required=False, capitalized=True),
        ]


@dataclass(frozen=True, slots=True, repr=False)
class Company(_Record):
    org_name: str
    short_name: str
    address: str
    email: str
    phone: str
    bank_account: str
    reg_number: str | None = None
    tax_number: str | None = None

    def _optional(self) -> list[Value]:
        return [
            Value(
                "short_name",
                EntityType.ORGANIZATION,
                self.short_name,
                required=False,
                capitalized=True,
            )
        ]


@dataclass(frozen=True, slots=True, repr=False)
class Property(_Record):
    address: str
    parcel: str | None = None


@dataclass(frozen=True, slots=True, repr=False)
class Institution(_Record):
    org_name: str
    address: str
    phone: str
    email: str


# --- Language-independent pieces --------------------------------------------------------


def ascii_fold(text: str) -> str:
    """``"Kovács Ödön"`` -> ``"Kovacs Odon"`` (for e-mail local parts and slugs)."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def _slug(text: str, sep: str = "") -> str:
    words = ["".join(ch for ch in w if ch.isalnum()) for w in ascii_fold(text).lower().split()]
    return sep.join(w for w in words if w)


_PERSON_DOMAINS = ("example.com", "example.org", "example.net")


def email_address(rng: random.Random, given: str, family: str, year: int | None = None) -> str:
    """A personal address on a reserved ``example.*`` domain."""
    g, f = _slug(given), _slug(family)
    local = rng.choice(
        [
            f"{g}.{f}",
            f"{f}.{g}",
            f"{g[0]}{f}",
            f"{g}{f}",
            f"{g}.{f}{(year or 1990) % 100:02d}",
            f"{f}{g[0]}{rng.randint(1, 99)}",
        ]
    )
    return f"{local}@{rng.choice(_PERSON_DOMAINS)}"


def group(text: str, size: int = 4, sep: str = " ") -> str:
    return sep.join(text[i : i + size] for i in range(0, len(text), size))


def iban(country: str, bban: str, grouped: bool = True) -> str:
    compact = country + iban_check_digits(country, bban) + bban
    return group(compact) if grouped else compact


def _digits(rng: random.Random, n: int) -> str:
    return "".join(str(rng.randint(0, 9)) for _ in range(n))


def _letters(rng: random.Random, n: int, alphabet: str = "ABCDEFGHJKLMNPRSTUVWXYZ") -> str:
    return "".join(rng.choice(alphabet) for _ in range(n))


# --- Hungarian identifiers ----------------------------------------------------------------

_HU_TAX_EPOCH = dt.date(1867, 1, 1)


def hu_tax_id(rng: random.Random, birth_date: dt.date) -> str:
    """A checksum-valid adóazonosító jel: ``8``, days since 1867-01-01, serial, check digit."""
    days = (birth_date - _HU_TAX_EPOCH).days
    while True:
        payload = f"8{days:05d}{_digits(rng, 3)}"
        check = hu_tax_id_check_digit(payload)
        if check is not None:
            return payload + str(check)


def taj_number(rng: random.Random, sep: str = " ") -> str:
    payload = str(rng.randint(1, 9)) + _digits(rng, 7)
    digits = payload + str(taj_check_digit(payload))
    return sep.join((digits[:3], digits[3:6], digits[6:])) if sep is not None else digits


def _giro_block(payload: str) -> str:
    return payload + str(giro_check_digit(payload))


def hu_giro(rng: random.Random, long: bool | None = None, sep: str = "-") -> str:
    """A checksum-valid giro account: 8+8 or 8+8+8 digits."""
    bank = "1" + _digits(rng, 6)
    long = rng.random() < 0.6 if long is None else long
    account = _giro_block(_digits(rng, 15 if long else 7))
    first = _giro_block(bank)
    if long:
        return sep.join((first, account[:8], account[8:]))
    return sep.join((first, account))


def hu_iban(rng: random.Random, grouped: bool = True) -> str:
    bban = hu_giro(rng, long=True, sep="")
    return iban("HU", bban, grouped=grouped)


def hu_tax_number(rng: random.Random) -> str:
    """A valid company adószám ``12345678-2-42``."""
    base = str(rng.randint(1, 2)) + _digits(rng, 6)
    area = rng.choice(["02", "03", "05", "06", "07", "08", "09", "11", "13", "14", "41", "42"])
    return f"{base}{hu_tax_number_check_digit(base)}-{rng.choice('2222235')}-{area}"


# --- Base generator -------------------------------------------------------------------------


@dataclass(slots=True)
class IdentityGenerator:
    """Per-language generator. Subclasses fill in the name lists and formats."""

    rng: random.Random
    language: str = ""
    _used_names: set[str] = field(default_factory=set)
    _street_tokens: set[str] = field(default_factory=set)
    #: Index into the generator's institution towns. When set, properties and institutions
    #: are placed there, so a land registry office or court sits in the property's own town.
    local_town: int | None = None
    #: Also keep given names (mothers' included) distinct between the people of one document.
    #: Off by default so other seeded sets built on this generator stay byte-identical.
    distinct_given_names: bool = False

    @property
    def town_count(self) -> int:
        """How many towns have institutions (valid values of ``local_town``)."""
        raise NotImplementedError  # pragma: no cover - abstract

    # Hooks -------------------------------------------------------------------------------
    def person(self, gender: str | None = None) -> Person:  # pragma: no cover - abstract
        raise NotImplementedError

    def company(self) -> Company:  # pragma: no cover - abstract
        raise NotImplementedError

    def property(self) -> Property:  # pragma: no cover - abstract
        raise NotImplementedError

    def institution(self, kind: str = "court") -> Institution:  # pragma: no cover - abstract
        raise NotImplementedError

    # Shared ------------------------------------------------------------------------------
    def make(self, kind: str) -> _Record:
        """``"person"``, ``"company"``, ``"property"``, or ``"court"`` / ``"office"``."""
        factories: dict[str, Callable[[], _Record]] = {
            "person": self.person,
            "company": self.company,
            "property": self.property,
            "court": lambda: self.institution("court"),
            "office": lambda: self.institution("office"),
        }
        if kind not in factories:
            raise ValueError(f"unknown identity kind {kind!r}")
        return factories[kind]()

    def _birth_date(self) -> dt.date:
        start = dt.date(1945, 1, 1).toordinal()
        end = dt.date(2004, 12, 31).toordinal()
        return dt.date.fromordinal(self.rng.randint(start, end))

    def _town_index(self, count: int) -> int:
        return self.local_town if self.local_town is not None else self.rng.randrange(count)

    def _unique_name(self, build: Callable[[], tuple[str, str, str]]) -> tuple[str, str, str]:
        # Distinct people in one document get distinct full names and surnames, so labels
        # (and the model) can't confuse them; with ``distinct_given_names`` every name part,
        # so a given name used alone ("Péter") points at one person only.
        for _ in range(50):
            given, family, full = build()
            parts = set(full.split()) if self.distinct_given_names else {family}
            if full not in self._used_names and not parts & self._used_names:
                self._used_names.update({full, family, given, *full.split()})
                return given, family, full
        return build()  # pragma: no cover - lists are much larger than any document


# --- Hungarian --------------------------------------------------------------------------------

# Names and places come from the language pack's lexicons (pii_guard.lang, ADR 0009): given
# names and surnames are drawn by frequency and combined at random, so no generated person is
# a real one. A temperature below 1 flattens the long tail: more distinct values per document
# set than the raw frequencies would give.
_HU_NAME_TEMPERATURE = 0.5
_HU_PLACE_TEMPERATURE = 0.6
# Flattening leaves Budapest at ~2% of addresses; about a sixth of Hungarians live there.
_HU_BUDAPEST_SHARE = 0.17
# Public-space types that real street addresses use, with rough relative frequencies (the OSM
# counts in the street_types lexicon, capped so "utca" doesn't drown the rest).
_HU_STREET_TYPES = ("utca", "út", "tér", "köz", "sor", "körút", "sétány", "fasor", "rakpart")
_HU_STREET_TYPE_WEIGHTS = (60, 20, 6, 6, 3, 2, 1, 1, 1)
_HU_MONTHS = (
    "január", "február", "március", "április", "május", "június", "július", "augusztus",
    "szeptember", "október", "november", "december",
)  # fmt: skip

# Court and office towns: (town, adjective form for institution names, postcodes)
_HU_TOWNS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("Budapest", "Budai Központi Kerületi", ("1027", "1051", "1072", "1083", "1114", "1138")),
    ("Budapest", "Pesti Központi Kerületi", ("1095", "1106", "1141", "1155", "1181", "1203")),
    ("Debrecen", "Debreceni", ("4024", "4026", "4032")),
    ("Szeged", "Szegedi", ("6720", "6722", "6724")),
    ("Pécs", "Pécsi", ("7621", "7624", "7630")),
    ("Győr", "Győri", ("9021", "9022", "9024")),
    ("Miskolc", "Miskolci", ("3525", "3527", "3530")),
    ("Kecskemét", "Kecskeméti", ("6000",)),
    ("Nyíregyháza", "Nyíregyházi", ("4400",)),
    ("Székesfehérvár", "Székesfehérvári", ("8000",)),
    ("Szombathely", "Szombathelyi", ("9700",)),
    ("Eger", "Egri", ("3300",)),
    ("Veszprém", "Veszprémi", ("8200",)),
    ("Sopron", "Soproni", ("9400",)),
    ("Kaposvár", "Kaposvári", ("7400",)),
    ("Szolnok", "Szolnoki", ("5000",)),
    ("Vác", "Váci", ("2600",)),
    ("Gödöllő", "Gödöllői", ("2100",)),
    ("Siófok", "Siófoki", ("8600",)),
    ("Baja", "Bajai", ("6500",)),
)
_HU_COMPANY_A = (
    "Napfény", "Tölgyfa", "Zöldmező", "Rózsakert", "Csillagvirág", "Délibáb", "Fenyőliget",
    "Kristálypatak", "Ezüstnyír", "Hajnalpír", "Kékfelhő", "Gyöngyház", "Szélmalom",
    "Mókusdomb", "Vadgesztenye", "Borostyánkő",
)  # fmt: skip
_HU_COMPANY_B = (
    "Ingatlan", "Építő", "Kereskedelmi", "Szolgáltató", "Fuvarozó", "Könyvelő", "Asztalos",
    "Vendéglátó", "Informatikai", "Villanyszerelő", "Kertészeti", "Tanácsadó",
)  # fmt: skip
# (legal form, cégforma code in the registration number)
_HU_FORMS = (("Kft.", "09"), ("Kft.", "09"), ("Kft.", "09"), ("Bt.", "06"), ("Zrt.", "10"))


class HungarianIdentities(IdentityGenerator):
    """Hungarian people (family name first), addresses, IDs and companies."""

    def __init__(self, rng: random.Random) -> None:
        super().__init__(rng, "hu")

    @property
    def town_count(self) -> int:
        return len(_HU_TOWNS)

    def _given(self, gender: str, avoid: str = "") -> str:
        kind = "given_names_f" if gender == "f" else "given_names_m"
        for _ in range(20):
            given = lexicon(kind, "hu").sample(self.rng, _HU_NAME_TEMPERATURE)
            # A given name that is part of a street in this document (Petőfi Sándor utca)
            # would be labelled inside the address.
            if given != avoid and given not in self._street_tokens:
                return given
        return given  # pragma: no cover - the lists are much larger than one document

    def _surname(self, avoid: str = "") -> str:
        for _ in range(20):
            family = lexicon("surnames", "hu").sample(self.rng, _HU_NAME_TEMPERATURE)
            if family != avoid and family not in self._street_tokens:
                return family
        return family  # pragma: no cover

    def _name(self, gender: str) -> tuple[str, str, str]:
        given = self._given(gender)
        family = self._surname()
        if self.rng.random() < 0.08:  # a second given name
            second = self._given(gender, avoid=given)
            return given, family, f"{family} {given} {second}"
        return given, family, f"{family} {given}"

    def date(self, day: dt.date) -> str:
        style = self.rng.randrange(4)
        if style == 0:
            return f"{day.year}. {_HU_MONTHS[day.month - 1]} {day.day}."
        if style == 1:
            return f"{day.year}.{day.month:02d}.{day.day:02d}."
        if style == 2:
            return f"{day.year}. {day.month:02d}. {day.day:02d}."
        return day.isoformat()

    def address(self, town_index: int | None = None) -> str:
        """``<postcode> <settlement>, <street> <type> <number>[ <floor/door>]``.

        The settlement is Budapest about as often as in real life, otherwise drawn from the
        gazetteer (population-weighted, flattened), with one of its own postcodes, so every
        generated address passes the rule detector's postcode check; ``town_index`` pins one
        of the court towns instead.
        """
        if town_index is not None:
            town = _HU_TOWNS[town_index][0]
            code = self.rng.choice(_HU_TOWNS[town_index][2])
        elif self.rng.random() < _HU_BUDAPEST_SHARE:
            town = "Budapest"
            code = self._postcode(town)
        else:
            town = lexicon("settlements", "hu").sample(self.rng, _HU_PLACE_TEMPERATURE)
            code = self._postcode(town)
        street = self._street()
        number = str(self.rng.randint(1, 120))
        if self.rng.random() < 0.15:
            number += "/" + self.rng.choice("ABC")
        number += "."
        if self.rng.random() < 0.45:
            number += self.rng.choice(
                [
                    f" {self.rng.randint(1, 10)}/{self.rng.randint(1, 40)}.",
                    f" {self.rng.randint(1, 10)}. em. {self.rng.randint(1, 40)}.",
                    f" fszt. {self.rng.randint(1, 6)}.",
                ]
            )
        return f"{code} {town}, {street} {number}"

    def _postcode(self, town: str) -> str:
        index = postcode_index("hu")
        prefix = index.structural.get(town.casefold())
        if prefix is not None and self.rng.random() < 0.8:
            # Large cities: a street-level code (Budapest 1 + district + digit, Debrecen 40xx)
            for _ in range(50):
                if prefix == "1":
                    code = f"1{self.rng.randint(1, 23):02d}{self.rng.randint(0, 9)}"
                else:
                    code = prefix + _digits(self.rng, 4 - len(prefix))
                if index.consistent(code, town):
                    return code
        codes = sorted(index.by_settlement.get(town.casefold(), ()))
        return self.rng.choice(codes)

    def _street(self) -> str:
        for _ in range(20):
            name = lexicon("street_names", "hu").sample(self.rng, _HU_NAME_TEMPERATURE)
            if not (set(name.split()) & self._used_names):
                break
        street_type = self.rng.choices(_HU_STREET_TYPES, weights=_HU_STREET_TYPE_WEIGHTS)[0]
        self._street_tokens.update(name.split())
        return f"{name} {street_type}"

    def phone(self) -> str:
        rng = self.rng
        if rng.random() < 0.2:  # Budapest landline
            nsn = "1" + str(rng.randint(2, 9)) + _digits(rng, 6)
            return rng.choice([f"+36 1 {nsn[1:4]} {nsn[4:]}", f"06 1 {nsn[1:4]} {nsn[4:]}"])
        area = rng.choice(["20", "30", "31", "50", "70"])
        sub = str(rng.randint(1, 9)) + _digits(rng, 6)
        return rng.choice(
            [
                f"+36 {area} {sub[:3]} {sub[3:]}",
                f"06 {area} {sub[:3]} {sub[3:]}",
                f"06-{area}-{sub[:3]}-{sub[3:]}",
                f"+36{area}{sub}",
                f"06/{area} {sub[:3]} {sub[3:]}",
            ]
        )

    def plate(self) -> str:
        if self.rng.random() < 0.5:
            return f"{_letters(self.rng, 3)}-{_digits(self.rng, 3)}"
        return f"A{_letters(self.rng, 1)} {_letters(self.rng, 2)}-{_digits(self.rng, 3)}"

    def bank_account(self) -> str:
        roll = self.rng.random()
        if roll < 0.5:
            return hu_giro(self.rng)
        return hu_iban(self.rng, grouped=roll < 0.85)

    def person(self, gender: str | None = None) -> Person:
        gender = gender or self.rng.choice("fm")
        given, family, full = self._unique_name(lambda: self._name(gender))
        mother_given = self._given("f")
        if self.distinct_given_names:
            for _ in range(20):
                if mother_given not in self._used_names:
                    break
                mother_given = self._given("f")
            self._used_names.add(mother_given)
        mother_family = self._surname(avoid=family)
        birth = self._birth_date()
        return Person(
            given=given,
            family=family,
            name=full,
            gender=gender,
            birth_date=birth,
            date_of_birth=self.date(birth),
            address=self.address(),
            email=email_address(self.rng, given, family, birth.year),
            phone=self.phone(),
            id_document=f"{_digits(self.rng, 6)}{_letters(self.rng, 2)}",
            bank_account=self.bank_account(),
            plate=self.plate(),
            mother_name=f"{mother_family} {mother_given}",
            tax_id=hu_tax_id(self.rng, birth),
            taj=taj_number(self.rng, sep=self.rng.choice([" ", " ", "-", ""])),
        )

    def company(self) -> Company:
        a = self.rng.choice(_HU_COMPANY_A)
        b = self.rng.choice(_HU_COMPANY_B)
        form, form_code = self.rng.choice(_HU_FORMS)
        short = f"{a} {b}"
        court = f"{self.rng.randint(1, 20):02d}"
        return Company(
            org_name=f"{short} {form}",
            short_name=short,
            address=self.address(),
            email=f"{self.rng.choice(['info', 'iroda', 'ugyfelszolgalat'])}@"
            f"{_slug(short, '-')}.example",
            phone=self.phone(),
            bank_account=self.bank_account(),
            reg_number=f"{court}-{form_code}-{_digits(self.rng, 6)}",
            tax_number=hu_tax_number(self.rng),
        )

    def property(self) -> Property:
        parcel = str(self.rng.randint(100, 39999))
        if self.rng.random() < 0.7:
            parcel += f"/{self.rng.randint(1, 40)}"
        if self.rng.random() < 0.15:
            parcel = "0" + parcel
        return Property(address=self.address(self.local_town), parcel=parcel)

    def institution(self, kind: str = "court") -> Institution:
        index = self._town_index(len(_HU_TOWNS))
        town, adjective, _ = _HU_TOWNS[index]
        if kind == "court":
            name = (
                f"{adjective} Bíróság" if "Kerületi" in adjective else f"{adjective} Járásbíróság"
            )
        else:
            name = f"{adjective.split()[0]} Járási Hivatal"
        return Institution(
            org_name=name,
            address=self.address(index),
            phone=self.phone(),
            email=f"{self.rng.choice(['ugyfelkapu', 'titkarsag', 'info'])}@"
            f"{_slug(town)}-{'birosag' if kind == 'court' else 'hivatal'}.example",
        )


# --- English (United Kingdom) -----------------------------------------------------------------

_EN_FAMILY = (
    "Carter", "Whitfield", "Hollis", "Pemberton", "Ashworth", "Thornton", "Fairbanks",
    "Langley", "Holloway", "Kendall", "Prescott", "Radcliffe", "Sinclair", "Hargreaves",
    "Calloway", "Barrington", "Winslow", "Ellison", "Fletcher", "Hughes", "Morgan", "Bennett",
    "Turner", "Patel", "Okafor", "Nowak", "Murphy", "Clarke", "Hayes", "Doyle", "Quinn",
    "Kowalski", "Achebe", "Lindqvist", "Fairweather", "Dunmore", "Ashby", "Millington",
)  # fmt: skip
_EN_GIVEN_F = (
    "Amelia", "Isla", "Ava", "Mia", "Emily", "Sophie", "Ella", "Chloe", "Hannah", "Lucy",
    "Priya", "Aisha", "Siobhan", "Olivia", "Freya", "Imogen", "Zara", "Eleanor", "Martha",
)  # fmt: skip
_EN_GIVEN_M = (
    "Oliver", "George", "Harry", "Charlie", "Thomas", "James", "William", "Henry", "Daniel",
    "Samuel", "Joseph", "Benjamin", "Tomasz", "Arjun", "Callum", "Rhys", "Edward", "Oscar",
)  # fmt: skip
_EN_MONTHS = (
    "January", "February", "March", "April", "May", "June", "July", "August", "September",
    "October", "November", "December",
)  # fmt: skip
_EN_TOWNS = (
    ("Harrogate", "HG"), ("Bath", "BA"), ("Exeter", "EX"), ("Leeds", "LS"), ("York", "YO"),
    ("Norwich", "NR"), ("Reading", "RG"), ("Oxford", "OX"), ("Cambridge", "CB"),
    ("Bristol", "BS"), ("Chester", "CH"), ("Durham", "DH"), ("Lancaster", "LA"),
    ("Salisbury", "SP"), ("Truro", "TR"),
)  # fmt: skip
_EN_STREETS = (
    "Willow Lane", "Station Road", "Church Street", "Mill Road", "Victoria Street",
    "Park Avenue", "Orchard Close", "Elm Grove", "High Street", "Meadow Way",
    "Kingfisher Drive", "Rosemary Court", "Chapel Lane", "Beechwood Road", "Ferndale Crescent",
)  # fmt: skip
_EN_COMPANY_A = (
    "Brightwater", "Oakfield", "Kestrel", "Harbourside", "Larkspur", "Millbrook", "Northgate",
    "Copperleaf", "Silverbirch", "Foxglove", "Ravenscar", "Thistledown",
)  # fmt: skip
_EN_COMPANY_B = (
    "Lettings", "Property Services", "Logistics", "Consulting", "Joinery", "Electrical",
    "Accountancy", "Landscaping", "Catering", "Software",
)  # fmt: skip
_POSTCODE_LETTERS = "ABDEFGHJLNPQRSTUWXYZ"


class EnglishIdentities(IdentityGenerator):
    """UK-style people (given name first), addresses, phones, IBANs and companies."""

    def __init__(self, rng: random.Random) -> None:
        super().__init__(rng, "en")

    @property
    def town_count(self) -> int:
        return len(_EN_TOWNS)

    def _name(self, gender: str) -> tuple[str, str, str]:
        given = self.rng.choice(_EN_GIVEN_F if gender == "f" else _EN_GIVEN_M)
        family = self.rng.choice(_EN_FAMILY)
        return given, family, f"{given} {family}"

    def date(self, day: dt.date) -> str:
        style = self.rng.randrange(4)
        if style == 0:
            return f"{day.day} {_EN_MONTHS[day.month - 1]} {day.year}"
        if style == 1:
            return f"{_EN_MONTHS[day.month - 1]} {day.day}, {day.year}"
        if style == 2:
            return f"{day.day:02d}/{day.month:02d}/{day.year}"
        return day.isoformat()

    def postcode(self, area: str) -> str:
        district = self.rng.randint(1, 20)
        return (
            f"{area}{district} {self.rng.randint(1, 9)}{_letters(self.rng, 2, _POSTCODE_LETTERS)}"
        )

    def address(self, town_index: int | None = None) -> str:
        town, area = _EN_TOWNS[town_index] if town_index is not None else self.rng.choice(_EN_TOWNS)
        number = str(self.rng.randint(1, 180))
        street = self.rng.choice(_EN_STREETS)
        flat = f"Flat {self.rng.randint(1, 24)}, " if self.rng.random() < 0.2 else ""
        return f"{flat}{number} {street}, {town} {self.postcode(area)}"

    def phone(self) -> str:
        # Ofcom drama ranges: 07700 900000-900999, 020 7946 0000-0999, 0113 496 0000-0999.
        rng = self.rng
        tail3, tail4 = f"{rng.randint(0, 999):03d}", f"{rng.randint(0, 999):04d}"
        return rng.choice(
            [
                f"07700 900{tail3}",
                f"+44 7700 900{tail3}",
                f"020 7946 {tail4}",
                f"+44 20 7946 {tail4}",
                f"0113 496 {tail4}",
            ]
        )

    def plate(self) -> str:
        return (
            f"{_letters(self.rng, 2)}{self.rng.randint(51, 74)} {_letters(self.rng, 3)}"
            if self.rng.random() < 0.5
            else f"{_letters(self.rng, 2)}{self.rng.randint(10, 24):02d} {_letters(self.rng, 3)}"
        )

    def bank_account(self) -> str:
        bban = _letters(self.rng, 4, "ABCDEFGHIJKLMNOPQRSTUVWXYZ") + _digits(self.rng, 14)
        return iban("GB", bban, grouped=self.rng.random() < 0.8)

    def person(self, gender: str | None = None) -> Person:
        gender = gender or self.rng.choice("fm")
        given, family, full = self._unique_name(lambda: self._name(gender))
        birth = self._birth_date()
        return Person(
            given=given,
            family=family,
            name=full,
            gender=gender,
            birth_date=birth,
            date_of_birth=self.date(birth),
            address=self.address(),
            email=email_address(self.rng, given, family, birth.year),
            phone=self.phone(),
            id_document=str(self.rng.randint(1, 9)) + _digits(self.rng, 8),
            bank_account=self.bank_account(),
            plate=self.plate(),
        )

    def company(self) -> Company:
        short = f"{self.rng.choice(_EN_COMPANY_A)} {self.rng.choice(_EN_COMPANY_B)}"
        return Company(
            org_name=f"{short} {self.rng.choice(['Ltd', 'Ltd', 'Limited', 'LLP'])}",
            short_name=short,
            address=self.address(),
            email=f"{self.rng.choice(['hello', 'accounts', 'info'])}@{_slug(short, '-')}.example",
            phone=self.phone(),
            bank_account=self.bank_account(),
        )

    def property(self) -> Property:
        return Property(address=self.address(self.local_town))

    def institution(self, kind: str = "court") -> Institution:
        index = self._town_index(len(_EN_TOWNS))
        town = _EN_TOWNS[index][0]
        name = f"{town} County Court" if kind == "court" else f"{town} City Council"
        return Institution(
            org_name=name,
            address=self.address(index),
            phone=self.phone(),
            email=f"enquiries@{_slug(town)}-{'court' if kind == 'court' else 'council'}.example",
        )


LANGUAGES: dict[str, type[IdentityGenerator]] = {
    "hu": HungarianIdentities,
    "en": EnglishIdentities,
}


def identity_generator(language: str, rng: random.Random) -> IdentityGenerator:
    """The generator for ``language`` (``"hu"``, ``"en"``; ``"en-GB"`` -> ``"en"``)."""
    code = language.split("-", 1)[0].lower()
    if code not in LANGUAGES:
        raise ValueError(f"no identity generator for language {language!r}")
    return LANGUAGES[code](rng)
