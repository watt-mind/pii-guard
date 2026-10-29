"""Fictional name packs and name forms for the v4.1 court-style corpus (LAB-1539).

Fictional data only (ADR 0005). As in ``eu_identities.py``, a person is a common given name and
a common surname of the language combined at random, so nobody generated is a real person; an
address is a random house number on a common street name of a real town. Company names are
invented words plus the local legal form. Latvian, Lithuanian, Croatian and Slovenian reuse the
packs and declension rules of ``eu_identities.py``.

:func:`name_forms` returns a regular expression for one name token in any form a sentence can
put it in. For the case-rich languages it is the stem (the token without its final vowels,
at least four letters) followed by up to five letters, plus the language's known stem changes
(Finnish ``-nen`` -> ``-se-``, Hungarian assimilated ``-val``); for Germanic languages the
genitive ``-s``; Irish adds the initial mutations. The rules are generous on purpose: a form
only becomes a label where the planted name occurs, and the Glimmer pass excludes anything
it disagrees with from the loss.
"""

# Name lists in Cyrillic and Greek script: look-alike letters are the point.
# ruff: noqa: RUF001

from __future__ import annotations

import re
from dataclasses import dataclass

import eu_identities as eui


@dataclass(frozen=True, slots=True)
class Pack:
    code: str
    name: str
    given_m: tuple[str, ...]
    given_f: tuple[str, ...]
    #: (masculine form, feminine form); the same string twice where the surname is invariant.
    surnames: tuple[tuple[str, str], ...]
    towns: tuple[tuple[str, str], ...]  # (town, postcode)
    streets: tuple[str, ...]
    address_format: str  # {street} {num} {post} {town}
    company_forms: tuple[str, ...]
    date_format: str  # {d} {m} {y}, zero-padded d/m
    honorifics: str  # shown to the writer: how courts in this language address parties
    inflects: bool


def _inv(*names: str) -> tuple[tuple[str, str], ...]:
    return tuple((n, n) for n in names)


def _pairs(*pairs: str) -> tuple[tuple[str, str], ...]:
    out = []
    for p in pairs:
        m, _, f = p.partition("/")
        out.append((m, f or m))
    return tuple(out)


PACKS: dict[str, Pack] = {}


def _add(pack: Pack) -> None:
    PACKS[pack.code] = pack


