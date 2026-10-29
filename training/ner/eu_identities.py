"""Fictional identities and name declension for the multilingual NER phase 1 (LAB-1525).

Fictional data only (ADR 0005). Like the generator's Hungarian and English packs, a person is
a common given name and a common surname combined at random, so nobody generated is a real
person; addresses are a random house number on a common street name of a real town; phone,
ID and account numbers are random digits in the national shape (IBANs carry valid check
digits so they look real to a detector, but the bank codes are random). E-mail addresses use
the reserved ``example.*`` domains. Company names are invented two-word names plus a legal
form. Court and municipality names are the real public institutions of the towns (not
personal data).

:func:`name_forms` lists the declined forms of a name token (Latvian, Lithuanian, Croatian,
Slovenian and Romanian decline names, Irish mutates them, a Spanish surname may appear as its
first half alone, a Dutch particle is capitalised before a lone surname; a form is labelled as
a whole word, as ``hu-inflection.jsonl`` does
for Hungarian stem-changing forms). The rules are deliberately generous (they also list some
forms the language doesn't use): a form only becomes a label where the planted name occurs.

Languages: ``lv``, ``lt``, ``hr``, ``sl`` (phase 1, the weakest MAPA languages first), then
``fr``, ``es``, ``it``, ``nl``, ``ro``, ``ga``, ``mt`` (phase 1b, LAB-1534).
"""

# Seeded synthetic data: the standard PRNG is the point.

from __future__ import annotations

import datetime as dt
import random
from dataclasses import dataclass, field

from pii_guard.eval.identities import email_address, iban
from pii_guard.types import EntityType


@dataclass(frozen=True, slots=True)
class Planted:
    """One value the writing model must use (``required``) or may use (name parts)."""

    field: str
    entity_type: EntityType
    text: str
    required: bool = True
    #: For people: the given name and surname tokens, and the gender (declension).
    given: str = ""
    family: str = ""
    gender: str = ""

    def __repr__(self) -> str:  # never the value
        return f"Planted({self.field!r}, {self.entity_type.value}, required={self.required})"


@dataclass(frozen=True, slots=True)
class Lang:
    code: str
    name: str
    country: str  # IBAN country code
    given_m: tuple[str, ...]
    given_f: tuple[str, ...]
    #: (masculine form, feminine forms): surnames with gendered forms, or one form for both.
    surnames: tuple[tuple[str, tuple[str, ...]], ...]
    #: (town, postcode prefix or list, court name, municipality name)
    towns: tuple[tuple[str, tuple[str, ...], str, str], ...]
    streets: tuple[str, ...]
    address_format: str  # {street} {num} {town} {post}
    company_a: tuple[str, ...]
    company_forms: tuple[str, ...]
    company_format: str  # {form} {name}
    months_gen: tuple[str, ...]
    date_formats: tuple[str, ...]
    id_label: str
    inflection_rule: str
    extra: dict[str, str] = field(default_factory=dict)


# --- Latvian ----------------------------------------------------------------------------------

LV = Lang(
    code="lv",
    name="Latvian",
    country="LV",
    given_m=(
        "Jānis",
        "Andris",
        "Mārtiņš",
        "Edgars",
        "Kārlis",
        "Roberts",
        "Artūrs",
        "Raivis",
        "Guntis",
        "Aivars",
        "Dainis",
        "Oskars",
        "Rihards",
        "Valdis",
        "Ivars",
        "Normunds",
        "Toms",
        "Kristaps",
        "Uldis",
        "Gatis",
        "Māris",
        "Juris",
        "Ēriks",
        "Reinis",
        "Matīss",
        "Aigars",
        "Ainārs",
        "Viesturs",
        "Gints",
        "Arvis",
    ),
    given_f=(
        "Anna",
        "Līga",
        "Inese",
        "Kristīne",
        "Ilze",
        "Laura",
        "Dace",
        "Ieva",
        "Santa",
        "Elīna",
        "Agnese",
        "Zane",
        "Baiba",
        "Sanita",
        "Linda",
        "Marta",
        "Evija",
        "Iveta",
        "Madara",
        "Dagnija",
        "Gunta",
        "Alise",
        "Rūta",
        "Signe",
        "Una",
        "Liene",
        "Sandra",
        "Daiga",
        "Ligita",
        "Aija",
    ),
    surnames=(
        ("Bērziņš", ("Bērziņa",)),
        ("Kalniņš", ("Kalniņa",)),
        ("Ozoliņš", ("Ozoliņa",)),
        ("Jansons", ("Jansone",)),
        ("Ozols", ("Ozola",)),
        ("Liepiņš", ("Liepiņa",)),
        ("Krūmiņš", ("Krūmiņa",)),
        ("Balodis", ("Balode",)),
        ("Eglītis", ("Eglīte",)),
        ("Zariņš", ("Zariņa",)),
        ("Pētersons", ("Pētersone",)),
        ("Vītols", ("Vītola",)),
        ("Kļaviņš", ("Kļaviņa",)),
        ("Kārkliņš", ("Kārkliņa",)),
        ("Vanags", ("Vanaga",)),
        ("Lapiņš", ("Lapiņa",)),
        ("Siliņš", ("Siliņa",)),
        ("Jēkabsons", ("Jēkabsone",)),
        ("Zvirbulis", ("Zvirbule",)),
        ("Upītis", ("Upīte",)),
        ("Āboliņš", ("Āboliņa",)),
        ("Strazdiņš", ("Strazdiņa",)),
        ("Rozītis", ("Rozīte",)),
        ("Grīnbergs", ("Grīnberga",)),
        ("Celmiņš", ("Celmiņa",)),
        ("Lūsis", ("Lūse",)),
        ("Purviņš", ("Purviņa",)),
        ("Sproģis", ("Sproģe",)),
        ("Kalējs", ("Kalēja",)),
        ("Freimanis", ("Freimane",)),
        ("Dzenis", ("Dzene",)),
        ("Mežs", ("Meža",)),
        ("Avotiņš", ("Avotiņa",)),
        ("Bērtiņš", ("Bērtiņa",)),
        ("Leja", ("Leja",)),
        ("Gailītis", ("Gailīte",)),
    ),
    towns=(
        (
            "Rīga",
            ("LV-1001", "LV-1010", "LV-1011", "LV-1013", "LV-1039", "LV-1050", "LV-1082"),
            "Rīgas pilsētas tiesa",
            "Rīgas valstspilsētas pašvaldība",
        ),
        (
            "Daugavpils",
            ("LV-5401", "LV-5404", "LV-5417"),
            "Latgales rajona tiesa",
            "Daugavpils valstspilsētas pašvaldība",
        ),
        (
            "Liepāja",
            ("LV-3401", "LV-3405", "LV-3414"),
            "Kurzemes rajona tiesa",
            "Liepājas valstspilsētas pašvaldība",
        ),
        (
            "Jelgava",
            ("LV-3001", "LV-3002", "LV-3008"),
            "Zemgales rajona tiesa",
            "Jelgavas valstspilsētas pašvaldība",
        ),
        (
            "Jūrmala",
            ("LV-2008", "LV-2010", "LV-2015"),
            "Rīgas rajona tiesa",
            "Jūrmalas valstspilsētas pašvaldība",
        ),
        (
            "Ventspils",
            ("LV-3601", "LV-3602"),
            "Kurzemes rajona tiesa",
            "Ventspils valstspilsētas pašvaldība",
        ),
        (
            "Rēzekne",
            ("LV-4601", "LV-4604"),
            "Latgales rajona tiesa",
            "Rēzeknes valstspilsētas pašvaldība",
        ),
        (
            "Valmiera",
            ("LV-4201", "LV-4202"),
            "Vidzemes rajona tiesa",
            "Valmieras novada pašvaldība",
        ),
        ("Ogre", ("LV-5001", "LV-5003"), "Vidzemes rajona tiesa", "Ogres novada pašvaldība"),
        ("Cēsis", ("LV-4101",), "Vidzemes rajona tiesa", "Cēsu novada pašvaldība"),
        ("Tukums", ("LV-3101",), "Kurzemes rajona tiesa", "Tukuma novada pašvaldība"),
        ("Sigulda", ("LV-2150",), "Vidzemes rajona tiesa", "Siguldas novada pašvaldība"),
    ),
    streets=(
        "Brīvības iela",
        "Krasta iela",
        "Lāčplēša iela",
        "Rīgas iela",
        "Skolas iela",
        "Dzirnavu iela",
        "Meža iela",
        "Ozolu iela",
        "Liepu iela",
        "Pils iela",
        "Dārza iela",
        "Saules iela",
        "Avotu iela",
        "Stacijas iela",
        "Ezera iela",
        "Bērzu iela",
        "Ganību dambis",
        "Kalnu iela",
        "Pļavas iela",
        "Jūras iela",
    ),
    address_format="{street} {num}, {town}, {post}",
    company_a=(
        "Zaļā Birze",
        "Ozolkalns",
        "Saules Krasts",
        "Baltais Bērzs",
        "Dzintara Ceļš",
        "Rudens Lapa",
        "Zilais Ezers",
        "Meža Takas",
        "Gaišā Māja",
        "Klusā Upe",
        "Vēja Dzirnavas",
        "Sudraba Avots",
    ),
    company_forms=("SIA", "SIA", "SIA", "AS"),
    company_format='{form} "{name}"',
    months_gen=(
        "janvārī",
        "februārī",
        "martā",
        "aprīlī",
        "maijā",
        "jūnijā",
        "jūlijā",
        "augustā",
        "septembrī",
        "oktobrī",
        "novembrī",
        "decembrī",
    ),
    date_formats=("{d:02d}.{m:02d}.{y}.", "{d:02d}.{m:02d}.{y}", "{y}. gada {d}. {mon}", "{iso}"),
    id_label="personal code (personas kods)",
    inflection_rule=(
        "Decline the names of people as natural Latvian requires (Jānis Bērziņš, Jāņa "
        "Bērziņa, Jānim Bērziņam, ar Jāni Bērziņu; Līga Ozola, Līgai Ozolai). Give every "
        "person's full name at least once exactly as given, in the nominative (for example in "
        "the list of parties or the signature block); later you may use the surname or the "
        "given name alone, in any case. Write company and institution names, addresses and "
        "every number exactly as given."
    ),
)

# --- Lithuanian -------------------------------------------------------------------------------

