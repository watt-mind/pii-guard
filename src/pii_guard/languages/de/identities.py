"""German fictional identities for the synthetic corpus (ADR 0005). Part of the German pack.

People (given name first), addresses (``Lindenstraße 12, 10115 Berlin``), dates of birth,
checksum-valid Steuer-IDs, Personalausweis-style document numbers, DE IBANs, plates, companies
and institutions, all from a seeded :class:`random.Random`.

The name, street and town lists are hand-curated for this project (ADR 0009: our own lists are
committed): common German given names and surnames, combined at random, so no generated person
is a real one. Towns are real, with postcodes from their own range, so every address passes the
German address rule. Telephone numbers come from the ranges the Bundesnetzagentur keeps free for
film and television (``030 23125 xxx``, ``040 66969 xxx``, ``069 90009 xxx``,
``089 99998 xxx``, ``0221 4710 xxx``); e-mail addresses use the reserved ``example.*`` domains.
"""

from __future__ import annotations

import datetime as dt
import random

from pii_guard.eval.identities import (
    Company,
    IdentityGenerator,
    Institution,
    Person,
    Property,
    ascii_fold,
    email_address,
    iban,
)
from pii_guard.languages.de.checksums import is_valid_steuer_id, steuer_id_check_digit

__all__ = ["GermanIdentities", "steuer_id"]

