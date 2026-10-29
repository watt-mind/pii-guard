"""Fictional identities and name declension for the multilingual NER phase 1 (LAB-1525).

Fictional data only (ADR 0005). Like the generator's Hungarian and English packs, a person is
a common given name and a common surname combined at random, so nobody generated is a real
person; addresses are a random house number on a common street name of a real town; phone,
ID and account numbers are random digits in the national shape (IBANs carry valid check
digits so they look real to a detector, but the bank codes are random). E-mail addresses use
the reserved ``example.*`` domains. Company names are invented two-word names plus a legal
form. Court and municipality names are the real public institutions of the towns (not
personal data).

:func:`name_forms` lists the declined forms of a name token (Latvian, Lithuanian, Croatian and
Slovenian decline names; a form is labelled as a whole word, as ``hu-inflection.jsonl`` does
for Hungarian stem-changing forms). The rules are deliberately generous (they also list some
forms the language doesn't use): a form only becomes a label where the planted name occurs.

Languages: ``lv``, ``lt``, ``hr``, ``sl`` (phase 1, the weakest MAPA languages first).
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

LANGS: dict[str, Lang] = {lang.code: lang for lang in (LV, LT, HR, SL)}


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


def name_forms(language: str, token: str, gender: str = "", is_family: bool = False) -> set[str]:
    """Declined forms of one name token (the token itself included)."""
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
            num += ("-" if self.lang.code in {"lv", "lt"} else "/") + str(self.rng.randint(1, 60))
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
        }[c]()
        return iban(c, bban, grouped=self.rng.random() < 0.75)

    def id_document(self, birth: dt.date, gender: str) -> str:
        code = self.lang.code
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
        if code == "hr":
            return f"{self.rng.choice(['ZG', 'ST', 'RI', 'OS', 'ZD', 'PU', 'VŽ'])} {d(4)}-{L(2)}"
        return f"{self.rng.choice(['LJ', 'MB', 'CE', 'KR', 'KP', 'NM'])} {L(2)}-{d(3)}"

    def _name(self, gender: str) -> tuple[str, str]:
        for _ in range(50):
            given = self.rng.choice(self.lang.given_f if gender == "f" else self.lang.given_m)
            male, female = self.rng.choice(self.lang.surnames)
            family = self.rng.choice(female) if gender == "f" else male
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
            "id_document": self.id_document(birth, gender),
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


def _mailboxes(code: str) -> list[str]:
    return ["info", "birojs" if code == "lv" else "ured", "office"]


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