LT = Lang(
    code="lt",
    name="Lithuanian",
    country="LT",
    given_m=(
        "Jonas",
        "Tomas",
        "Mantas",
        "Lukas",
        "Darius",
        "Andrius",
        "Paulius",
        "Mindaugas",
        "Vytautas",
        "Giedrius",
        "Rokas",
        "Marius",
        "Tadas",
        "Dovydas",
        "Justinas",
        "Kęstutis",
        "Aurimas",
        "Edvinas",
        "Linas",
        "Saulius",
        "Gediminas",
        "Arnas",
        "Žygimantas",
        "Povilas",
        "Ignas",
        "Karolis",
        "Algirdas",
        "Rimantas",
    ),
    given_f=(
        "Rūta",
        "Ieva",
        "Eglė",
        "Greta",
        "Jurgita",
        "Laura",
        "Kristina",
        "Agnė",
        "Indrė",
        "Gintarė",
        "Aistė",
        "Milda",
        "Rasa",
        "Simona",
        "Austėja",
        "Vaida",
        "Lina",
        "Inga",
        "Dalia",
        "Neringa",
        "Gabija",
        "Ugnė",
        "Jolanta",
        "Viktorija",
        "Asta",
        "Daiva",
    ),
    surnames=(
        ("Kazlauskas", ("Kazlauskienė", "Kazlauskaitė")),
        ("Jankauskas", ("Jankauskienė", "Jankauskaitė")),
        ("Petrauskas", ("Petrauskienė", "Petrauskaitė")),
        ("Stankevičius", ("Stankevičienė", "Stankevičiūtė")),
        ("Vasiliauskas", ("Vasiliauskienė", "Vasiliauskaitė")),
        ("Žukauskas", ("Žukauskienė", "Žukauskaitė")),
        ("Butkus", ("Butkienė", "Butkutė")),
        ("Paulauskas", ("Paulauskienė", "Paulauskaitė")),
        ("Urbonas", ("Urbonienė", "Urbonaitė")),
        ("Kavaliauskas", ("Kavaliauskienė", "Kavaliauskaitė")),
        ("Navickas", ("Navickienė", "Navickaitė")),
        ("Ramanauskas", ("Ramanauskienė", "Ramanauskaitė")),
        ("Savickas", ("Savickienė", "Savickaitė")),
        ("Žilinskas", ("Žilinskienė", "Žilinskaitė")),
        ("Rimkus", ("Rimkienė", "Rimkutė")),
        ("Baranauskas", ("Baranauskienė", "Baranauskaitė")),
        ("Mockus", ("Mockienė", "Mockutė")),
        ("Šimkus", ("Šimkienė", "Šimkutė")),
        ("Adomaitis", ("Adomaitienė", "Adomaitytė")),
        ("Lukoševičius", ("Lukoševičienė", "Lukoševičiūtė")),
        ("Morkūnas", ("Morkūnienė", "Morkūnaitė")),
        ("Vaitkus", ("Vaitkienė", "Vaitkutė")),
        ("Kairys", ("Kairienė", "Kairytė")),
        ("Malinauskas", ("Malinauskienė", "Malinauskaitė")),
        ("Sakalauskas", ("Sakalauskienė", "Sakalauskaitė")),
        ("Bagdonas", ("Bagdonienė", "Bagdonaitė")),
        ("Grigas", ("Grigienė", "Grigaitė")),
        ("Dambrauskas", ("Dambrauskienė", "Dambrauskaitė")),
    ),
    towns=(
        (
            "Vilnius",
            ("LT-01100", "LT-03101", "LT-08105", "LT-09308", "LT-10223"),
            "Vilniaus miesto apylinkės teismas",
            "Vilniaus miesto savivaldybė",
        ),
        (
            "Kaunas",
            ("LT-44280", "LT-45255", "LT-49161", "LT-50120"),
            "Kauno apylinkės teismas",
            "Kauno miesto savivaldybė",
        ),
        (
            "Klaipėda",
            ("LT-91100", "LT-92231", "LT-94104"),
            "Klaipėdos apylinkės teismas",
            "Klaipėdos miesto savivaldybė",
        ),
        (
            "Šiauliai",
            ("LT-76285", "LT-77155"),
            "Šiaulių apylinkės teismas",
            "Šiaulių miesto savivaldybė",
        ),
        (
            "Panevėžys",
            ("LT-35173", "LT-36211"),
            "Panevėžio apylinkės teismas",
            "Panevėžio miesto savivaldybė",
        ),
        (
            "Alytus",
            ("LT-62141", "LT-63256"),
            "Alytaus apylinkės teismas",
            "Alytaus miesto savivaldybė",
        ),
        (
            "Marijampolė",
            ("LT-68308",),
            "Marijampolės apylinkės teismas",
            "Marijampolės savivaldybė",
        ),
        ("Utena", ("LT-28245",), "Panevėžio apylinkės teismas", "Utenos rajono savivaldybė"),
        ("Kėdainiai", ("LT-57262",), "Kauno apylinkės teismas", "Kėdainių rajono savivaldybė"),
        ("Telšiai", ("LT-87123",), "Plungės apylinkės teismas", "Telšių rajono savivaldybė"),
    ),
    streets=(
        "Gedimino pr.",
        "Vilniaus g.",
        "Laisvės al.",
        "Savanorių pr.",
        "Taikos pr.",
        "Žalgirio g.",
        "Liepų g.",
        "Mokyklos g.",
        "Sodų g.",
        "Ąžuolų g.",
        "Pušų g.",
        "Beržų g.",
        "Kalvarijų g.",
        "Ukmergės g.",
        "Klevų g.",
        "Žemaitės g.",
        "Pievų g.",
        "Stoties g.",
        "Ežero g.",
        "Parko g.",
    ),
    address_format="{street} {num}, {post} {town}",
    company_a=(
        "Ąžuolynas",
        "Saulės Takas",
        "Gintarų Krantas",
        "Baltoji Pušis",
        "Žalioji Giria",
        "Rudens Lapas",
        "Mėlynas Ežeras",
        "Vėjo Malūnas",
        "Šviesus Namas",
        "Tylioji Upė",
        "Sidabro Šaltinis",
        "Rasos Lankos",
    ),
    company_forms=("UAB", "UAB", "UAB", "AB", "MB"),
    company_format="{form} „{name}“",
    months_gen=(
        "sausio",
        "vasario",
        "kovo",
        "balandžio",
        "gegužės",
        "birželio",
        "liepos",
        "rugpjūčio",
        "rugsėjo",
        "spalio",
        "lapkričio",
        "gruodžio",
    ),
    date_formats=("{iso}", "{iso}", "{y} m. {mon} {d} d.", "{y}.{m:02d}.{d:02d}"),
    id_label="personal code (asmens kodas)",
    inflection_rule=(
        "Decline the names of people as natural Lithuanian requires (Jonas Kazlauskas, Jono "
        "Kazlausko, Jonui Kazlauskui, su Jonu Kazlausku; Rūta Petrauskienė, Rūtai "
        "Petrauskienei). Give every person's full name at least once exactly as given, in the "
        "nominative (for example in the list of parties or the signature block); later you may "
        "use the surname or the given name alone, in any case. Write company and institution "
        "names, addresses and every number exactly as given."
    ),
)

# --- Croatian ---------------------------------------------------------------------------------

HR = Lang(
    code="hr",
    name="Croatian",
    country="HR",
    given_m=(
        "Ivan",
        "Marko",
        "Luka",
        "Josip",
        "Tomislav",
        "Ante",
        "Matej",
        "Nikola",
        "Petar",
        "Filip",
        "Davor",
        "Krešimir",
        "Dario",
        "Goran",
        "Hrvoje",
        "Mario",
        "Stjepan",
        "Karlo",
        "Domagoj",
        "Zoran",
        "Igor",
        "Dino",
        "Mateo",
        "Bruno",
        "Damir",
        "Robert",
    ),
    given_f=(
        "Ana",
        "Marija",
        "Ivana",
        "Petra",
        "Lucija",
        "Martina",
        "Maja",
        "Katarina",
        "Mia",
        "Sara",
        "Nikolina",
        "Ivona",
        "Kristina",
        "Jelena",
        "Tea",
        "Lana",
        "Dora",
        "Marina",
        "Sanja",
        "Vesna",
        "Mirela",
        "Antonija",
        "Tena",
        "Ema",
        "Gordana",
        "Snježana",
    ),
    surnames=tuple(
        (s, (s,))
        for s in (
            "Horvat",
            "Kovačević",
            "Babić",
            "Marić",
            "Jurić",
            "Novak",
            "Kovačić",
            "Knežević",
            "Vuković",
            "Marković",
            "Petrović",
            "Matić",
            "Tomić",
            "Pavlović",
            "Božić",
            "Blažević",
            "Grgić",
            "Pavić",
            "Radić",
            "Perić",
            "Kovač",
            "Šarić",
            "Lovrić",
            "Vidović",
            "Barišić",
            "Jukić",
            "Martinović",
            "Bošnjak",
            "Vrdoljak",
            "Mlinarić",
            "Klarić",
            "Filipović",
        )
    ),
    towns=(
        (
            "Zagreb",
            ("10000", "10010", "10020", "10040", "10090"),
            "Općinski građanski sud u Zagrebu",
            "Grad Zagreb",
        ),
        ("Split", ("21000",), "Općinski sud u Splitu", "Grad Split"),
        ("Rijeka", ("51000",), "Općinski sud u Rijeci", "Grad Rijeka"),
        ("Osijek", ("31000",), "Općinski sud u Osijeku", "Grad Osijek"),
        ("Zadar", ("23000",), "Općinski sud u Zadru", "Grad Zadar"),
        ("Pula", ("52100",), "Općinski sud u Puli", "Grad Pula"),
        ("Slavonski Brod", ("35000",), "Općinski sud u Slavonskom Brodu", "Grad Slavonski Brod"),
        ("Karlovac", ("47000",), "Općinski sud u Karlovcu", "Grad Karlovac"),
        ("Varaždin", ("42000",), "Općinski sud u Varaždinu", "Grad Varaždin"),
        ("Šibenik", ("22000",), "Općinski sud u Šibeniku", "Grad Šibenik"),
        ("Sisak", ("44000",), "Općinski sud u Sisku", "Grad Sisak"),
        ("Dubrovnik", ("20000",), "Općinski sud u Dubrovniku", "Grad Dubrovnik"),
    ),
    streets=(
        "Ilica",
        "Vukovarska ulica",
        "Savska cesta",
        "Zagrebačka cesta",
        "Školska ulica",
        "Lipova ulica",
        "Primorska ulica",
        "Vrtna ulica",
        "Cvjetna ulica",
        "Hrastova ulica",
        "Sunčana ulica",
        "Kolodvorska ulica",
        "Industrijska ulica",
        "Trg slobode",
        "Ulica kralja Tomislava",
        "Obala kneza Branimira",
        "Ribarska ulica",
        "Jadranska ulica",
        "Kninska ulica",
        "Bjelovarska ulica",
    ),
    address_format="{street} {num}, {post} {town}",
    company_a=(
        "Zeleno Polje",
        "Plavi Val",
        "Sunčani Dvor",
        "Kameni Most",
        "Stara Maslina",
        "Bijela Stijena",
        "Lipa Grupa",
        "Jadran Lux",
        "Vjetar Mlin",
        "Tiha Rijeka",
        "Srebrni Izvor",
        "Hrast Projekt",
    ),
    company_forms=("d.o.o.", "d.o.o.", "d.o.o.", "j.d.o.o.", "d.d."),
    company_format="{name} {form}",
    months_gen=(
        "siječnja",
        "veljače",
        "ožujka",
        "travnja",
        "svibnja",
        "lipnja",
        "srpnja",
        "kolovoza",
        "rujna",
        "listopada",
        "studenoga",
        "prosinca",
    ),
    date_formats=("{d}. {m}. {y}.", "{d:02d}.{m:02d}.{y}.", "{d}. {mon} {y}.", "{iso}"),
    id_label="personal identification number (OIB)",
    inflection_rule=(
        "Decline the names of people as natural Croatian requires (Ivan Horvat, Ivana "
        "Horvata, Ivanu Horvatu, s Ivanom Horvatom; Ana Babić, Ani Babić). Give every "
        "person's full name at least once exactly as given, in the nominative (for example in "
        "the list of parties or the signature block); later you may use the surname or the "
        "given name alone, in any case. Write company and institution names, addresses and "
        "every number exactly as given."
    ),
)

# --- Slovenian --------------------------------------------------------------------------------