_add(
    Pack(
        "bg",
        "Bulgarian",
        (
            "Георги",
            "Иван",
            "Димитър",
            "Николай",
            "Петър",
            "Христо",
            "Стоян",
            "Тодор",
            "Васил",
            "Кирил",
            "Атанас",
            "Стефан",
        ),
        (
            "Мария",
            "Елена",
            "Иванка",
            "Десислава",
            "Цветелина",
            "Гергана",
            "Надежда",
            "Росица",
            "Теодора",
            "Радост",
            "Милена",
            "Силвия",
        ),
        _pairs(
            "Петров/Петрова",
            "Георгиев/Георгиева",
            "Димитров/Димитрова",
            "Николов/Николова",
            "Стоянов/Стоянова",
            "Христов/Христова",
            "Тодоров/Тодорова",
            "Илиев/Илиева",
            "Василев/Василева",
            "Атанасов/Атанасова",
            "Ангелов/Ангелова",
            "Маринов/Маринова",
            "Костадинов/Костадинова",
            "Колев/Колева",
        ),
        (("Пловдив", "4000"), ("Варна", "9000"), ("Бургас", "8000"), ("Русе", "7000")),
        (
            "ул. „Иван Вазов“",
            "бул. „България“",
            "ул. „Шипка“",
            "ул. „Христо Ботев“",
            "ул. „Раковски“",
        ),
        "{street} № {num}, {post} {town}",
        ("ООД", "ЕООД", "АД"),
        "{d}.{m}.{y} г.",
        "господин / госпожа (г-н, г-жа), ищецът, ответникът",
        False,
    )
)
_add(
    Pack(
        "cs",
        "Czech",
        (
            "Jan",
            "Petr",
            "Tomáš",
            "Martin",
            "Pavel",
            "Jiří",
            "Lukáš",
            "Ondřej",
            "Michal",
            "Jakub",
            "Vojtěch",
            "Radek",
        ),
        (
            "Jana",
            "Eva",
            "Hana",
            "Lucie",
            "Kateřina",
            "Veronika",
            "Tereza",
            "Martina",
            "Lenka",
            "Petra",
            "Zuzana",
            "Markéta",
        ),
        _pairs(
            "Novák/Nováková",
            "Svoboda/Svobodová",
            "Dvořák/Dvořáková",
            "Černý/Černá",
            "Procházka/Procházková",
            "Kučera/Kučerová",
            "Veselý/Veselá",
            "Horák/Horáková",
            "Němec/Němcová",
            "Pokorný/Pokorná",
            "Marek/Marková",
            "Pospíšil/Pospíšilová",
            "Hájek/Hájková",
            "Král/Králová",
        ),
        (("Brno", "602 00"), ("Ostrava", "702 00"), ("Plzeň", "301 00"), ("Olomouc", "779 00")),
        ("Masarykova", "Husova", "Palackého", "Nádražní", "Komenského"),
        "{street} {num}, {post} {town}",
        ("s.r.o.", "a.s."),
        "{d}. {m}. {y}",
        "pan / paní, žalobce, žalovaný, svědek",
        True,
    )
)
_add(
    Pack(
        "da",
        "Danish",
        (
            "Søren",
            "Jens",
            "Mikkel",
            "Anders",
            "Lars",
            "Rasmus",
            "Frederik",
            "Henrik",
            "Morten",
            "Christian",
            "Niels",
            "Mads",
        ),
        (
            "Mette",
            "Anne",
            "Camilla",
            "Louise",
            "Sofie",
            "Line",
            "Maria",
            "Pernille",
            "Trine",
            "Ida",
            "Helle",
            "Katrine",
        ),
        _inv(
            "Nielsen",
            "Jensen",
            "Hansen",
            "Pedersen",
            "Andersen",
            "Christensen",
            "Larsen",
            "Sørensen",
            "Rasmussen",
            "Jørgensen",
            "Madsen",
            "Kristensen",
            "Olsen",
            "Thomsen",
        ),
        (("Aarhus", "8000"), ("Odense", "5000"), ("Aalborg", "9000"), ("Esbjerg", "6700")),
        ("Vestergade", "Søndergade", "Nørregade", "Skolevej", "Kirkevej"),
        "{street} {num}, {post} {town}",
        ("ApS", "A/S"),
        "{d}.{m}.{y}",
        "sagsøger, sagsøgte, vidnet (no honorifics; surname alone after the first mention)",
        False,
    )
)
_add(
    Pack(
        "de",
        "German",
        (
            "Thomas",
            "Michael",
            "Andreas",
            "Stefan",
            "Markus",
            "Jürgen",
            "Frank",
            "Matthias",
            "Tobias",
            "Florian",
            "Uwe",
            "Klaus",
        ),
        (
            "Sabine",
            "Andrea",
            "Claudia",
            "Petra",
            "Katrin",
            "Julia",
            "Stefanie",
            "Monika",
            "Nicole",
            "Anja",
            "Birgit",
            "Susanne",
        ),
        _inv(
            "Müller",
            "Schmidt",
            "Schneider",
            "Fischer",
            "Weber",
            "Meyer",
            "Wagner",
            "Becker",
            "Schulz",
            "Hoffmann",
            "Koch",
            "Richter",
            "Wolf",
            "Schröder",
        ),
        (("Leipzig", "04109"), ("Bielefeld", "33602"), ("Augsburg", "86150"), ("Kassel", "34117")),
        ("Bahnhofstraße", "Lindenstraße", "Schillerstraße", "Gartenweg", "Bergstraße"),
        "{street} {num}, {post} {town}",
        ("GmbH", "KG", "GmbH & Co. KG"),
        "{d}.{m}.{y}",
        "Herr / Frau, der Kläger, die Beklagte, der Zeuge",
        False,
    )
)
_add(
    Pack(
        "el",
        "Greek",
        (
            "Γιώργος",
            "Δημήτρης",
            "Νίκος",
            "Κώστας",
            "Γιάννης",
            "Παναγιώτης",
            "Βασίλης",
            "Χρήστος",
            "Αθανάσιος",
            "Μιχάλης",
            "Σπύρος",
            "Ευάγγελος",
        ),
        (
            "Μαρία",
            "Ελένη",
            "Αικατερίνη",
            "Βασιλική",
            "Σοφία",
            "Αναστασία",
            "Δέσποινα",
            "Ευαγγελία",
            "Γεωργία",
            "Χριστίνα",
            "Ειρήνη",
            "Παναγιώτα",
        ),
        _pairs(
            "Παπαδόπουλος/Παπαδοπούλου",
            "Γεωργίου/Γεωργίου",
            "Οικονόμου/Οικονόμου",
            "Νικολάου/Νικολάου",
            "Παπαδάκης/Παπαδάκη",
            "Βασιλείου/Βασιλείου",
            "Κωνσταντίνου/Κωνσταντίνου",
            "Ιωάννου/Ιωάννου",
            "Μακρής/Μακρή",
            "Αλεξίου/Αλεξίου",
            "Καραγιάννης/Καραγιάννη",
            "Παππάς/Παππά",
            "Δημητρίου/Δημητρίου",
            "Αντωνίου/Αντωνίου",
        ),
        (("Πάτρα", "262 21"), ("Λάρισα", "412 22"), ("Ηράκλειο", "712 02"), ("Βόλος", "382 21")),
        ("οδός Ερμού", "οδός Αθηνάς", "οδός Κολοκοτρώνη", "οδός Μαιζώνος", "οδός Κορίνθου"),
        "{street} {num}, {post} {town}",
        ("Ε.Π.Ε.", "Ι.Κ.Ε.", "Α.Ε."),
        "{d}/{m}/{y}",
        "κ. / κα (κύριος, κυρία), ο ενάγων, η εναγομένη, ο μάρτυρας",
        True,
    )
)
_add(
    Pack(
        "en",
        "English",
        (
            "James",
            "David",
            "Daniel",
            "Thomas",
            "Matthew",
            "Andrew",
            "Richard",
            "Mark",
            "Paul",
            "Simon",
            "Peter",
            "Graham",
        ),
        (
            "Sarah",
            "Emma",
            "Rachel",
            "Laura",
            "Claire",
            "Helen",
            "Rebecca",
            "Joanne",
            "Victoria",
            "Hannah",
            "Louise",
            "Amanda",
        ),
        _inv(
            "Thompson",
            "Walker",
            "Robinson",
            "Wright",
            "Hughes",
            "Edwards",
            "Turner",
            "Parker",
            "Collins",
            "Morgan",
            "Bennett",
            "Cooper",
            "Fletcher",
            "Harrison",
        ),
        (
            ("Leeds", "LS1 4AP"),
            ("Bristol", "BS1 5TR"),
            ("Nottingham", "NG1 6FB"),
            ("Sheffield", "S1 2HE"),
        ),
        ("Station Road", "Church Lane", "Victoria Street", "Mill Lane", "Park Avenue"),
        "{num} {street}, {town} {post}",
        ("Ltd", "Limited"),
        "{d}/{m}/{y}",
        "Mr / Mrs / Ms, the claimant, the defendant, the witness",
        False,
    )
)
_add(
    Pack(
        "es",
        "Spanish",
        (
            "Javier",
            "Carlos",
            "Antonio",
            "Manuel",
            "Francisco",
            "Miguel",
            "Alejandro",
            "Pablo",
            "Sergio",
            "Jorge",
            "Rubén",
            "Álvaro",
        ),
        (
            "María",
            "Carmen",
            "Lucía",
            "Laura",
            "Marta",
            "Elena",
            "Isabel",
            "Pilar",
            "Cristina",
            "Raquel",
            "Beatriz",
            "Silvia",
        ),
        _inv(
            "García",
            "Fernández",
            "González",
            "Rodríguez",
            "López",
            "Martínez",
            "Sánchez",
            "Pérez",
            "Gómez",
            "Martín",
            "Jiménez",
            "Ruiz",
            "Moreno",
            "Navarro",
        ),
        (("Zaragoza", "50001"), ("Valladolid", "47001"), ("Málaga", "29001"), ("Murcia", "30001")),
        (
            "Calle Mayor",
            "Calle del Carmen",
            "Avenida de la Constitución",
            "Calle Real",
            "Calle San Juan",
        ),
        "{street}, {num}, {post} {town}",
        ("S.L.", "S.A."),
        "{d}/{m}/{y}",
        "don / doña (D., D.ª), la parte demandante, el demandado, el testigo",
        False,
    )
)
_add(
    Pack(
        "et",
        "Estonian",
        (
            "Andres",
            "Jaan",
            "Margus",
            "Rein",
            "Toomas",
            "Priit",
            "Tarmo",
            "Indrek",
            "Urmas",
            "Kalev",
            "Siim",
            "Martin",
        ),
        (
            "Kadri",
            "Tiina",
            "Katrin",
            "Piret",
            "Kristi",
            "Maarja",
            "Liis",
            "Anu",
            "Triin",
            "Kersti",
            "Eve",
            "Merike",
        ),
        _inv(
            "Tamm",
            "Saar",
            "Sepp",
            "Mägi",
            "Kask",
            "Kukk",
            "Rebane",
            "Ilves",
            "Pärn",
            "Koppel",
            "Lepik",
            "Kuusk",
            "Oja",
            "Raud",
        ),
        (("Tartu", "50103"), ("Pärnu", "80010"), ("Narva", "20308"), ("Viljandi", "71004")),
        ("Pikk tänav", "Kooli tänav", "Aia tänav", "Rüütli tänav", "Jaama tänav"),
        "{street} {num}, {post} {town}",
        ("OÜ", "AS"),
        "{d}.{m}.{y}",
        "hageja, kostja, tunnistaja (honorifics härra / proua are rare; surname alone is usual)",
        True,
    )
)
_add(
    Pack(
        "fi",
        "Finnish",
        (
            "Mikko",
            "Juha",
            "Timo",
            "Jari",
            "Antti",
            "Matti",
            "Petri",
            "Jukka",
            "Ville",
            "Sami",
            "Kari",
            "Janne",
        ),
        (
            "Anna",
            "Laura",
            "Johanna",
            "Minna",
            "Sanna",
            "Heidi",
            "Riikka",
            "Katja",
            "Elina",
            "Tiina",
            "Satu",
            "Hanna",
        ),
        _inv(
            "Virtanen",
            "Korhonen",
            "Nieminen",
            "Mäkinen",
            "Hämäläinen",
            "Laine",
            "Heikkinen",
            "Koskinen",
            "Järvinen",
            "Lehtonen",
            "Saarinen",
            "Salminen",
            "Heinonen",
            "Niemi",
        ),
        (("Tampere", "33100"), ("Turku", "20100"), ("Oulu", "90100"), ("Jyväskylä", "40100")),
        ("Kauppakatu", "Koulukatu", "Rantatie", "Puistokatu", "Asemakatu"),
        "{street} {num}, {post} {town}",
        ("Oy", "Ky"),
        "{d}.{m}.{y}",
        "kantaja, vastaaja, todistaja (no honorifics; the surname alone, declined, after the "
        "first mention)",
        True,
    )
)
_add(
    Pack(
        "fr",
        "French",
        (
            "Nicolas",
            "Julien",
            "Thomas",
            "Sébastien",
            "Laurent",
            "Philippe",
            "Pierre",
            "Antoine",
            "Mathieu",
            "Olivier",
            "Jérôme",
            "Vincent",
        ),
        (
            "Isabelle",
            "Nathalie",
            "Sophie",
            "Céline",
            "Aurélie",
            "Camille",
            "Claire",
            "Émilie",
            "Julie",
            "Sandrine",
            "Valérie",
            "Hélène",
        ),
        _inv(
            "Martin",
            "Bernard",
            "Dubois",
            "Durand",
            "Lefèvre",
            "Moreau",
            "Laurent",
            "Girard",
            "Roux",
            "Fournier",
            "Mercier",
            "Lambert",
            "Bonnet",
            "Faure",
        ),
        (("Lyon", "69002"), ("Toulouse", "31000"), ("Nantes", "44000"), ("Rennes", "35000")),
        (
            "rue de la République",
            "rue Victor Hugo",
            "avenue Jean Jaurès",
            "rue du Moulin",
            "boulevard Gambetta",
        ),
        "{num} {street}, {post} {town}",
        ("SARL", "SAS"),
        "{d}/{m}/{y}",
        "M. / Mme, le demandeur, la défenderesse, le témoin, la société",
        False,
    )
)
_add(
    Pack(
        "ga",
        "Irish",
        (
            "Seán",
            "Pádraig",
            "Ciarán",
            "Eoin",
            "Colm",
            "Dónall",
            "Tomás",
            "Niall",
            "Diarmuid",
            "Cathal",
            "Liam",
            "Máirtín",
        ),
        (
            "Áine",
            "Siobhán",
            "Niamh",
            "Caitríona",
            "Gráinne",
            "Róisín",
            "Orla",
            "Sinéad",
            "Méabh",
            "Úna",
            "Bríd",
            "Clíona",
        ),
        _pairs(
            "Ó Briain/Ní Bhriain",
            "Ó Murchú/Ní Mhurchú",
            "Ó Súilleabháin/Ní Shúilleabháin",
            "Mac Carthaigh/Nic Carthaigh",
            "Ó Conaill/Ní Chonaill",
            "Ó Dónaill/Ní Dhónaill",
            "Mac Mathúna/Nic Mhathúna",
            "Ó Ceallaigh/Ní Cheallaigh",
            "Breathnach/Breathnach",
            "Ó Néill/Ní Néill",
            "Ó Riain/Ní Riain",
            "Mac Gearailt/Nic Gearailt",
            "Ó Flaithearta/Ní Fhlaithearta",
            "Seoighe/Seoighe",
        ),
        (
            ("Gaillimh", "H91 E2K8"),
            ("Corcaigh", "T12 R5CP"),
            ("Luimneach", "V94 T9PX"),
            ("Port Láirge", "X91 K0EK"),
        ),
        (
            "Sráid an Droichid",
            "Bóthar na Trá",
            "Sráid na hEaglaise",
            "Bóthar an Mhuilinn",
            "Sráid Mhór",
        ),
        "{num} {street}, {town}, {post}",
        ("Teoranta", "Teo."),
        "{d}/{m}/{y}",
        "an tUasal / Bean (an tUas.), an t-iarratasóir, an freagróir, an finné",
        True,
    )
)
_add(
    Pack(
        "hu",
        "Hungarian",
        (
            "László",
            "István",
            "Gábor",
            "Zoltán",
            "Péter",
            "Attila",
            "Tamás",
            "Ferenc",
            "Sándor",
            "Balázs",
            "Csaba",
            "Róbert",
        ),
        (
            "Katalin",
            "Erzsébet",
            "Zsuzsanna",
            "Andrea",
            "Mónika",
            "Krisztina",
            "Eszter",
            "Judit",
            "Anita",
            "Ildikó",
            "Beáta",
            "Edit",
        ),
        _inv(
            "Nagy",
            "Kovács",
            "Tóth",
            "Szabó",
            "Horváth",
            "Varga",
            "Kiss",
            "Molnár",
            "Németh",
            "Farkas",
            "Balogh",
            "Papp",
            "Takács",
            "Juhász",
        ),
        (("Debrecen", "4024"), ("Szeged", "6720"), ("Pécs", "7621"), ("Győr", "9021")),
        ("Petőfi utca", "Kossuth Lajos utca", "Rákóczi út", "Ady Endre utca", "Fő utca"),
        "{post} {town}, {street} {num}.",
        ("Kft.", "Zrt.", "Bt."),
        "{y}. {m}. {d}.",
        "a felperes, az alperes, a tanú (surname with or without given name; the -né form)",
        True,
    )
)
_add(
    Pack(
        "it",
        "Italian",
        (
            "Marco",
            "Alessandro",
            "Andrea",
            "Luca",
            "Giuseppe",
            "Francesco",
            "Matteo",
            "Stefano",
            "Davide",
            "Roberto",
            "Paolo",
            "Simone",
        ),
        (
            "Giulia",
            "Francesca",
            "Chiara",
            "Sara",
            "Valentina",
            "Elena",
            "Silvia",
            "Laura",
            "Federica",
            "Martina",
            "Alessandra",
            "Paola",
        ),
        _inv(
            "Rossi",
            "Russo",
            "Ferrari",
            "Esposito",
            "Bianchi",
            "Romano",
            "Colombo",
            "Ricci",
            "Marino",
            "Greco",
            "Bruno",
            "Gallo",
            "Conti",
            "Costa",
        ),
        (("Bologna", "40121"), ("Torino", "10121"), ("Firenze", "50122"), ("Verona", "37121")),
        ("Via Roma", "Via Garibaldi", "Corso Vittorio Emanuele", "Via Mazzini", "Via Dante"),
        "{street} {num}, {post} {town}",
        ("S.r.l.", "S.p.A."),
        "{d}/{m}/{y}",
        "il sig. / la sig.ra, l'attore, la convenuta, il testimone",
        False,
    )
)
_add(
    Pack(
        "mt",
        "Maltese",
        (
            "Joseph",
            "John",
            "Mario",
            "Carmel",
            "Anthony",
            "Paul",
            "Charles",
            "Michael",
            "Daniel",
            "Mark",
            "Ġorġ",
            "Pawlu",
        ),
        (
            "Maria",
            "Rita",
            "Doris",
            "Carmen",
            "Josephine",
            "Marija",
            "Antoinette",
            "Claire",
            "Roberta",
            "Sharon",
            "Graziella",
            "Anna",
        ),
        _inv(
            "Borg",
            "Camilleri",
            "Vella",
            "Farrugia",
            "Zammit",
            "Galea",
            "Micallef",
            "Grech",
            "Attard",
            "Spiteri",
            "Azzopardi",
            "Mifsud",
            "Agius",
            "Cassar",
        ),
        (
            ("Birkirkara", "BKR 1010"),
            ("Ħaż-Żabbar", "ZBR 1020"),
            ("Il-Mosta", "MST 1030"),
            ("Ħal Qormi", "QRM 1040"),
        ),
        (
            "Triq il-Kbira",
            "Triq il-Knisja",
            "Triq San Pawl",
            "Triq il-Mitħna",
            "Triq ir-Repubblika",
        ),
        "{num}, {street}, {town} {post}",
        ("Limited", "Ltd"),
        "{d}/{m}/{y}",
        "is-Sur / is-Sinjura, ir-rikorrent, l-intimat, ix-xhud",
        False,
    )
)
_add(
    Pack(
        "nl",
        "Dutch",
        (
            "Jan",
            "Pieter",
            "Dirk",
            "Bas",
            "Thijs",
            "Joost",
            "Ruud",
            "Sander",
            "Maarten",
            "Wouter",
            "Erik",
            "Gert",
        ),
        (
            "Anouk",
            "Ingrid",
            "Marieke",
            "Sanne",
            "Femke",
            "Linda",
            "Esther",
            "Judith",
            "Lotte",
            "Annemiek",
            "Petra",
            "Karin",
        ),
        _inv(
            "de Vries",
            "Jansen",
            "Bakker",
            "Visser",
            "Smit",
            "Meijer",
            "de Boer",
            "Mulder",
            "de Groot",
            "Bos",
            "Vos",
            "Peters",
            "Hendriks",
            "van Dijk",
        ),
        (
            ("Utrecht", "3511 AB"),
            ("Eindhoven", "5611 CD"),
            ("Groningen", "9711 EF"),
            ("Tilburg", "5038 GH"),
        ),
        ("Kerkstraat", "Dorpsstraat", "Molenweg", "Stationsweg", "Schoolstraat"),
        "{street} {num}, {post} {town}",
        ("B.V.", "V.O.F."),
        "{d}-{m}-{y}",
        "de heer / mevrouw (dhr., mevr.), eiser, gedaagde, de getuige",
        False,
    )
)
_add(
    Pack(
        "pl",
        "Polish",
        (
            "Piotr",
            "Krzysztof",
            "Tomasz",
            "Paweł",
            "Michał",
            "Marcin",
            "Grzegorz",
            "Andrzej",
            "Łukasz",
            "Jakub",
            "Adam",
            "Rafał",
        ),
        (
            "Anna",
            "Katarzyna",
            "Magdalena",
            "Agnieszka",
            "Joanna",
            "Małgorzata",
            "Ewa",
            "Monika",
            "Aleksandra",
            "Barbara",
            "Dorota",
            "Justyna",
        ),
        _pairs(
            "Nowak/Nowak",
            "Kowalski/Kowalska",
            "Wiśniewski/Wiśniewska",
            "Wójcik/Wójcik",
            "Kowalczyk/Kowalczyk",
            "Kamiński/Kamińska",
            "Lewandowski/Lewandowska",
            "Zieliński/Zielińska",
            "Szymański/Szymańska",
            "Woźniak/Woźniak",
            "Dąbrowski/Dąbrowska",
            "Kozłowski/Kozłowska",
            "Mazur/Mazur",
            "Krawczyk/Krawczyk",
        ),
        (("Kraków", "30-001"), ("Wrocław", "50-001"), ("Poznań", "60-001"), ("Gdańsk", "80-001")),
        ("ul. Mickiewicza", "ul. Kościuszki", "ul. Słowackiego", "ul. Ogrodowa", "ul. Polna"),
        "{street} {num}, {post} {town}",
        ("sp. z o.o.", "S.A."),
        "{d}.{m}.{y}",
        "pan / pani, powód, pozwana, świadek",
        True,
    )
)
_add(
    Pack(
        "pt",
        "Portuguese",
        (
            "João",
            "José",
            "António",
            "Pedro",
            "Miguel",
            "Rui",
            "Nuno",
            "Tiago",
            "Ricardo",
            "Paulo",
            "Bruno",
            "Luís",
        ),
        (
            "Ana",
            "Maria",
            "Sofia",
            "Inês",
            "Catarina",
            "Joana",
            "Marta",
            "Rita",
            "Patrícia",
            "Helena",
            "Teresa",
            "Cláudia",
        ),
        _inv(
            "Silva",
            "Santos",
            "Ferreira",
            "Pereira",
            "Oliveira",
            "Costa",
            "Rodrigues",
            "Martins",
            "Sousa",
            "Fernandes",
            "Gonçalves",
            "Gomes",
            "Lopes",
            "Carvalho",
        ),
        (
            ("Porto", "4000-322"),
            ("Braga", "4700-435"),
            ("Coimbra", "3000-150"),
            ("Aveiro", "3810-200"),
        ),
        (
            "Rua Direita",
            "Avenida da Liberdade",
            "Rua de Santo António",
            "Rua do Comércio",
            "Rua da Escola",
        ),
        "{street}, n.º {num}, {post} {town}",
        ("Lda.", "S.A."),
        "{d}/{m}/{y}",
        "o Sr. / a Sr.ª, o autor, a ré, a testemunha",
        False,
    )
)
_add(
    Pack(
        "ro",
        "Romanian",
        (
            "Andrei",
            "Mihai",
            "Alexandru",
            "Ion",
            "Florin",
            "Cristian",
            "Bogdan",
            "Adrian",
            "Radu",
            "Gabriel",
            "Ionuț",
            "Vasile",
        ),
        (
            "Elena",
            "Ioana",
            "Maria",
            "Andreea",
            "Mihaela",
            "Cristina",
            "Alina",
            "Gabriela",
            "Ana",
            "Simona",
            "Daniela",
            "Roxana",
        ),
        _inv(
            "Popescu",
            "Ionescu",
            "Popa",
            "Stan",
            "Dumitru",
            "Constantin",
            "Stoica",
            "Gheorghe",
            "Munteanu",
            "Rusu",
            "Matei",
            "Lazăr",
            "Moldovan",
            "Ciobanu",
        ),
        (
            ("Cluj-Napoca", "400001"),
            ("Iași", "700001"),
            ("Timișoara", "300001"),
            ("Brașov", "500001"),
        ),
        (
            "Strada Mihai Eminescu",
            "Strada Republicii",
            "Bulevardul Unirii",
            "Strada Florilor",
            "Strada Morii",
        ),
        "{street} nr. {num}, {town} {post}",
        ("S.R.L.", "S.A."),
        "{d}.{m}.{y}",
        "domnul / doamna (dl., dna.), reclamantul, pârâta, martorul",
        True,
    )
)
_add(
    Pack(
        "sk",
        "Slovak",
        (
            "Peter",
            "Martin",
            "Ján",
            "Michal",
            "Tomáš",
            "Jozef",
            "Marek",
            "Lukáš",
            "Juraj",
            "Milan",
            "Róbert",
            "Matej",
        ),
        (
            "Jana",
            "Mária",
            "Zuzana",
            "Katarína",
            "Lucia",
            "Martina",
            "Monika",
            "Eva",
            "Andrea",
            "Veronika",
            "Ivana",
            "Silvia",
        ),
        _pairs(
            "Horváth/Horváthová",
            "Kováč/Kováčová",
            "Varga/Vargová",
            "Tóth/Tóthová",
            "Nagy/Nagyová",
            "Baláž/Balážová",
            "Szabó/Szabóová",
            "Molnár/Molnárová",
            "Lukáč/Lukáčová",
            "Kollár/Kollárová",
            "Mészáros/Mészárosová",
            "Polák/Poláková",
            "Kováčik/Kováčiková",
            "Krajčovič/Krajčovičová",
        ),
        (("Košice", "040 01"), ("Prešov", "080 01"), ("Žilina", "010 01"), ("Nitra", "949 01")),
        ("Hlavná", "Školská", "Záhradná", "Štúrova", "Námestie SNP"),
        "{street} {num}, {post} {town}",
        ("s.r.o.", "a.s."),
        "{d}. {m}. {y}",
        "pán / pani, žalobca, žalovaná, svedok",
        True,
    )
)
_add(
    Pack(
        "sv",
        "Swedish",
        (
            "Erik",
            "Lars",
            "Anders",
            "Johan",
            "Per",
            "Mikael",
            "Fredrik",
            "Magnus",
            "Henrik",
            "Daniel",
            "Jonas",
            "Mattias",
        ),
        (
            "Anna",
            "Eva",
            "Karin",
            "Maria",
            "Sara",
            "Emma",
            "Elin",
            "Malin",
            "Johanna",
            "Sofia",
            "Linnea",
            "Ingrid",
        ),
        _inv(
            "Andersson",
            "Johansson",
            "Karlsson",
            "Nilsson",
            "Eriksson",
            "Larsson",
            "Olsson",
            "Persson",
            "Svensson",
            "Gustafsson",
            "Lindberg",
            "Lindqvist",
            "Berg",
            "Holm",
        ),
        (
            ("Göteborg", "411 01"),
            ("Malmö", "211 20"),
            ("Uppsala", "753 20"),
            ("Linköping", "582 22"),
        ),
        ("Storgatan", "Kyrkogatan", "Drottninggatan", "Skolgatan", "Ringvägen"),
        "{street} {num}, {post} {town}",
        ("AB", "HB"),
        "{y}-{m}-{d}",
        "käranden, svaranden, vittnet (no honorifics; surname alone after the first mention)",
        False,
    )
)