_GIVEN_F = (
    "Anna", "Julia", "Laura", "Sophie", "Katharina", "Lena", "Sarah", "Lisa", "Hannah", "Marie",
    "Johanna", "Franziska", "Sabine", "Petra", "Claudia", "Monika", "Ursula", "Birgit", "Emma",
    "Mia", "Lea", "Clara", "Charlotte", "Greta", "Ida", "Paula", "Nina", "Carina", "Heike",
    "Andrea", "Susanne", "Martina", "Gabriele", "Renate", "Kerstin", "Melanie", "Stefanie",
    "Nadine", "Jana", "Tanja", "Ayşe", "Elif", "Natalia", "Agnieszka", "Ingrid", "Helga",
)  # fmt: skip
_GIVEN_M = (
    "Lukas", "Jonas", "Felix", "Maximilian", "Paul", "Leon", "Tobias", "Florian", "Stefan",
    "Thomas", "Andreas", "Michael", "Jürgen", "Klaus", "Matthias", "Sebastian", "Jan", "Tim",
    "Niklas", "Moritz", "David", "Simon", "Philipp", "Benedikt", "Johannes", "Markus", "Frank",
    "Uwe", "Ralf", "Dirk", "Holger", "Torsten", "Christian", "Daniel", "Alexander", "Henrik",
    "Emre", "Mehmet", "Piotr", "Dmitri", "Wolfgang", "Dieter", "Günter", "Bernd", "Karsten",
)  # fmt: skip
_FAMILY = (
    "Müller", "Schmidt", "Schneider", "Fischer", "Weber", "Meyer", "Wagner", "Becker",
    "Schulz", "Hoffmann", "Koch", "Richter", "Klein", "Wolf", "Schröder", "Neumann",
    "Schwarz", "Braun", "Zimmermann", "Hartmann", "Krüger", "Lange", "Werner", "Lehmann",
    "Schmitz", "Krause", "Meier", "Köhler", "Herrmann", "König", "Walter", "Mayer", "Huber",
    "Kaiser", "Fuchs", "Peters", "Lang", "Scholz", "Möller", "Weiß", "Jung", "Hahn", "Vogel",
    "Friedrich", "Keller", "Günther", "Berger", "Winkler", "Roth", "Beck", "Lorenz",
    "Baumann", "Franke", "Albrecht", "Schuster", "Ludwig", "Böhm", "Winter", "Kraus",
    "Schumacher", "Krämer", "Vogt", "Stein", "Jäger", "Otto", "Sommer", "Groß",
    "Seidel", "Heinrich", "Brandt", "Haas", "Schreiber", "Graf", "Schulte", "Dietrich",
    "Ziegler", "Kuhn", "Kühn", "Pohl", "Engel", "Horn", "Busch", "Bergmann",
    "Voigt", "Sauer", "Arnold", "Wolff", "Pfeiffer", "Yılmaz", "Kaya", "Nowak", "Kowalski",  # noqa: RUF001
)  # fmt: skip
_MONTHS = (
    "Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September",
    "Oktober", "November", "Dezember",
)  # fmt: skip
# (town, Kfz-Kennzeichen prefix, postcodes in the town's own range)
_TOWNS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("Berlin", "B", ("10115", "10178", "10245", "10437", "10827", "12049", "12555", "13353")),
    ("Hamburg", "HH", ("20095", "20249", "20357", "22083", "22765")),
    ("München", "M", ("80331", "80469", "80799", "81369", "81675")),
    ("Köln", "K", ("50667", "50733", "50823", "50937")),
    ("Leipzig", "L", ("04103", "04109", "04177", "04277")),
    ("Dresden", "DD", ("01067", "01099", "01309")),
    ("Stuttgart", "S", ("70173", "70182", "70372")),
    ("Düsseldorf", "D", ("40210", "40477", "40545")),
    ("Hannover", "H", ("30159", "30161", "30169")),
    ("Nürnberg", "N", ("90402", "90429", "90489")),
    ("Bremen", "HB", ("28195", "28203", "28209")),
    ("Bonn", "BN", ("53111", "53113", "53129")),
    ("Münster", "MS", ("48143", "48145", "48151")),
    ("Heidelberg", "HD", ("69115", "69117", "69120")),
    ("Kiel", "KI", ("24103", "24105", "24114")),
    ("Rostock", "HRO", ("18055", "18057", "18069")),
    ("Erfurt", "EF", ("99084", "99089", "99096")),
    ("Mainz", "MZ", ("55116", "55118", "55122")),
    ("Regensburg", "R", ("93047", "93049", "93053")),
    ("Augsburg", "A", ("86150", "86152", "86159")),
    ("Potsdam", "P", ("14467", "14469", "14482")),
    ("Göttingen", "GÖ", ("37073", "37075", "37083")),
    ("Kassel", "KS", ("34117", "34119", "34131")),
)
# Every name ends in a street word the German address rule knows (straße, weg, platz, ...).
_STREETS = (
    "Hauptstraße", "Schulstraße", "Gartenstraße", "Bahnhofstraße", "Lindenweg", "Birkenallee",
    "Kirchgasse", "Bergstraße", "Rosenweg", "Mühlenweg", "Waldstraße", "Lindenstraße",
    "Ahornweg", "Schillerstraße", "Goethestraße", "Feldweg", "Marktplatz", "Am Lindenplatz",
    "Kastanienallee", "Uferweg", "Wiesenring", "Brunnengasse", "Eichendorffstraße",
    "Alte Dorfstraße", "Hafenstraße", "Sonnenweg", "Kirchplatz", "Talstraße", "Parkallee",
    "Fliederweg", "Rheinuferweg", "Tannenring", "Mozartstraße", "Gartenweg", "Am Mühlendamm",
)  # fmt: skip
_COMPANY_A = (
    "Nordlicht", "Weidenhof", "Elbtal", "Kranich", "Sonnenhof", "Lindenhof", "Bergquell",
    "Eichenwald", "Silberfluss", "Rotdorn", "Falkenstein", "Seeblick", "Morgenrot", "Kiefernhain",
)  # fmt: skip
_COMPANY_B = (
    "Immobilien", "Logistik", "Haustechnik", "Software", "Baustoffe", "Druckerei", "Gartenbau",
    "Steuerberatung", "Elektrotechnik", "Tischlerei", "Gastronomie", "Hausverwaltung",
)  # fmt: skip
_LEGAL_FORMS = ("GmbH", "GmbH", "GmbH", "UG (haftungsbeschränkt)", "KG", "GmbH & Co. KG", "e. K.")
# Bundesnetzagentur ranges reserved for film and television: (area code, block)
_PHONE_BLOCKS = (("030", "23125"), ("040", "66969"), ("069", "90009"), ("089", "99998"),
                 ("0221", "4710"))  # fmt: skip
_ID_ALPHABET = "CFGHJKLMNPRTVWXYZ0123456789"  # Personalausweis serial characters


def steuer_id(rng: random.Random, grouped: bool = False) -> str:
    """A Steuer-ID with a valid structure and check digit (issued to nobody)."""
    while True:
        head = str(rng.randint(1, 9)) + "".join(str(rng.randrange(10)) for _ in range(9))
        value = head + str(steuer_id_check_digit(head))
        if is_valid_steuer_id(value):
            if grouped:
                return f"{value[:2]} {value[2:5]} {value[5:8]} {value[8:]}"
            return value