SL = Lang(
    code="sl",
    name="Slovenian",
    country="SI",
    given_m=(
        "Luka",
        "Matej",
        "Jan",
        "Žiga",
        "Marko",
        "Andrej",
        "Jure",
        "Tomaž",
        "Rok",
        "Gregor",
        "Miha",
        "Aleš",
        "Primož",
        "Boštjan",
        "Matjaž",
        "Uroš",
        "Blaž",
        "Nejc",
        "Anže",
        "Gašper",
        "Tadej",
        "Peter",
        "Janez",
        "Klemen",
        "Bojan",
        "Simon",
    ),
    given_f=(
        "Maja",
        "Ana",
        "Nina",
        "Eva",
        "Mojca",
        "Petra",
        "Katja",
        "Tina",
        "Urška",
        "Špela",
        "Nataša",
        "Barbara",
        "Mateja",
        "Sara",
        "Lara",
        "Nika",
        "Tjaša",
        "Alenka",
        "Polona",
        "Jerneja",
        "Andreja",
        "Manca",
        "Teja",
        "Zala",
        "Irena",
        "Metka",
    ),
    surnames=tuple(
        (s, (s,))
        for s in (
            "Novak",
            "Horvat",
            "Kovačič",
            "Krajnc",
            "Zupančič",
            "Potočnik",
            "Kovač",
            "Mlakar",
            "Kos",
            "Vidmar",
            "Golob",
            "Turk",
            "Božič",
            "Kralj",
            "Korošec",
            "Zupan",
            "Bizjak",
            "Hribar",
            "Kotnik",
            "Kavčič",
            "Rozman",
            "Kastelic",
            "Oblak",
            "Žagar",
            "Petek",
            "Hočevar",
            "Kolar",
            "Košir",
            "Koren",
            "Klemenčič",
            "Erjavec",
            "Jerman",
        )
    ),
    towns=(
        ("Ljubljana", ("1000",), "Okrajno sodišče v Ljubljani", "Mestna občina Ljubljana"),
        ("Maribor", ("2000",), "Okrajno sodišče v Mariboru", "Mestna občina Maribor"),
        ("Celje", ("3000",), "Okrajno sodišče v Celju", "Mestna občina Celje"),
        ("Kranj", ("4000",), "Okrajno sodišče v Kranju", "Mestna občina Kranj"),
        ("Koper", ("6000",), "Okrajno sodišče v Kopru", "Mestna občina Koper"),
        ("Velenje", ("3320",), "Okrajno sodišče v Velenju", "Mestna občina Velenje"),
        ("Novo mesto", ("8000",), "Okrajno sodišče v Novem mestu", "Mestna občina Novo mesto"),
        ("Ptuj", ("2250",), "Okrajno sodišče na Ptuju", "Mestna občina Ptuj"),
        ("Nova Gorica", ("5000",), "Okrajno sodišče v Novi Gorici", "Mestna občina Nova Gorica"),
        (
            "Murska Sobota",
            ("9000",),
            "Okrajno sodišče v Murski Soboti",
            "Mestna občina Murska Sobota",
        ),
        ("Kamnik", ("1241",), "Okrajno sodišče v Kamniku", "Občina Kamnik"),
        ("Jesenice", ("4270",), "Okrajno sodišče na Jesenicah", "Občina Jesenice"),
    ),
    streets=(
        "Slovenska cesta",
        "Celovška cesta",
        "Dunajska cesta",
        "Šolska ulica",
        "Cankarjeva ulica",
        "Prešernova ulica",
        "Lipova ulica",
        "Vrtna ulica",
        "Gubčeva ulica",
        "Kidričeva ulica",
        "Partizanska cesta",
        "Ljubljanska cesta",
        "Mariborska cesta",
        "Cesta na Brdo",
        "Trg svobode",
        "Gozdna pot",
        "Sončna ulica",
        "Kolodvorska ulica",
        "Tržaška cesta",
        "Obrtniška ulica",
    ),
    address_format="{street} {num}, {post} {town}",
    company_a=(
        "Zelena Dolina",
        "Modri Val",
        "Sončni Dvor",
        "Kamniti Most",
        "Bela Skala",
        "Lipa Projekt",
        "Tiha Reka",
        "Srebrni Izvir",
        "Hrastov Gaj",
        "Veter Mlin",
        "Jasna Pot",
        "Zlati Klas",
    ),
    company_forms=("d.o.o.", "d.o.o.", "d.o.o.", "d.d.", "s.p."),
    company_format="{name} {form}",
    months_gen=(
        "januarja",
        "februarja",
        "marca",
        "aprila",
        "maja",
        "junija",
        "julija",
        "avgusta",
        "septembra",
        "oktobra",
        "novembra",
        "decembra",
    ),
    date_formats=("{d}. {m}. {y}", "{d:02d}.{m:02d}.{y}", "{d}. {mon} {y}", "{iso}"),
    id_label="personal registration number (EMŠO)",
    inflection_rule=(
        "Decline the names of people as natural Slovenian requires (Janez Novak, Janeza "
        "Novaka, Janezu Novaku, z Janezom Novakom; Maja Kos, Maji Kos). Give every person's "
        "full name at least once exactly as given, in the nominative (for example in the list "
        "of parties or the signature block); later you may use the surname or the given name "
        "alone, in any case. Write company and institution names, addresses and every number "
        "exactly as given."
    ),
)

# --- Phase 1b (LAB-1534): fr, es, it, nl, ro, ga, mt -----------------------------------------
#
# Given names and surnames that are also common words, place names or street names of the same
# pack are left out (an unplanted match would be taught as a person, or a person as ``O``).

_NO_DECLENSION = (
    "{lang} does not decline names. Give every person's full name at least once exactly as "
    "given (for example in the list of parties or the signature block); later you may use the "
    "surname or the given name alone{extra}. Write company and institution names, addresses "
    "and every number exactly as given."
)

FR = Lang(
    code="fr",
    name="French",
    country="FR",
    given_m=(
        "Lucas",
        "Hugo",
        "Thomas",
        "Nicolas",
        "Julien",
        "Antoine",
        "Maxime",
        "Alexandre",
        "Romain",
        "Guillaume",
        "Sébastien",
        "Olivier",
        "Christophe",
        "Damien",
        "Benoît",
        "Jérôme",
        "Cédric",
        "Fabien",
        "Grégoire",
        "Yann",
        "Théo",
        "Quentin",
        "Bastien",
        "Florian",
        "Mathis",
        "Adrien",
        "Baptiste",
        "Clément",
        "Gaël",
        "Loïc",
    ),
    given_f=(
        "Camille",
        "Léa",
        "Chloé",
        "Manon",
        "Emma",
        "Sarah",
        "Julie",
        "Pauline",
        "Mathilde",
        "Claire",
        "Élodie",
        "Aurélie",
        "Céline",
        "Sandrine",
        "Nathalie",
        "Isabelle",
        "Sophie",
        "Hélène",
        "Juliette",
        "Margaux",
        "Charlotte",
        "Lucie",
        "Anaïs",
        "Émilie",
        "Audrey",
        "Justine",
        "Océane",
        "Laetitia",
        "Delphine",
        "Agnès",
    ),
    surnames=tuple(
        (s, (s,))
        for s in (
            "Dubois",
            "Durand",
            "Leroy",
            "Moreau",
            "Lefebvre",
            "Bertrand",
            "Fournier",
            "Morel",
            "Girard",
            "Mercier",
            "Dupont",
            "Lambert",
            "Bonnet",
            "Legrand",
            "Garnier",
            "Faure",
            "Rousseau",
            "Guérin",
            "Perrin",
            "Morin",
            "Gauthier",
            "Dumont",
            "Chevalier",
            "Masson",
            "Boyer",
            "Lemaire",
            "Duval",
            "Meunier",
            "Marchand",
            "Dufour",
            "Blanchard",
            "Barbier",
            "Brunet",
            "Leclerc",
            "Lacroix",
            "Dupuis",
        )
    ),
    towns=(
        (
            "Paris",
            ("75011", "75015", "75018", "75020"),
            "Tribunal judiciaire de Paris",
            "Mairie de Paris",
        ),
        ("Lyon", ("69001", "69003", "69007"), "Tribunal judiciaire de Lyon", "Mairie de Lyon"),
        (
            "Marseille",
            ("13001", "13008", "13013"),
            "Tribunal judiciaire de Marseille",
            "Mairie de Marseille",
        ),
        ("Toulouse", ("31000", "31400"), "Tribunal judiciaire de Toulouse", "Mairie de Toulouse"),
        ("Nantes", ("44000", "44300"), "Tribunal judiciaire de Nantes", "Mairie de Nantes"),
        (
            "Strasbourg",
            ("67000", "67100"),
            "Tribunal judiciaire de Strasbourg",
            "Mairie de Strasbourg",
        ),
        (
            "Montpellier",
            ("34000", "34070"),
            "Tribunal judiciaire de Montpellier",
            "Mairie de Montpellier",
        ),
        ("Bordeaux", ("33000", "33800"), "Tribunal judiciaire de Bordeaux", "Mairie de Bordeaux"),
        ("Lille", ("59000", "59800"), "Tribunal judiciaire de Lille", "Mairie de Lille"),
        ("Rennes", ("35000", "35200"), "Tribunal judiciaire de Rennes", "Mairie de Rennes"),
        ("Dijon", ("21000",), "Tribunal judiciaire de Dijon", "Mairie de Dijon"),
        ("Grenoble", ("38000", "38100"), "Tribunal judiciaire de Grenoble", "Mairie de Grenoble"),
    ),
    streets=(
        "rue de la République",
        "avenue des Tilleuls",
        "rue de l'Église",
        "boulevard de la Liberté",
        "rue des Écoles",
        "place du Marché",
        "rue de la Gare",
        "rue du Château",
        "chemin des Vignes",
        "rue des Lilas",
        "avenue de la Mer",
        "rue du Lac",
        "impasse des Peupliers",
        "rue des Acacias",
        "allée des Cerisiers",
        "rue Neuve",
    ),
    address_format="{num} {street}, {post} {town}",
    company_a=(
        "Horizon Vert",
        "Atelier Azur",
        "Pierre Blanche",
        "Vallon Fleuri",
        "Étoile du Nord",
        "Les Trois Chênes",
        "Ciel Ouvert",
        "Rive Douce",
        "Lumière d'Automne",
        "Grand Large",
        "Source Vive",
        "Bois Joli",
    ),
    company_forms=("SARL", "SAS", "SAS", "SA"),
    company_format="{name} {form}",
    months_gen=(
        "janvier",
        "février",
        "mars",
        "avril",
        "mai",
        "juin",
        "juillet",
        "août",
        "septembre",
        "octobre",
        "novembre",
        "décembre",
    ),
    date_formats=("{d:02d}/{m:02d}/{y}", "{d} {mon} {y}", "{d:02d}/{m:02d}/{y}", "{iso}"),
    id_label="social security number (NIR)",
    inflection_rule=_NO_DECLENSION.format(
        lang="French", extra=" (with elision where natural: d'Hélène, l'avocat de Mme Dubois)"
    ),
)

_ES_SURNAMES = (
    "García",
    "Rodríguez",
    "González",
    "Fernández",
    "López",
    "Martínez",
    "Sánchez",
    "Pérez",
    "Gómez",
    "Jiménez",
    "Ruiz",
    "Hernández",
    "Díaz",
    "Moreno",
    "Muñoz",
    "Álvarez",
    "Romero",
    "Alonso",
    "Gutiérrez",
    "Navarro",
    "Torres",
    "Domínguez",
    "Vázquez",
    "Ramírez",
    "Serrano",
    "Molina",
    "Morales",
    "Suárez",
    "Ortega",
    "Delgado",
    "Ortiz",
    "Rubio",
    "Medina",
    "Garrido",
    "Lozano",
    "Méndez",
    "Herrera",
    "Cabrera",
    "Carrasco",
    "Nieto",
    "Aguilar",
    "Ibáñez",
)