def _from_eu(lang: eui.Lang, honorifics: str) -> Pack:
    surnames = tuple((m, f[0]) for m, f in lang.surnames) + tuple(
        (m, alt) for m, f in lang.surnames for alt in f[1:]
    )
    return Pack(
        lang.code, lang.name, lang.given_m, lang.given_f, surnames,
        tuple((t, p[0]) for t, p, _, _ in lang.towns), lang.streets,
        lang.address_format, lang.company_forms, "{d}.{m}.{y}", honorifics, True,
    )  # fmt: skip


for _lang, _hon in (
    (eui.LV, "prasītājs, atbildētāja, liecinieks (kungs / kundze after the surname)"),
    (eui.LT, "ieškovas, atsakovė, liudytojas (ponas / ponia)"),
    (eui.HR, "tužitelj, tuženica, svjedok (gospodin / gospođa)"),
    (eui.SL, "tožnik, toženka, priča (gospod / gospa)"),
):
    _add(_from_eu(_lang, _hon))

#: The 21 MAPA languages, then hr, sl and pl.
LANGUAGES = [
    "bg",
    "cs",
    "da",
    "de",
    "el",
    "en",
    "es",
    "et",
    "fi",
    "fr",
    "ga",
    "hu",
    "it",
    "lt",
    "lv",
    "mt",
    "nl",
    "pt",
    "ro",
    "sk",
    "sv",
    "hr",
    "sl",
    "pl",
]