def _slug(text: str) -> str:
    words = ["".join(ch for ch in w if ch.isalnum()) for w in ascii_fold(text).lower().split()]
    return "-".join(w for w in words if w)


class GermanIdentities(IdentityGenerator):
    """German people (given name first), addresses, Steuer-IDs, IBANs and companies."""

    def __init__(self, rng: random.Random) -> None:
        super().__init__(rng, "de")

    def _name(self, gender: str) -> tuple[str, str, str]:
        given = self.rng.choice(_GIVEN_F if gender == "f" else _GIVEN_M)
        family = self.rng.choice(_FAMILY)
        if self.rng.random() < 0.06:  # a double-barrelled surname
            other = self.rng.choice(_FAMILY)
            if other != family:
                family = f"{family}-{other}"
        return given, family, f"{given} {family}"

    def date(self, day: dt.date) -> str:
        style = self.rng.randrange(4)
        if style == 0:
            return f"{day.day:02d}.{day.month:02d}.{day.year}"
        if style == 1:
            return f"{day.day}. {_MONTHS[day.month - 1]} {day.year}"
        if style == 2:
            return f"{day.day}.{day.month}.{day.year}"
        return day.isoformat()

    def address(self, town_index: int | None = None) -> str:
        """``<street> <number>[<letter>], <postcode> <town>``."""
        index = town_index if town_index is not None else self.rng.randrange(len(_TOWNS))
        town, _, codes = _TOWNS[index]
        number = str(self.rng.randint(1, 160))
        if self.rng.random() < 0.12:
            number += self.rng.choice("abc")
        street = self.rng.choice(_STREETS)
        self._street_tokens.update(street.split())
        return f"{street} {number}, {self.rng.choice(codes)} {town}"

    def phone(self) -> str:
        area, block = self.rng.choice(_PHONE_BLOCKS)
        tail = f"{self.rng.randint(0, 999):03d}"
        return self.rng.choice(
            [
                f"{area} {block}{tail}",
                f"{area} {block} {tail}",
                f"({area}) {block}{tail}",
                f"{area}/{block}{tail}",
                f"+49 {area[1:]} {block}{tail}",
            ]
        )

    def plate(self, town_index: int | None = None) -> str:
        prefix = _TOWNS[town_index if town_index is not None else self.rng.randrange(len(_TOWNS))][
            1
        ]
        letters = "".join(self.rng.choice("ABCDEFGHJKLMNPRSTUVWXYZ") for _ in range(2))
        return f"{prefix}-{letters} {self.rng.randint(1, 9999)}"

    def bank_account(self) -> str:
        bban = str(self.rng.randint(1, 8)) + "".join(str(self.rng.randrange(10)) for _ in range(17))
        return iban("DE", bban, grouped=self.rng.random() < 0.75)

    def id_document(self) -> str:
        return self.rng.choice("CFGHJKLMNPRTVWXYZ") + "".join(
            self.rng.choice(_ID_ALPHABET) for _ in range(8)
        )

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
            id_document=self.id_document(),
            bank_account=self.bank_account(),
            plate=self.plate(),
            steuer_id=steuer_id(self.rng, grouped=self.rng.random() < 0.5),
        )

    def company(self) -> Company:
        short = f"{self.rng.choice(_COMPANY_A)} {self.rng.choice(_COMPANY_B)}"
        return Company(
            org_name=f"{short} {self.rng.choice(_LEGAL_FORMS)}",
            short_name=short,
            address=self.address(),
            email=f"{self.rng.choice(['info', 'kontakt', 'buchhaltung'])}@{_slug(short)}.example",
            phone=self.phone(),
            bank_account=self.bank_account(),
        )

    def property(self) -> Property:
        return Property(address=self.address())

    def institution(self, kind: str = "court") -> Institution:
        index = self.rng.randrange(len(_TOWNS))
        town = _TOWNS[index][0]
        if kind == "court":
            name, mailbox = f"Amtsgericht {town}", f"poststelle@ag-{_slug(town)}.example"
        else:
            name, mailbox = f"Bürgeramt {town}", f"buergeramt@{_slug(town)}-stadt.example"
        return Institution(
            org_name=name, address=self.address(index), phone=self.phone(), email=mailbox
        )