ES = Lang(
    code="es",
    name="Spanish",
    country="ES",
    given_m=(
        "Javier",
        "Daniel",
        "David",
        "Alejandro",
        "Pablo",
        "Sergio",
        "Adrián",
        "Álvaro",
        "Diego",
        "Jorge",
        "Rubén",
        "Iván",
        "Raúl",
        "Alberto",
        "Fernando",
        "Marcos",
        "Hugo",
        "Mario",
        "Óscar",
        "Gonzalo",
        "Andrés",
        "Víctor",
        "Ignacio",
        "Rafael",
        "Enrique",
        "Miguel",
        "Carlos",
        "Manuel",
        "Luis",
        "Antonio",
    ),
    given_f=(
        "Lucía",
        "María",
        "Laura",
        "Marta",
        "Paula",
        "Elena",
        "Sara",
        "Andrea",
        "Cristina",
        "Raquel",
        "Beatriz",
        "Silvia",
        "Nuria",
        "Irene",
        "Alba",
        "Patricia",
        "Natalia",
        "Claudia",
        "Sonia",
        "Noelia",
        "Lorena",
        "Inés",
        "Julia",
        "Carla",
        "Ainhoa",
        "Teresa",
        "Isabel",
        "Ana",
        "Eva",
        "Miriam",
    ),
    #: Two surnames per person (``extra["compound_surname"]``), drawn from this list.
    surnames=tuple((s, (s,)) for s in _ES_SURNAMES),
    towns=(
        (
            "Madrid",
            ("28001", "28013", "28045"),
            "Juzgado de Primera Instancia de Madrid",
            "Ayuntamiento de Madrid",
        ),
        (
            "Barcelona",
            ("08001", "08013", "08029"),
            "Juzgado de Primera Instancia de Barcelona",
            "Ayuntamiento de Barcelona",
        ),
        (
            "Valencia",
            ("46001", "46010"),
            "Juzgado de Primera Instancia de Valencia",
            "Ayuntamiento de Valencia",
        ),
        (
            "Sevilla",
            ("41001", "41010"),
            "Juzgado de Primera Instancia de Sevilla",
            "Ayuntamiento de Sevilla",
        ),
        (
            "Zaragoza",
            ("50001", "50008"),
            "Juzgado de Primera Instancia de Zaragoza",
            "Ayuntamiento de Zaragoza",
        ),
        (
            "Málaga",
            ("29001", "29016"),
            "Juzgado de Primera Instancia de Málaga",
            "Ayuntamiento de Málaga",
        ),
        (
            "Murcia",
            ("30001", "30008"),
            "Juzgado de Primera Instancia de Murcia",
            "Ayuntamiento de Murcia",
        ),
        (
            "Bilbao",
            ("48001", "48013"),
            "Juzgado de Primera Instancia de Bilbao",
            "Ayuntamiento de Bilbao",
        ),
        (
            "Valladolid",
            ("47001", "47010"),
            "Juzgado de Primera Instancia de Valladolid",
            "Ayuntamiento de Valladolid",
        ),
        (
            "Alicante",
            ("03001", "03010"),
            "Juzgado de Primera Instancia de Alicante",
            "Ayuntamiento de Alicante",
        ),
        (
            "Granada",
            ("18001", "18009"),
            "Juzgado de Primera Instancia de Granada",
            "Ayuntamiento de Granada",
        ),
        (
            "Córdoba",
            ("14001", "14008"),
            "Juzgado de Primera Instancia de Córdoba",
            "Ayuntamiento de Córdoba",
        ),
    ),
    streets=(
        "Calle Mayor",
        "Calle del Sol",
        "Avenida de la Constitución",
        "Calle de la Paz",
        "Plaza de España",
        "Calle Real",
        "Calle Nueva",
        "Calle del Río",
        "Avenida del Mar",
        "Calle de los Olivos",
        "Paseo de la Estación",
        "Calle Ancha",
        "Ronda Norte",
        "Calle de los Almendros",
        "Avenida de Andalucía",
        "Calle del Pozo",
    ),
    address_format="{street}, {num}, {post} {town}",
    company_a=(
        "Sol Naciente",
        "Olivo Verde",
        "Brisa Marina",
        "Cumbre Alta",
        "Río Claro",
        "Luz del Norte",
        "Piedra Azul",
        "Monte Sereno",
        "Nube Blanca",
        "Faro Dorado",
        "Viento Sur",
        "Huerta Fresca",
    ),
    company_forms=("S.L.", "S.L.", "S.A."),
    company_format="{name}, {form}",
    months_gen=(
        "enero",
        "febrero",
        "marzo",
        "abril",
        "mayo",
        "junio",
        "julio",
        "agosto",
        "septiembre",
        "octubre",
        "noviembre",
        "diciembre",
    ),
    date_formats=("{d:02d}/{m:02d}/{y}", "{d} de {mon} de {y}", "{d:02d}/{m:02d}/{y}", "{iso}"),
    id_label="DNI",
    inflection_rule=_NO_DECLENSION.format(
        lang="Spanish", extra=" (a person has two surnames; later you may use the first one alone)"
    ),
    extra={"compound_surname": "1"},
)

IT = Lang(
    code="it",
    name="Italian",
    country="IT",
    given_m=(
        "Marco",
        "Luca",
        "Francesco",
        "Alessandro",
        "Matteo",
        "Lorenzo",
        "Davide",
        "Simone",
        "Federico",
        "Riccardo",
        "Stefano",
        "Giuseppe",
        "Antonio",
        "Giovanni",
        "Paolo",
        "Roberto",
        "Fabio",
        "Daniele",
        "Emanuele",
        "Gabriele",
        "Tommaso",
        "Pietro",
        "Claudio",
        "Massimo",
        "Sergio",
        "Enrico",
        "Alberto",
        "Filippo",
        "Michele",
        "Nicola",
    ),
    given_f=(
        "Giulia",
        "Francesca",
        "Chiara",
        "Sara",
        "Martina",
        "Valentina",
        "Alessia",
        "Federica",
        "Silvia",
        "Elena",
        "Laura",
        "Elisa",
        "Giorgia",
        "Roberta",
        "Paola",
        "Anna",
        "Ilaria",
        "Beatrice",
        "Claudia",
        "Eleonora",
        "Arianna",
        "Camilla",
        "Veronica",
        "Monica",
        "Barbara",
        "Cristina",
        "Daniela",
        "Michela",
        "Lucia",
        "Alice",
    ),
    surnames=tuple(
        (s, (s,))
        for s in (
            "Rossi",
            "Russo",
            "Esposito",
            "Bianchi",
            "Colombo",
            "Ricci",
            "Conti",
            "De Luca",
            "Mancini",
            "Giordano",
            "Rizzo",
            "Lombardi",
            "Moretti",
            "Barbieri",
            "Santoro",
            "Mariani",
            "Rinaldi",
            "Caruso",
            "Galli",
            "Longo",
            "Martinelli",
            "Vitale",
            "Coppola",
            "De Santis",
            "Marchetti",
            "Parisi",
            "Ferraro",
            "Fabbri",
            "Marini",
            "Valentini",
            "Pellegrini",
            "Palumbo",
            "Sanna",
            "Cattaneo",
            "Morelli",
            "Silvestri",
        )
    ),
    towns=(
        ("Roma", ("00118", "00153", "00185"), "Tribunale di Roma", "Comune di Roma"),
        ("Milano", ("20121", "20135", "20146"), "Tribunale di Milano", "Comune di Milano"),
        ("Napoli", ("80121", "80134"), "Tribunale di Napoli", "Comune di Napoli"),
        ("Torino", ("10121", "10138"), "Tribunale di Torino", "Comune di Torino"),
        ("Bologna", ("40121", "40137"), "Tribunale di Bologna", "Comune di Bologna"),
        ("Firenze", ("50122", "50134"), "Tribunale di Firenze", "Comune di Firenze"),
        ("Genova", ("16121", "16145"), "Tribunale di Genova", "Comune di Genova"),
        ("Palermo", ("90133", "90141"), "Tribunale di Palermo", "Comune di Palermo"),
        ("Bari", ("70121", "70126"), "Tribunale di Bari", "Comune di Bari"),
        ("Verona", ("37121", "37138"), "Tribunale di Verona", "Comune di Verona"),
        ("Padova", ("35121", "35139"), "Tribunale di Padova", "Comune di Padova"),
        ("Trieste", ("34121", "34139"), "Tribunale di Trieste", "Comune di Trieste"),
    ),
    streets=(
        "Via Roma",
        "Via Dante",
        "Corso Italia",
        "Via Garibaldi",
        "Via della Repubblica",
        "Via dei Mille",
        "Viale della Libertà",
        "Via del Mare",
        "Via delle Rose",
        "Piazza del Popolo",
        "Via della Stazione",
        "Via dei Tigli",
        "Via San Martino",
        "Via Nazionale",
        "Corso Cavour",
        "Via del Mulino",
    ),
    address_format="{street} {num}, {post} {town}",
    company_a=(
        "Sole Alto",
        "Verde Valle",
        "Nuova Aurora",
        "Mare Chiaro",
        "Stella Polare",
        "Collina d'Oro",
        "Fiume Blu",
        "Torre Bianca",
        "Vento Leggero",
        "Prato Fiorito",
        "Luce Viva",
        "Pietra Antica",
    ),
    company_forms=("S.r.l.", "S.r.l.", "S.p.A."),
    company_format="{name} {form}",
    months_gen=(
        "gennaio",
        "febbraio",
        "marzo",
        "aprile",
        "maggio",
        "giugno",
        "luglio",
        "agosto",
        "settembre",
        "ottobre",
        "novembre",
        "dicembre",
    ),
    date_formats=("{d:02d}/{m:02d}/{y}", "{d} {mon} {y}", "{d:02d}/{m:02d}/{y}", "{iso}"),
    id_label="codice fiscale",
    inflection_rule=_NO_DECLENSION.format(lang="Italian", extra=""),
)

NL = Lang(
    code="nl",
    name="Dutch",
    country="NL",
    given_m=(
        "Daan",
        "Sem",
        "Lucas",
        "Jesse",
        "Thijs",
        "Ruben",
        "Bram",
        "Lars",
        "Niels",
        "Joost",
        "Pieter",
        "Sander",
        "Maarten",
        "Wouter",
        "Jeroen",
        "Martijn",
        "Rick",
        "Stijn",
        "Koen",
        "Jasper",
        "Tim",
        "Vincent",
        "Hendrik",
        "Gerrit",
        "Dirk",
        "Floris",
        "Mats",
        "Jelle",
        "Sjoerd",
        "Teun",
    ),
    given_f=(
        "Emma",
        "Sophie",
        "Julia",
        "Anna",
        "Lisa",
        "Sanne",
        "Femke",
        "Lotte",
        "Eva",
        "Noor",
        "Anouk",
        "Marieke",
        "Ingrid",
        "Annelies",
        "Esther",
        "Judith",
        "Linda",
        "Mirjam",
        "Petra",
        "Karin",
        "Ilse",
        "Merel",
        "Fenna",
        "Sara",
        "Tessa",
        "Lieke",
        "Romy",
        "Jet",
        "Floor",
        "Inge",
    ),
    surnames=tuple(
        (s, (s,))
        for s in (
            "de Vries",
            "van Dijk",
            "Jansen",
            "de Jong",
            "Bakker",
            "Visser",
            "Smit",
            "Meijer",
            "de Boer",
            "Mulder",
            "de Groot",
            "Bos",
            "Peters",
            "Hendriks",
            "van Leeuwen",
            "Dekker",
            "Brouwer",
            "de Wit",
            "Dijkstra",
            "Smits",
            "de Graaf",
            "van der Meer",
            "van der Linden",
            "Jacobs",
            "de Haan",
            "Vermeulen",
            "van den Heuvel",
            "van der Veen",
            "van den Broek",
            "de Bruijn",
            "van der Heijden",
            "Schouten",
            "van Beek",
            "Willems",
            "Hoekstra",
            "Verhoeven",
        )
    ),
    towns=(
        (
            "Amsterdam",
            ("1012 AB", "1053 KL", "1071 DJ", "1094 RS"),
            "Rechtbank Amsterdam",
            "Gemeente Amsterdam",
        ),
        (
            "Rotterdam",
            ("3011 BN", "3024 GE", "3061 PT"),
            "Rechtbank Rotterdam",
            "Gemeente Rotterdam",
        ),
        ("Den Haag", ("2511 CV", "2563 XL", "2592 BH"), "Rechtbank Den Haag", "Gemeente Den Haag"),
        (
            "Utrecht",
            ("3511 LX", "3523 GD", "3581 KP"),
            "Rechtbank Midden-Nederland",
            "Gemeente Utrecht",
        ),
        ("Eindhoven", ("5611 EM", "5643 RA"), "Rechtbank Oost-Brabant", "Gemeente Eindhoven"),
        ("Groningen", ("9711 LM", "9725 BC"), "Rechtbank Noord-Nederland", "Gemeente Groningen"),
        ("Tilburg", ("5038 TA", "5025 VK"), "Rechtbank Zeeland-West-Brabant", "Gemeente Tilburg"),
        ("Arnhem", ("6811 AP", "6824 HW"), "Rechtbank Gelderland", "Gemeente Arnhem"),
        ("Haarlem", ("2011 RB", "2034 MH"), "Rechtbank Noord-Holland", "Gemeente Haarlem"),
        ("Leiden", ("2311 EZ", "2324 KN"), "Rechtbank Den Haag", "Gemeente Leiden"),
        ("Zwolle", ("8011 PK", "8031 EJ"), "Rechtbank Overijssel", "Gemeente Zwolle"),
        ("Maastricht", ("6211 KL", "6224 GB"), "Rechtbank Limburg", "Gemeente Maastricht"),
    ),
    streets=(
        "Kerkstraat",
        "Dorpsstraat",
        "Stationsweg",
        "Molenstraat",
        "Schoolstraat",
        "Nieuwstraat",
        "Julianalaan",
        "Lindenlaan",
        "Eikenlaan",
        "Prinsengracht",
        "Marktplein",
        "Zuiderweg",
        "Havenstraat",
        "Beukenlaan",
        "Parkweg",
        "Kastanjelaan",
    ),
    address_format="{street} {num}, {post} {town}",
    company_a=(
        "Groene Horizon",
        "Blauwe Haven",
        "Zonnige Velden",
        "Witte Molen",
        "Noorder Licht",
        "Oranje Brug",
        "Gouden Polder",
        "Stille Gracht",
        "Hoge Duinen",
        "Frisse Wind",
        "Lage Landen",
        "Rode Pannen",
    ),
    company_forms=("B.V.", "B.V.", "B.V.", "N.V."),
    company_format="{name} {form}",
    months_gen=(
        "januari",
        "februari",
        "maart",
        "april",
        "mei",
        "juni",
        "juli",
        "augustus",
        "september",
        "oktober",
        "november",
        "december",
    ),
    date_formats=("{d:02d}-{m:02d}-{y}", "{d} {mon} {y}", "{d:02d}-{m:02d}-{y}", "{iso}"),
    id_label="citizen service number (BSN)",
    inflection_rule=_NO_DECLENSION.format(
        lang="Dutch",
        extra=" (a surname alone starts with a capital: de heer De Vries, mevrouw Van Dijk)",
    ),
)