#: Invented company words (no real company): combined with a legal form of the language.
COMPANY_WORDS = (
    "Velmora", "Korvex", "Ambrino", "Stellwyn", "Tavira", "Nordelo", "Brivant", "Quelmar",
    "Ostrelia", "Cavendo", "Lumetra", "Fendiro", "Galvora",
    "Hestano", "Irvalo", "Jormex", "Kelvana", "Lisoro", "Montevar", "Nubiro", "Orvela",
    "Pellano", "Ristova", "Solvita", "Trevano", "Ulmaro", "Vandero", "Wenlo", "Zeltaro",
)  # fmt: skip


# --- Name forms -------------------------------------------------------------------------------

_W = r"[^\W\d_]"
_VOWELS = "aeiouyáéíóúýàèìòùäëïöüőűâêîôûãõåæøăąęėįųūāēīαεηιοωυάέήίόύώΐΰϊϋьъая" + "еёиоуюэы"


def _stem(token: str) -> str:
    s = token[:-1] if token.endswith("ς") else token
    while s and s[-1].lower() in _VOWELS:
        s = s[:-1]
    return s


def _lenite(token: str) -> str:
    if len(token) > 1 and token[0] in "BCDFGMPST" and token[1] != "h":
        return token[0] + "h" + token[1:]
    return token