RO = Lang(
    code="ro",
    name="Romanian",
    country="RO",
    given_m=(
        "Andrei",
        "Alexandru",
        "Mihai",
        "Ion",
        "Florin",
        "Cristian",
        "Bogdan",
        "Adrian",
        "Ionuț",
        "Marius",
        "Daniel",
        "Răzvan",
        "Ciprian",
        "Vlad",
        "Sorin",
        "Cătălin",
        "Lucian",
        "Ovidiu",
        "Radu",
        "Dragoș",
        "Mircea",
        "Valentin",
        "Costin",
        "Victor",
        "Iulian",
        "Gabriel",
        "Sebastian",
        "Liviu",
        "Horia",
        "Emil",
    ),
    given_f=(
        "Maria",
        "Elena",
        "Ioana",
        "Andreea",
        "Alexandra",
        "Mihaela",
        "Cristina",
        "Ana",
        "Gabriela",
        "Raluca",
        "Diana",
        "Simona",
        "Roxana",
        "Alina",
        "Irina",
        "Oana",
        "Adriana",
        "Larisa",
        "Bianca",
        "Daniela",
        "Corina",
        "Monica",
        "Iulia",
        "Teodora",
        "Laura",
        "Ramona",
        "Anca",
        "Denisa",
        "Lavinia",
        "Sorina",
    ),
    surnames=tuple(
        (s, (s,))
        for s in (
            "Popescu",
            "Popa",
            "Dumitru",
            "Stan",
            "Stoica",
            "Ciobanu",
            "Ionescu",
            "Rusu",
            "Munteanu",
            "Șerban",
            "Lazăr",
            "Dinu",
            "Moldovan",
            "Cristea",
            "Florea",
            "Dobre",
            "Barbu",
            "Nistor",
            "Dragomir",
            "Ene",
            "Diaconu",
            "Preda",
            "Oprea",
            "Voicu",
            "Neagu",
            "Avram",
            "Mocanu",
            "Manole",
            "Georgescu",
            "Constantinescu",
            "Ursu",
            "Bălan",
            "Stănescu",
            "Nedelcu",
            "Pavel",
            "Zamfir",
        )
    ),
    towns=(
        (
            "București",
            ("010011", "020335", "030167", "040051"),
            "Judecătoria Sectorului 1 București",
            "Primăria Municipiului București",
        ),
        (
            "Cluj-Napoca",
            ("400001", "400124", "400394"),
            "Judecătoria Cluj-Napoca",
            "Primăria Municipiului Cluj-Napoca",
        ),
        (
            "Timișoara",
            ("300011", "300223"),
            "Judecătoria Timișoara",
            "Primăria Municipiului Timișoara",
        ),
        ("Iași", ("700028", "700259"), "Judecătoria Iași", "Primăria Municipiului Iași"),
        (
            "Constanța",
            ("900178", "900590"),
            "Judecătoria Constanța",
            "Primăria Municipiului Constanța",
        ),
        ("Brașov", ("500030", "500187"), "Judecătoria Brașov", "Primăria Municipiului Brașov"),
        ("Craiova", ("200345", "200585"), "Judecătoria Craiova", "Primăria Municipiului Craiova"),
        ("Galați", ("800008", "800211"), "Judecătoria Galați", "Primăria Municipiului Galați"),
        ("Oradea", ("410087", "410210"), "Judecătoria Oradea", "Primăria Municipiului Oradea"),
        (
            "Ploiești",
            ("100066", "100390"),
            "Judecătoria Ploiești",
            "Primăria Municipiului Ploiești",
        ),
        ("Sibiu", ("550024", "550182"), "Judecătoria Sibiu", "Primăria Municipiului Sibiu"),
        ("Suceava", ("720035", "720229"), "Judecătoria Suceava", "Primăria Municipiului Suceava"),
    ),
    streets=(
        "Strada Florilor",
        "Bulevardul Unirii",
        "Strada Libertății",
        "Calea Victoriei",
        "Strada Morii",
        "Strada Teilor",
        "Strada Lalelelor",
        "Strada Primăverii",
        "Bulevardul Independenței",
        "Strada Școlii",
        "Strada Gării",
        "Strada Viilor",
        "Strada Castanilor",
        "Aleea Trandafirilor",
        "Strada Păcii",
        "Strada Fabricii",
    ),
    address_format="{street} nr. {num}, {post} {town}",
    company_a=(
        "Codrul Verde",
        "Dealul Însorit",
        "Lumina Nordului",
        "Valea Albastră",
        "Steaua Mării",
        "Izvorul Clar",
        "Muntele Alb",
        "Piatra Nouă",
        "Vântul de Est",
        "Câmpia Aurie",
        "Ploaia Caldă",
        "Lacul Liniștit",
    ),
    company_forms=("S.R.L.", "S.R.L.", "S.A."),
    company_format="{name} {form}",
    months_gen=(
        "ianuarie",
        "februarie",
        "martie",
        "aprilie",
        "mai",
        "iunie",
        "iulie",
        "august",
        "septembrie",
        "octombrie",
        "noiembrie",
        "decembrie",
    ),
    date_formats=("{d:02d}.{m:02d}.{y}", "{d} {mon} {y}", "{d:02d}.{m:02d}.{y}", "{iso}"),
    id_label="personal numeric code (CNP)",
    inflection_rule=(
        "Decline the names of people as natural Romanian requires (Ioana Popescu, Ioanei "
        "Popescu, Mariei Stan; lui Andrei Popescu; vocative Ioano, Mihaie). Give every "
        "person's full name at least once exactly as given, in the nominative (for example in "
        "the list of parties or the signature block); later you may use the surname or the "
        "given name alone, in any case. Write company and institution names, addresses and "
        "every number exactly as given."
    ),
)

GA = Lang(
    code="ga",
    name="Irish (Gaeilge)",
    country="IE",
    given_m=(
        "Seán",
        "Pádraig",
        "Cian",
        "Oisín",
        "Ciarán",
        "Diarmuid",
        "Eoin",
        "Colm",
        "Dónal",
        "Liam",
        "Tadhg",
        "Ruairí",
        "Dara",
        "Fionn",
        "Séamus",
        "Niall",
        "Cathal",
        "Éamonn",
        "Peadar",
        "Tomás",
        "Micheál",
        "Daithí",
        "Aodhán",
        "Cormac",
        "Lorcán",
        "Fiachra",
        "Conall",
        "Odhrán",
        "Seanán",
        "Cillian",
    ),
    given_f=(
        "Aoife",
        "Siobhán",
        "Niamh",
        "Gráinne",
        "Saoirse",
        "Caoimhe",
        "Róisín",
        "Orlaith",
        "Clíodhna",
        "Sinéad",
        "Máire",
        "Áine",
        "Eimear",
        "Méabh",
        "Úna",
        "Deirdre",
        "Bríd",
        "Nóra",
        "Sorcha",
        "Ailbhe",
        "Muireann",
        "Laoise",
        "Aisling",
        "Ciara",
        "Éabha",
        "Treasa",
        "Síle",
        "Nuala",
        "Fiadh",
        "Gormlaith",
    ),
    #: (man's form, (woman's form,)): Ó / Ní, Mac / Nic, with the lenition the woman's form takes.
    surnames=(
        ("Ó Briain", ("Ní Bhriain",)),
        ("Ó Ceallaigh", ("Ní Cheallaigh",)),
        ("Ó Súilleabháin", ("Ní Shúilleabháin",)),
        ("Mac Cárthaigh", ("Nic Cárthaigh",)),
        ("Ó Murchú", ("Ní Mhurchú",)),
        ("Ó Néill", ("Ní Néill",)),
        ("Ó Dónaill", ("Ní Dhónaill",)),
        ("Breathnach", ("Bhreathnach",)),
        ("Mac Mathúna", ("Nic Mhathúna",)),
        ("Ó Conaill", ("Ní Chonaill",)),
        ("Ó Dálaigh", ("Ní Dhálaigh",)),
        ("Ó Riain", ("Ní Riain",)),
        ("Ó Flaithearta", ("Ní Fhlaithearta",)),
        ("Mac Aodha", ("Nic Aodha",)),
        ("Ó Gallchóir", ("Ní Ghallchóir",)),
        ("Ó Máille", ("Ní Mháille",)),
        ("Ó Cinnéide", ("Ní Chinnéide",)),
        ("Ó Tuathail", ("Ní Thuathail",)),
        ("Mac Diarmada", ("Nic Dhiarmada",)),
        ("de Búrca", ("de Búrca",)),
        ("Ó Floinn", ("Ní Fhloinn",)),
        ("Ó Laoire", ("Ní Laoire",)),
        ("Mac Gearailt", ("Nic Gearailt",)),
        ("Ó Cathasaigh", ("Ní Chathasaigh",)),
        ("Ó Duibhir", ("Ní Dhuibhir",)),
        ("Seoighe", ("Sheoighe",)),
        ("Ó hEadhra", ("Ní Eadhra",)),
        ("Mac Suibhne", ("Nic Suibhne",)),
    ),
    towns=(
        (
            "Baile Átha Cliath",
            ("D02 X285", "D04 K7W2", "D08 P6F3", "D12 H9R4"),
            "An Chúirt Dúiche, Baile Átha Cliath",
            "Comhairle Cathrach Bhaile Átha Cliath",
        ),
        (
            "Corcaigh",
            ("T12 R5CP", "T23 K8E6"),
            "An Chúirt Dúiche, Corcaigh",
            "Comhairle Cathrach Chorcaí",
        ),
        (
            "Gaillimh",
            ("H91 E2K3", "H91 T6Y8"),
            "An Chúirt Dúiche, Gaillimh",
            "Comhairle Cathrach na Gaillimhe",
        ),
        (
            "Luimneach",
            ("V94 C4D9", "V94 N2P7"),
            "An Chúirt Dúiche, Luimneach",
            "Comhairle Cathrach agus Contae Luimnigh",
        ),
        (
            "Port Láirge",
            ("X91 H3T5", "X91 W8K2"),
            "An Chúirt Dúiche, Port Láirge",
            "Comhairle Cathrach agus Contae Phort Láirge",
        ),
        (
            "Cill Chainnigh",
            ("R95 A6V3",),
            "An Chúirt Dúiche, Cill Chainnigh",
            "Comhairle Contae Chill Chainnigh",
        ),
        ("Sligeach", ("F91 P2X6",), "An Chúirt Dúiche, Sligeach", "Comhairle Contae Shligigh"),
        ("Trá Lí", ("V92 F7H4",), "An Chúirt Dúiche, Trá Lí", "Comhairle Contae Chiarraí"),
        ("Dún Dealgan", ("A91 R3K8",), "An Chúirt Dúiche, Dún Dealgan", "Comhairle Contae Lú"),
        (
            "Leitir Ceanainn",
            ("F92 V5T1",),
            "An Chúirt Dúiche, Leitir Ceanainn",
            "Comhairle Contae Dhún na nGall",
        ),
        (
            "An Daingean",
            ("V92 Y6E3",),
            "An Chúirt Dúiche, An Daingean",
            "Comhairle Contae Chiarraí",
        ),
        (
            "Cathair na Mart",
            ("F28 K2D9",),
            "An Chúirt Dúiche, Cathair na Mart",
            "Comhairle Contae Mhaigh Eo",
        ),
    ),
    streets=(
        "Sráid an Mhuilinn",
        "Bóthar na Trá",
        "Sráid na hEaglaise",
        "Bóthar an Stáisiúin",
        "An tSráid Mhór",
        "Ascaill na Páirce",
        "Bóthar na Coille",
        "Lána an Droichid",
        "Cearnóg an Mhargaidh",
        "Bóthar na Scoile",
        "Sráid an Chalaidh",
        "Ardán na Mara",
        "Bóthar an Chnoic",
        "Sráid na Siopaí",
        "Plás na Fuinseoige",
        "Céide an Locha",
    ),
    address_format="{num} {street}, {town}, {post}",
    company_a=(
        "Solas na Mara",
        "Crann Óir",
        "Gleann Glas",
        "Cnoc Ard",
        "Tonn Gheal",
        "Réalta Thuaidh",
        "Abhainn Chiúin",
        "Cloch Bhán",
        "Gaoth Aniar",
        "Páirc Ghlas",
        "Loch Gorm",
        "Dún Láidir",
    ),
    company_forms=("Teo.", "Teo.", "Teoranta"),
    company_format="{name} {form}",
    months_gen=(
        "Eanáir",
        "Feabhra",
        "Márta",
        "Aibreán",
        "Bealtaine",
        "Meitheamh",
        "Iúil",
        "Lúnasa",
        "Meán Fómhair",
        "Deireadh Fómhair",
        "Samhain",
        "Nollaig",
    ),
    date_formats=("{d:02d}/{m:02d}/{y}", "{d} {mon} {y}", "{d:02d}/{m:02d}/{y}", "{iso}"),
    id_label="PPS number (uimhir PSP)",
    inflection_rule=(
        "Apply the initial mutations and case forms natural Irish requires (Seán Ó Briain, a "
        "Sheáin, teach Sheáin Uí Bhriain, do Sheán; Máire Ní Bhriain, a Mháire; Mac Cárthaigh, "
        "Mhic Cárthaigh). Give every person's full name at least once exactly as given (for "
        "example in the list of parties or the signature block); later you may use the surname "
        "or the given name alone, in any form. Write company and institution names, addresses "
        "and every number exactly as given."
    ),
)

MT = Lang(
    code="mt",
    name="Maltese",
    country="MT",
    given_m=(
        "Ġorġ",
        "Ġużeppi",
        "Pawlu",
        "Karmenu",
        "Mikiel",
        "Ġwann",
        "Salvu",
        "Frans",
        "Manwel",
        "Anton",
        "Kristjan",
        "Luqa",
        "Mattew",
        "Kurt",
        "Clayton",
        "Ryan",
        "Malcolm",
        "Raymond",
        "Charles",
        "Adrian",
        "Daniel",
        "Carmel",
        "Joseph",
        "Kevin",
        "Duncan",
        "Neil",
        "Ivan",
        "Jean",
        "Owen",
        "Nikolai",
    ),
    given_f=(
        "Marija",
        "Rita",
        "Doris",
        "Carmen",
        "Josephine",
        "Claire",
        "Rachel",
        "Graziella",
        "Antonella",
        "Rosanne",
        "Michelle",
        "Nicole",
        "Kristina",
        "Marlene",
        "Pauline",
        "Bernardette",
        "Sarah",
        "Roberta",
        "Christine",
        "Maryanne",
        "Elaine",
        "Joanna",
        "Stephanie",
        "Ritianne",
        "Lorraine",
        "Miriam",
        "Yvonne",
        "Daniela",
        "Melanie",
        "Analise",
    ),
    surnames=tuple(
        (s, (s,))
        for s in (
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
            "Fenech",
            "Sammut",
            "Caruana",
            "Debono",
            "Bonnici",
            "Abela",
            "Calleja",
            "Schembri",
            "Gauci",
            "Xuereb",
            "Cutajar",
            "Ellul",
            "Bugeja",
            "Tabone",
            "Sciberras",
            "Chetcuti",
            "Buttigieg",
            "Saliba",
            "Portelli",
            "Zahra",
            "Formosa",
            "Briffa",
        )
    ),
    towns=(
        (
            "Il-Belt Valletta",
            ("VLT 1117", "VLT 1442"),
            "Il-Qorti tal-Maġistrati (Malta)",
            "Il-Kunsill Lokali tal-Belt Valletta",
        ),
        (
            "Birkirkara",
            ("BKR 1310", "BKR 4012"),
            "Il-Qorti tal-Maġistrati (Malta)",
            "Il-Kunsill Lokali ta' Birkirkara",
        ),
        (
            "Il-Mosta",
            ("MST 1550", "MST 2130"),
            "Il-Qorti tal-Maġistrati (Malta)",
            "Il-Kunsill Lokali tal-Mosta",
        ),
        (
            "Ħal Qormi",
            ("QRM 1420", "QRM 2401"),
            "Il-Qorti tal-Maġistrati (Malta)",
            "Il-Kunsill Lokali ta' Ħal Qormi",
        ),
        (
            "Ħaż-Żabbar",
            ("ZBR 1013", "ZBR 2210"),
            "Il-Qorti tal-Maġistrati (Malta)",
            "Il-Kunsill Lokali ta' Ħaż-Żabbar",
        ),
        (
            "Tas-Sliema",
            ("SLM 1540", "SLM 3112"),
            "Il-Qorti tal-Maġistrati (Malta)",
            "Il-Kunsill Lokali tas-Sliema",
        ),
        (
            "San Ġwann",
            ("SGN 2302", "SGN 1600"),
            "Il-Qorti tal-Maġistrati (Malta)",
            "Il-Kunsill Lokali ta' San Ġwann",
        ),
        (
            "In-Naxxar",
            ("NXR 1410", "NXR 2310"),
            "Il-Qorti tal-Maġistrati (Malta)",
            "Il-Kunsill Lokali tan-Naxxar",
        ),
        (
            "Iż-Żejtun",
            ("ZTN 1101", "ZTN 2510"),
            "Il-Qorti tal-Maġistrati (Malta)",
            "Il-Kunsill Lokali taż-Żejtun",
        ),
        (
            "Ir-Rabat",
            ("RBT 1010", "RBT 2321"),
            "Il-Qorti tal-Maġistrati (Malta)",
            "Il-Kunsill Lokali tar-Rabat",
        ),
        (
            "Il-Fgura",
            ("FGR 1320", "FGR 1601"),
            "Il-Qorti tal-Maġistrati (Malta)",
            "Il-Kunsill Lokali tal-Fgura",
        ),
        (
            "Ir-Rabat, Għawdex",
            ("VCT 1010", "VCT 2210"),
            "Il-Qorti tal-Maġistrati (Għawdex)",
            "Il-Kunsill Lokali tar-Rabat, Għawdex",
        ),
    ),
    streets=(
        "Triq il-Kbira",
        "Triq il-Knisja",
        "Triq ir-Repubblika",
        "Triq il-Mitħna",
        "Triq il-Ġnien",
        "Triq il-Baħar",
        "Triq l-Iskola",
        "Triq it-Torri",
        "Triq il-Fortizza",
        "Triq is-Salib",
        "Triq id-Dawl",
        "Triq il-Wied",
        "Triq il-Port",
        "Triq il-Merkanti",
        "Triq tal-Ħarrub",
        "Triq il-Lewża",
    ),
    address_format="{num}, {street}, {town} {post}",
    company_a=(
        "Dawl tal-Qamar",
        "Blu Mediterran",
        "Ġnien Aħdar",
        "Xemx Ħelwa",
        "Riħ Isfel",
        "Kosta Safja",
        "Ġebla Bajda",
        "Fanal Qadim",
        "Mewġa Ġdida",
        "Siġra tal-Ħarrub",
        "Bejta Sħuna",
        "Port Kwiet",
    ),
    company_forms=("Limited", "Ltd", "Ltd"),
    company_format="{name} {form}",
    months_gen=(
        "Jannar",
        "Frar",
        "Marzu",
        "April",
        "Mejju",
        "Ġunju",
        "Lulju",
        "Awwissu",
        "Settembru",
        "Ottubru",
        "Novembru",
        "Diċembru",
    ),
    date_formats=("{d:02d}/{m:02d}/{y}", "{d} ta' {mon} {y}", "{d:02d}/{m:02d}/{y}", "{iso}"),
    id_label="ID card number (numru tal-karta tal-identità)",
    inflection_rule=_NO_DECLENSION.format(
        lang="Maltese", extra=" (with the title where natural: is-Sur Borg, is-Sinjura Vella)"
    ),
)

LANGS: dict[str, Lang] = {lang.code: lang for lang in (LV, LT, HR, SL, FR, ES, IT, NL, RO, GA, MT)}


# --- Declension -------------------------------------------------------------------------------

_LV_PALATAL = (
    ("ln", "ļņ"), ("sn", "šņ"), ("zn", "žņ"), ("sl", "šļ"), ("zl", "žļ"),
    ("n", "ņ"), ("l", "ļ"), ("d", "ž"), ("t", "š"), ("s", "š"), ("z", "ž"), ("c", "č"),
    ("p", "pj"), ("b", "bj"), ("m", "mj"), ("v", "vj"),
)  # fmt: skip


def _lv_palatal(stem: str) -> str:
    for plain, soft in _LV_PALATAL:
        if stem.endswith(plain):
            return stem[: -len(plain)] + soft
    return stem


def _forms_lv(t: str) -> set[str]:
    if t.endswith("š"):
        s = t[:-1]
        return {t, s + "a", s + "am", s + "u", s + "ā", s + "i", s}  # s: the vocative (Bērziņ!)
    if t.endswith("is"):
        s = t[:-2]
        p = _lv_palatal(s)
        return {t, s + "a", p + "a", s + "im", s + "i", s + "ī", p + "u", p + "am", p + "ā"}
    if t.endswith("us"):
        s = t[:-2]
        return {t, s + "um", s + "u", s + "ū"}
    if t.endswith("s"):
        s = t[:-1]
        return {t, s + "a", s + "am", s + "u", s + "ā", s + "i", s}
    if t.endswith("a"):
        s = t[:-1]
        return {t, s + "as", s + "ai", s + "u", s + "ā"}
    if t.endswith("e"):
        s = t[:-1]
        return {t, s + "es", s + "ei", s + "i", s + "ē"}
    return {t}


def _forms_lt(t: str) -> set[str]:
    def soft(s: str) -> set[str]:  # t -> č, d -> dž before io / iui / iu / ių
        out = {s}
        if s.endswith("t"):
            out.add(s[:-1] + "č")
        if s.endswith("d"):
            out.add(s[:-1] + "dž")
        return out

    if t.endswith("ius"):
        s = t[:-3]
        return {t} | {s + e for e in ("iaus", "iui", "ių", "iumi", "iuje", "iau", "iu")}
    if t.endswith("as"):
        s = t[:-2]
        return {t} | {s + e for e in ("o", "ui", "ą", "u", "e", "ai", "ui")}
    if t.endswith(("is", "ys")):
        s = t[:-2]
        out = {t, s + "į", s + "yje", s + "i", s + "y"}
        for v in soft(s):
            out |= {v + "io", v + "iui", v + "iu"}
        return out
    if t.endswith("us"):
        s = t[:-2]
        return {t} | {s + e for e in ("aus", "ui", "ų", "umi", "uje", "au")}
    if t.endswith("ė"):
        s = t[:-1]
        return {t} | {s + e for e in ("ės", "ei", "ę", "e", "ėje")}
    if t.endswith("a"):
        s = t[:-1]
        return {t} | {s + e for e in ("os", "ai", "ą", "a", "oje")}
    return {t}