#: Languages whose forms come from ``eu_identities.name_forms`` (phase 1). Fixed, so the
#: corpus rebuilds byte for byte when ``eu_identities`` gains languages (phase 1b).
EU_DECLENSION = frozenset({"lv", "lt", "hr", "sl"})


def token_pattern(code: str, token: str, gender: str, is_family: bool) -> str:
    """Regex alternatives for one name token in any form (no anchors)."""
    if code in EU_DECLENSION:
        forms = eui.name_forms(code, token, gender, is_family)
        return "|".join(re.escape(f) for f in sorted(forms, key=len, reverse=True))
    alts = {re.escape(token)}
    if code in {"de", "nl", "sv", "da", "en"}:
        alts.add(re.escape(token) + "s")
    if code == "ga":
        alts |= {re.escape(_lenite(token)), re.escape(_lenite(token)) + _W + "{0,3}"}
        alts.add(re.escape(token) + _W + "{0,3}")
        if token in {"Ó"}:
            alts |= {"Uí", "Ua"}
        if token == "Mac":  # noqa: S105 - an Irish name particle
            alts |= {"Mhic", "Mic"}
        if token in {"Ní", "Nic"}:
            alts |= {"Bean Uí", "Uí"}
    if PACKS[code].inflects and code != "ga":
        stem = _stem(token)
        if len(stem) >= 4 or (len(stem) >= 3 and len(token) <= 4):
            alts.add(re.escape(stem) + _W + "{0,5}")
        if code == "fi" and token.endswith("nen"):
            alts.add(re.escape(token[:-3]) + "s" + _W + "{0,5}")
        if code in {"cs", "sk", "pl"} and re.search(r"[ek][kc]$|e[lkcrn]$", token):
            alts.add(re.escape(token[:-2] + token[-1]) + _W + "{0,5}")  # Marek -> Marka
        if code == "hu":
            alts.add(re.escape(token) + _W + "{0,6}")
    return "|".join(sorted(alts, key=len, reverse=True))


def person_regex(code: str, given: str, family: str, gender: str) -> re.Pattern[str]:
    """Full name (either order), the surname alone or the given name alone, any form."""
    g = token_pattern(code, given, gender, False)
    fam_tokens = family.split()
    f = r"\s+".join(f"(?:{token_pattern(code, t, gender, True)})" for t in fam_tokens)
    return re.compile(rf"(?<!{_W})(?:(?:{g})\s+(?:{f})|(?:{f})\s+(?:{g})|(?:{f})|(?:{g}))(?!{_W})")


def given_name_regex(code: str) -> re.Pattern[str]:
    """Any given name of the pack, capitalized, in any form (to find invented people)."""
    pack = PACKS[code]
    alts = [
        token_pattern(code, g, "m", False) for g in (*pack.given_m, *pack.given_f) if len(g) >= 4
    ]
    return re.compile(rf"(?<!{_W})(?:{'|'.join(alts)})(?!{_W})")