def _forms_hr(t: str, gender: str, is_family: bool) -> set[str]:
    if is_family and gender == "f":
        # A woman's surname doesn't decline (Ana Horvat, Ani Horvat), but colloquial text
        # names her with the possessive form (Horvatova, Babićeva).
        return {t} | _possessive(t, ("ov", "ev"))
    if t.endswith("a"):
        s = t[:-1]
        out = {t} | {s + e for e in ("e", "i", "u", "om", "o")}
        if s.endswith("k"):
            out.add(s[:-1] + "ci")
        return out
    if t.endswith("io"):
        s = t[:-1]
        return {t} | {s + e for e in ("ja", "ju", "jem", "a", "u", "om")}
    if t.endswith(("o", "e")):
        s = t[:-1]
        return {t} | {s + e for e in ("a", "u", "om", "e", "i", "ea", "eu", "eom")}
    stems = {t}
    if t.endswith("ar"):  # Petar -> Petra
        stems.add(t[:-2] + "r")
    out = {t}
    for s in stems:
        out |= {s + e for e in ("a", "u", "om", "em", "e", "i")}
    return out | _possessive(t, ("ov", "ev"))


#: Endings of a possessive adjective (Horvatov, Horvatova, Horvatovoj ...), hr and sl.
_POSSESSIVE_ENDINGS = (
    "",
    "a",
    "e",
    "i",
    "o",
    "u",
    "oj",
    "om",
    "ega",
    "emu",
    "em",
    "im",
    "ih",
    "ima",
)


def _possessive(t: str, suffixes: tuple[str, ...]) -> set[str]:
    """A man's name or surname as a possessive adjective (``Tomićeva kuća``, ``Kraljeva hiša``)."""
    return {t + suf + e for suf in suffixes for e in _POSSESSIVE_ENDINGS}


def _forms_sl(t: str, gender: str, is_family: bool) -> set[str]:
    if is_family and gender == "f":
        forms = {t} | _possessive(t, ("ov", "ev", "jev"))  # Novakova, Žagarjeva (colloquial)
        for c in (t, t[:-2] + "c" if t.endswith("ec") else t):
            if c.endswith("c"):
                forms |= _possessive(c[:-1] + "č", ("ev",))
        return forms
    if t.endswith("a"):
        s = t[:-1]
        return {t} | {s + e for e in ("e", "i", "o", "u", "a")}
    if t.endswith("e"):  # Anže -> Anžeta, Jure -> Jureta / Jureja
        return {t} | {t + e for e in ("ta", "tu", "tom", "ja", "ju", "jem")}
    if t.endswith("o"):
        s = t[:-1]
        return {t} | {s + e for e in ("a", "u", "om", "ota", "otu", "otom")}
    stems = {t}
    if t.endswith("er"):  # Peter -> Petra
        stems.add(t[:-2] + "r")
    if t.endswith("ec"):  # Korošec -> Korošca
        stems.add(t[:-2] + "c")
    out = {t}
    for s in stems:
        out |= {s + e for e in ("a", "u", "om", "em", "ja", "ju", "jem")}
        out |= _possessive(s, ("ov", "ev", "jev"))
        if s.endswith("c"):  # Kastelic -> Kasteličeva, Erjavec -> Erjavčeva
            out |= _possessive(s[:-1] + "č", ("ev",))
    return out


def _forms_ro(t: str, gender: str, is_family: bool) -> set[str]:
    # Surnames don't decline (lui Andrei Popescu, Ioanei Popescu); given names take the
    # genitive-dative -ei (Ioana -> Ioanei, Maria -> Mariei) and the vocative.
    if is_family:
        return {t}
    if t.endswith("a"):
        s = t[:-1]
        return {t, s + "ei", s + "o"}
    if t.endswith(("u", "e")):
        return {t, t + "le"}
    return {t, t + "e", t + "ule"}


_GA_LENITABLE = set("BCDFGMPT")
_GA_BROAD = "aouáóú"
_GA_VOWELS = "aeiouáéíóú"


def _ga_lenite(t: str) -> str:
    """Séamus -> Shéamus, Máire -> Mháire; vowels, ``Sc``/``Sp``/``St``/``Sm`` and h stay."""
    if len(t) < 2 or t[1] == "h":
        return t
    if t[0] in _GA_LENITABLE or (t[0] == "S" and t[1].lower() in _GA_VOWELS + "lnr"):
        return t[0] + "h" + t[1:]
    return t


def _ga_slender(t: str) -> str:
    """Genitive / vocative of a man's name ending in a broad consonant: Seán -> Seáin."""
    i = len(t)
    while i > 0 and t[i - 1].lower() not in _GA_VOWELS:
        i -= 1
    if 0 < i < len(t) and t[i - 1] in _GA_BROAD:
        return t[:i] + "i" + t[i:]
    return t


def _forms_ga(t: str, gender: str, is_family: bool) -> set[str]:
    """Irish initial mutations and the slender genitive / vocative (deliberately generous)."""
    out = {t, _ga_lenite(t)}
    if not is_family:
        if gender != "f":
            out |= {_ga_slender(t), _ga_lenite(_ga_slender(t))}
        return out
    head, _, rest = t.partition(" ")
    if not rest:  # Breathnach -> Bhreathnach, Bhreathnaigh
        stems = {t, t[:-3] + "aigh"} if t.endswith("ach") else {t, _ga_slender(t)}
        return out | stems | {_ga_lenite(x) for x in stems}
    bare = rest[1:] if rest[:1] == "h" and rest[1:2].isupper() else rest  # Ó hEadhra
    if head == "Ó":  # genitive Uí + lenition: Seáin Uí Bhriain
        out |= {f"Uí {_ga_lenite(bare)}", f"Ua {rest}"}
    elif head == "Mac":
        out |= {f"Mhic {rest}", f"Mic {rest}", f"Mhic {_ga_lenite(rest)}"}
    elif head == "de":
        out.add(f"De {rest}")
    return out


def name_forms(language: str, token: str, gender: str = "", is_family: bool = False) -> set[str]:
    """Declined forms of one name token (the token itself included)."""
    if language == "ro":
        return _forms_ro(token, gender, is_family)
    if language == "ga":
        return _forms_ga(token, gender, is_family)
    if language == "nl" and is_family and token[:1].islower():
        return {token, token[0].upper() + token[1:]}  # de Vries -> (de heer) De Vries
    if language == "es" and is_family and " " in token:
        return {token, token.split(" ")[0]}  # García López -> García (the first surname alone)
    if language == "lv":
        return _forms_lv(token)
    if language == "lt":
        return _forms_lt(token)
    if language == "hr":
        return _forms_hr(token, gender, is_family)
    if language == "sl":
        return _forms_sl(token, gender, is_family)
    return {token}


# --- National identifiers (random payloads, valid shape) --------------------------------------


def lt_personal_code(rng: random.Random, birth: dt.date, gender: str) -> str:
    century = 3 if birth.year < 2000 else 5
    first = century + (1 if gender == "f" else 0)
    body = f"{first}{birth:%y%m%d}{rng.randint(0, 999):03d}"
    digits = [int(c) for c in body]
    for weights in ((1, 2, 3, 4, 5, 6, 7, 8, 9, 1), (3, 4, 5, 6, 7, 8, 9, 1, 2, 3)):
        check = sum(d * w for d, w in zip(digits, weights, strict=True)) % 11
        if check != 10:
            return body + str(check)
    return body + "0"


def hr_oib(rng: random.Random) -> str:
    body = f"{rng.randint(1, 9)}{rng.randint(0, 10**9 - 1):09d}"
    acc = 10
    for c in body:
        acc = (acc + int(c)) % 10 or 10
        acc = (acc * 2) % 11
    return body + str((11 - acc) % 10)


def si_emso(rng: random.Random, birth: dt.date, gender: str) -> str:
    region = "50"
    serial = rng.randint(0, 499) + (500 if gender == "f" else 0)
    body = f"{birth.day:02d}{birth.month:02d}{birth.year % 1000:03d}{region}{serial:03d}"
    weights = (7, 6, 5, 4, 3, 2, 7, 6, 5, 4, 3, 2)
    rest = sum(int(c) * w for c, w in zip(body, weights, strict=True)) % 11
    check = 0 if rest == 0 else 11 - rest
    return body + str(check % 10)


def lv_personal_code(rng: random.Random, birth: dt.date) -> str:
    century = 1 if birth.year < 2000 else 2
    return f"{birth:%d%m%y}-{century}{rng.randint(0, 9999):04d}"


def fr_nir(rng: random.Random, birth: dt.date, gender: str) -> str:
    """French social security number: sex, year, month, département, commune, order, key."""
    dept = rng.choice([d for d in range(1, 96) if d != 20])
    body = f"{1 if gender == 'm' else 2}{birth:%y%m}{dept:02d}{rng.randint(1, 999):03d}"
    body += f"{rng.randint(1, 999):03d}"
    key = 97 - int(body) % 97
    b = body
    return f"{b[0]} {b[1:3]} {b[3:5]} {b[5:7]} {b[7:10]} {b[10:13]} {key:02d}"


def es_dni(rng: random.Random) -> str:
    n = rng.randint(10_000_000, 99_999_999)
    return f"{n}{'TRWAGMYFPDXBNJZSQVHLCKE'[n % 23]}"


_CF_MONTHS = "ABCDEHLMPRST"
_CF_ODD = dict(
    zip(
        "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ",
        (1, 0, 5, 7, 9, 13, 15, 17, 19, 21, 1, 0, 5, 7, 9, 13, 15, 17, 19, 21, 2, 4, 18, 20,
         11, 3, 6, 8, 12, 14, 16, 10, 22, 25, 24, 23),
        strict=True,
    )
)  # fmt: skip
#: Cadastral codes of the pack's towns (public, as the towns themselves).
_CF_TOWNS = ("H501", "F205", "F839", "L219", "A944", "D612", "D969", "G273", "A662", "L781")


def _cf_letters(word: str) -> tuple[str, str]:
    import unicodedata

    plain = "".join(c for c in unicodedata.normalize("NFD", word.upper()) if "A" <= c <= "Z")
    cons = "".join(c for c in plain if c not in "AEIOU")
    vows = "".join(c for c in plain if c in "AEIOU")
    return cons, vows


def it_codice_fiscale(
    rng: random.Random, given: str, family: str, birth: dt.date, gender: str
) -> str:
    cons, vows = _cf_letters(family)
    sur = (cons + vows + "XXX")[:3]
    cons, vows = _cf_letters(given)
    name = cons[0] + cons[2] + cons[3] if len(cons) >= 4 else (cons + vows + "XXX")[:3]
    day = birth.day + (40 if gender == "f" else 0)
    body = f"{sur}{name}{birth:%y}{_CF_MONTHS[birth.month - 1]}{day:02d}{rng.choice(_CF_TOWNS)}"
    total = sum(
        _CF_ODD[c] if i % 2 == 0 else (int(c) if c.isdigit() else ord(c) - 65)
        for i, c in enumerate(body)
    )
    return body + chr(65 + total % 26)


def nl_bsn(rng: random.Random) -> str:
    while True:
        digits = [rng.randint(1, 9)] + [rng.randint(0, 9) for _ in range(7)]
        last = sum(d * w for d, w in zip(digits, range(9, 1, -1), strict=True)) % 11
        if last < 10:
            return "".join(map(str, digits)) + str(last)


def ro_cnp(rng: random.Random, birth: dt.date, gender: str) -> str:
    sex = (1 if gender == "m" else 2) + (4 if birth.year >= 2000 else 0)
    body = f"{sex}{birth:%y%m%d}{rng.randint(1, 46):02d}{rng.randint(1, 999):03d}"
    check = sum(int(c) * int(w) for c, w in zip(body, "279146358279", strict=True)) % 11
    return body + str(1 if check == 10 else check)


def ie_ppsn(rng: random.Random) -> str:
    digits = [rng.randint(0, 9) for _ in range(7)]
    total = sum(d * w for d, w in zip(digits, range(8, 1, -1), strict=True)) + 9 * 1  # "A"
    return "".join(map(str, digits)) + "WABCDEFGHIJKLMNOPQRSTUV"[total % 23] + "A"


def mt_id_card(rng: random.Random) -> str:
    return f"{rng.randint(1, 999)}{rng.randint(0, 9999):04d}{rng.choice('MMMG')}"


# --- Generator --------------------------------------------------------------------------------


class Identities:
    """Fictional people, companies and institutions for one language and one document."""

    def __init__(self, lang: Lang, rng: random.Random) -> None:
        self.lang = lang
        self.rng = rng
        self._used: set[str] = set()

    def _digits(self, n: int) -> str:
        return "".join(self.rng.choice("0123456789") for _ in range(n))

    def _letters(self, n: int, alphabet: str = "ABCDEFGHJKLMNPRSTUVZ") -> str:
        return "".join(self.rng.choice(alphabet) for _ in range(n))

    def date(self, day: dt.date) -> str:
        fmt = self.rng.choice(self.lang.date_formats)
        return fmt.format(
            d=day.day, m=day.month, y=day.year, iso=day.isoformat(),
            mon=self.lang.months_gen[day.month - 1],
        )  # fmt: skip

    def birth(self) -> dt.date:
        start = dt.date(1945, 1, 1).toordinal()
        return dt.date.fromordinal(self.rng.randint(start, dt.date(2004, 12, 31).toordinal()))

    def address(self, town_index: int | None = None) -> str:
        town, posts, _, _ = (
            self.lang.towns[town_index]
            if town_index is not None
            else self.rng.choice(self.lang.towns)
        )
        num = str(self.rng.randint(1, 160))
        if self.rng.random() < 0.3:
            code = self.lang.code
            if code in {"lv", "lt"}:
                num += f"-{self.rng.randint(1, 60)}"
            elif code in {"hr", "sl", "ro"}:
                num += f"/{self.rng.randint(1, 60)}"
            elif code == "nl":
                num += self.rng.choice(["A", "B", "-1", "-2", " bis"])
        return self.lang.address_format.format(
            street=self.rng.choice(self.lang.streets), num=num, town=town,
            post=self.rng.choice(posts),
        )  # fmt: skip

    def phone(self) -> str:
        r, d = self.rng, self._digits
        code = self.lang.code
        if code == "lv":
            return r.choice([f"+371 2{d(3)} {d(4)}", f"2{d(7)}", f"+371 67{d(6)}"])
        if code == "lt":
            return r.choice([f"+370 6{d(2)} {d(5)}", f"86{d(2)} {d(5)}", f"+370 5 {d(3)} {d(4)}"])
        if code in _PHONES:
            return r.choice(_PHONES[code])(d, r)
        if code == "hr":
            op = r.choice(["91", "92", "95", "98", "99"])
            return r.choice(
                [f"+385 {op} {d(3)} {d(4)}", f"0{op} {d(3)} {d(4)}", f"01 {d(4)} {d(3)}"]
            )
        op = r.choice(["31", "40", "41", "51", "64", "70"])
        return r.choice(
            [f"+386 {op} {d(3)} {d(3)}", f"0{op} {d(3)} {d(3)}", f"01 {d(3)} {d(2)} {d(2)}"]
        )

    def bank_account(self) -> str:
        c, d = self.lang.country, self._digits
        bban = {
            "LV": lambda: self._letters(4, "ABCDEFGHIJKLMNOPQRSTUVWXYZ") + d(13),
            "LT": lambda: d(16),
            "HR": lambda: d(17),
            "SI": lambda: d(15),
            "FR": lambda: d(23),
            "ES": lambda: d(20),
            "IT": lambda: self._letters(1, "ABCDEFGHIJKLMNOPQRSTUVWXYZ") + d(22),
            "NL": lambda: self._letters(4, "ABCDEFGHIJKLMNOPQRSTUVWXYZ") + d(10),
            "RO": lambda: self._letters(4, "ABCDEFGHIJKLMNOPQRSTUVWXYZ") + d(16),
            "IE": lambda: self._letters(4, "ABCDEFGHIJKLMNOPQRSTUVWXYZ") + d(14),
            "MT": lambda: self._letters(4, "ABCDEFGHIJKLMNOPQRSTUVWXYZ") + d(23),
        }[c]()
        return iban(c, bban, grouped=self.rng.random() < 0.75)

    def id_document(self, birth: dt.date, gender: str, given: str = "", family: str = "") -> str:
        code, rng = self.lang.code, self.rng
        if code == "fr":
            return fr_nir(rng, birth, gender)
        if code == "es":
            return es_dni(rng)
        if code == "it":
            return it_codice_fiscale(rng, given, family, birth, gender)
        if code == "nl":
            return nl_bsn(rng)
        if code == "ro":
            return ro_cnp(rng, birth, gender)
        if code == "ga":
            return ie_ppsn(rng)
        if code == "mt":
            return mt_id_card(rng)
        if code == "lv":
            return lv_personal_code(self.rng, birth)
        if code == "lt":
            return lt_personal_code(self.rng, birth, gender)
        if code == "hr":
            return hr_oib(self.rng)
        return si_emso(self.rng, birth, gender)

    def plate(self) -> str:
        code, d, L = self.lang.code, self._digits, self._letters
        if code == "lv":
            return f"{L(2)}-{self.rng.randint(1, 9999)}"
        if code == "lt":
            return f"{L(3)} {d(3)}"
        r = self.rng
        if code == "fr":
            return f"{L(2)}-{d(3)}-{L(2)}"
        if code == "es":
            return f"{d(4)} {L(3, 'BCDFGHJKLMNPRSTVWXYZ')}"
        if code == "it":
            return f"{L(2)} {d(3)} {L(2)}"
        if code == "nl":
            return r.choice(
                [f"{L(2)}-{d(3)}-{L(1)}", f"{d(1)}-{L(3)}-{d(2)}", f"{L(3)}-{d(2)}-{L(1)}"]
            )
        if code == "ro":
            county = r.choice(["B", "CJ", "IS", "TM", "BV", "CT", "DJ", "SB"])
            return f"{county} {d(3 if county == 'B' and r.random() < 0.3 else 2)} {L(3)}"
        if code == "ga":
            county = r.choice(["D", "C", "G", "L", "KY", "SO", "WD"])
            return f"{r.randint(12, 25)}{r.choice('12')}-{county}-{r.randint(1, 99999)}"
        if code == "mt":
            return f"{L(3)} {d(3)}"
        if code == "hr":
            return f"{self.rng.choice(['ZG', 'ST', 'RI', 'OS', 'ZD', 'PU', 'VŽ'])} {d(4)}-{L(2)}"
        return f"{self.rng.choice(['LJ', 'MB', 'CE', 'KR', 'KP', 'NM'])} {L(2)}-{d(3)}"

    def _name(self, gender: str) -> tuple[str, str]:
        for _ in range(50):
            given = self.rng.choice(self.lang.given_f if gender == "f" else self.lang.given_m)
            male, female = self.rng.choice(self.lang.surnames)
            family = self.rng.choice(female) if gender == "f" else male
            if self.lang.extra.get("compound_surname"):  # Spanish: García López
                second = self.rng.choice(self.lang.surnames)[0]
                if second == male or second in self._used:
                    continue
                family = male = f"{male} {second}"
                female = (family,)
                if family.split()[0] in self._used:
                    continue
            if given not in self._used and family not in self._used and male not in self._used:
                self._used |= {given, family, male, *female}
                return given, family
        return given, family  # pragma: no cover

    def person(self, fields: list[str]) -> list[Planted]:
        gender = self.rng.choice("fm")
        given, family = self._name(gender)
        birth = self.birth()
        values = {
            "name": f"{given} {family}",
            "date_of_birth": self.date(birth),
            "address": self.address(),
            "email": email_address(self.rng, given, family, birth.year),
            "phone": self.phone(),
            "id_document": self.id_document(birth, gender, given, family),
            "bank_account": self.bank_account(),
            "plate": self.plate(),
        }
        out = [
            Planted(
                f,
                FIELD_TYPES[f],
                values[f],
                given=given if f == "name" else "",
                family=family if f == "name" else "",
                gender=gender if f == "name" else "",
            )
            for f in fields
        ]
        return out

    def company(self, fields: list[str]) -> list[Planted]:
        short = self.rng.choice([a for a in self.lang.company_a if a not in self._used])
        self._used.add(short)
        name = self.lang.company_format.format(
            form=self.rng.choice(self.lang.company_forms), name=short
        )
        from pii_guard.eval.identities import _slug

        values = {
            "org_name": name,
            "address": self.address(),
            "email": f"{self.rng.choice(_mailboxes(self.lang.code))}@{_slug(short, '-')}.example",
            "phone": self.phone(),
            "bank_account": self.bank_account(),
        }
        out = [Planted(f, FIELD_TYPES[f], values[f]) for f in fields]
        out.append(Planted("short_name", EntityType.ORGANIZATION, short, required=False))
        return out

    def institution(self, kind: str, fields: list[str]) -> list[Planted]:
        index = self.rng.randrange(len(self.lang.towns))
        _, _, court, office = self.lang.towns[index]
        values = {
            "org_name": court if kind == "court" else office,
            "address": self.address(index),
            "phone": self.phone(),
        }
        return [Planted(f, FIELD_TYPES[f], values[f]) for f in fields]

    def make(self, kind: str, fields: list[str]) -> list[Planted]:
        if kind == "person":
            return self.person(fields)
        if kind == "company":
            return self.company(fields)
        if kind == "property":
            return [Planted("address", EntityType.ADDRESS, self.address())]
        return self.institution(kind, fields)


_MAILBOX = {"lv": "birojs", "fr": "contact", "es": "contacto", "it": "ufficio", "nl": "kantoor",
            "ro": "contact", "ga": "eolas", "mt": "ufficcju"}  # fmt: skip


def _mailboxes(code: str) -> list[str]:
    return ["info", _MAILBOX.get(code, "ured"), "office"]


#: National phone shapes of the phase-1b packs: ``(digits, rng) -> number``.
_PHONES: dict[str, tuple] = {
    "fr": (
        lambda d, r: f"+33 {r.choice('67')} {d(2)} {d(2)} {d(2)} {d(2)}",
        lambda d, r: f"0{r.choice('67')} {d(2)} {d(2)} {d(2)} {d(2)}",
        lambda d, r: f"0{r.choice('12345')} {d(2)} {d(2)} {d(2)} {d(2)}",
    ),
    "es": (
        lambda d, r: f"+34 6{d(2)} {d(3)} {d(3)}",
        lambda d, r: f"6{d(2)} {d(2)} {d(2)} {d(2)}",
        lambda d, r: f"9{r.choice('1345')} {d(3)} {d(2)} {d(2)}",
    ),
    "it": (
        lambda d, r: f"+39 3{d(2)} {d(3)} {d(4)}",
        lambda d, r: f"3{d(2)} {d(7)}",
        lambda d, r: f"0{r.choice(['6', '2', '11', '51', '55'])} {d(4)} {d(4)}",
    ),
    "nl": (
        lambda d, r: f"+31 6 {d(4)} {d(4)}",
        lambda d, r: f"06-{d(8)}",
        lambda d, r: f"0{r.choice(['20', '10', '30', '70'])} {d(3)} {d(4)}",
    ),
    "ro": (
        lambda d, r: f"+40 7{d(2)} {d(3)} {d(3)}",
        lambda d, r: f"07{d(2)} {d(3)} {d(3)}",
        lambda d, r: f"021 {d(3)} {d(4)}",
    ),
    "ga": (
        lambda d, r: f"+353 8{r.choice('35679')} {d(3)} {d(4)}",
        lambda d, r: f"08{r.choice('35679')} {d(3)} {d(4)}",
        lambda d, r: f"0{r.choice(['1', '21', '91', '61'])} {d(3)} {d(4)}",
    ),
    "mt": (
        lambda d, r: f"+356 79{d(2)} {d(4)}",
        lambda d, r: f"99{d(2)} {d(4)}",
        lambda d, r: f"21{d(2)} {d(4)}",
    ),
}


FIELD_TYPES: dict[str, EntityType] = {
    "name": EntityType.PERSON,
    "date_of_birth": EntityType.DATE_OF_BIRTH,
    "address": EntityType.ADDRESS,
    "email": EntityType.EMAIL,
    "phone": EntityType.PHONE,
    "id_document": EntityType.ID_DOCUMENT,
    "bank_account": EntityType.BANK_ACCOUNT,
    "plate": EntityType.VEHICLE_PLATE,
    "org_name": EntityType.ORGANIZATION,
}
