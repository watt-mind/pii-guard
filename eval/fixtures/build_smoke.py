"""Build the hand-written smoke fixtures: ``hu-smoke.jsonl``, ``en-smoke.jsonl`` and
``hu-inflection.jsonl`` (Hungarian stem-changing forms of names).

Every person, address, number and organisation below is **fictional** (ADR 0005). Names use
placeholder-style Hungarian and English surnames; e-mail domains are the reserved
``example.com`` / ``example.org`` / ``example.net``; English phone numbers come from ranges set
aside for drama and fiction. Checksummed identifiers are computed from made-up payloads with
:mod:`pii_guard.detect.checksums`, so they are valid in form but issued to nobody.

Labels are written inline as ``{{TYPE|value}}`` (see :func:`pii_guard.eval.from_markup`), so
offsets are never typed by hand. Hungarian suffixes that leave the value intact stay outside
the label (``{{PERSON|Teszt Elek}}nek``); a stem-changing form is labelled as a whole word.

Regenerate after editing (a test fails if the committed files are stale)::

    uv run python eval/fixtures/build_smoke.py
"""

from __future__ import annotations

from pathlib import Path

from pii_guard.detect.checksums import (
    giro_check_digit,
    hu_tax_id_check_digit,
    hu_tax_number_check_digit,
    iban_check_digits,
    taj_check_digit,
)
from pii_guard.eval import Document, from_markup, label, write_fixtures

HERE = Path(__file__).resolve().parent


# --- Fictional identifiers -------------------------------------------------------------


def tax_id(payload9: str) -> str:
    """A checksum-valid adóazonosító jel (10 digits, starts with 8)."""
    check = hu_tax_id_check_digit(payload9)
    if check is None:
        raise ValueError("payload has no valid check digit; pick another")
    return payload9 + str(check)


def bad_tax_id(payload9: str) -> str:
    """Looks like a tax ID, fails the checksum."""
    good = tax_id(payload9)
    return good[:9] + str((int(good[9]) + 1) % 10)


def taj(payload8: str, sep: str = " ") -> str:
    digits = payload8 + str(taj_check_digit(payload8))
    return sep.join((digits[:3], digits[3:6], digits[6:]))


def bad_taj(payload8: str, sep: str = " ") -> str:
    digits = payload8 + str((taj_check_digit(payload8) + 1) % 10)
    return sep.join((digits[:3], digits[3:6], digits[6:]))


def _giro_block(payload: str) -> str:
    return payload + str(giro_check_digit(payload))


def giro(bank7: str, account: str, sep: str = "-") -> str:
    """A checksum-valid giro account: 8 + 8 digits (7-digit account) or 8 + 16 (15-digit)."""
    first = _giro_block(bank7)
    second = _giro_block(account)
    if len(second) == 8:
        return f"{first}{sep}{second}"
    return f"{first}{sep}{second[:8]}{sep}{second[8:]}"


def hu_iban(bank7: str, account15: str, grouped: bool = True) -> str:
    bban = giro(bank7, account15, sep="")
    compact = "HU" + iban_check_digits("HU", bban) + bban
    return " ".join(compact[i : i + 4] for i in range(0, len(compact), 4)) if grouped else compact


def iban(country: str, bban: str, grouped: bool = True) -> str:
    compact = country + iban_check_digits(country, bban) + bban
    return " ".join(compact[i : i + 4] for i in range(0, len(compact), 4)) if grouped else compact


def company_tax_number(base7: str, vat: str = "2", area: str = "42") -> str:
    return f"{base7}{hu_tax_number_check_digit(base7)}-{vat}-{area}"


def bad_company_tax_number(base7: str) -> str:
    return f"{base7}{(hu_tax_number_check_digit(base7) + 1) % 10}-2-42"


# Shorthands for inline labels.
def P(v: str) -> str:
    return label("PERSON", v)


def A(v: str) -> str:
    return label("ADDRESS", v)


def E(v: str) -> str:
    return label("EMAIL", v)


def PH(v: str) -> str:
    return label("PHONE", v)


def DOB(v: str) -> str:
    return label("DATE_OF_BIRTH", v)


def TAX(v: str) -> str:
    return label("NATIONAL_ID_HU_TAX", v)


def TAJ(v: str) -> str:
    return label("NATIONAL_ID_HU_TAJ", v)


def IDD(v: str) -> str:
    return label("ID_DOCUMENT", v)


def BANK(v: str) -> str:
    return label("BANK_ACCOUNT", v)


def CO(v: str) -> str:
    return label("COMPANY_ID_HU", v)


def ORG(v: str) -> str:
    return label("ORGANIZATION", v)


def HRSZ(v: str) -> str:
    return label("PARCEL_NUMBER_HU", v)


def PLATE(v: str) -> str:
    return label("VEHICLE_PLATE", v)


# --- Hungarian ---------------------------------------------------------------------------

TAX_1 = tax_id("812345678")
TAX_2 = tax_id("834567012")
TAX_3 = tax_id("856565651")
TAJ_1 = taj("12345678")
TAJ_2 = taj("20304050", sep="-")
TAJ_3 = taj("98765432", sep="")
GIRO_1 = giro("1199999", "0000123")
GIRO_2 = giro("1088888", "000000000045678")
IBAN_HU_1 = hu_iban("1177777", "000000012345678")
IBAN_HU_2 = hu_iban("1066666", "000000098765432", grouped=False)
CO_TAX_1 = company_tax_number("1234567")
CO_TAX_2 = company_tax_number("2345678", vat="2", area="13")


def hu_documents() -> list[Document]:
    docs: list[tuple[str, str, dict[str, object]]] = [
        (
            "hu-contract-0001",
            "ADÁSVÉTELI SZERZŐDÉS\n\n"
            f"Eladó: {P('Teszt Elek')} (született: {DOB('1971. március 4.')}, "
            f"adóazonosító jel: {TAX(TAX_1)}, lakcím: {A('1051 Budapest, Minta utca 12. 3/5.')}), "
            f"Vevő: {P('Gipsz Jakab')} (szül. {DOB('1985.11.23.')}, "
            f"adóazonosító jel: {TAX(TAX_2)}, "
            f"lakcím: {A('6720 Szeged, Képzelt tér 4.')}).\n"
            f"Az ingatlan: Budapest belterület, {HRSZ('28145/3')} helyrajzi számú lakás. "
            "A vételár 48 500 000 Ft, azaz negyvennyolcmillió-ötszázezer forint, amelyet a Vevő "
            f"a {BANK(GIRO_1)} számú bankszámlára utal.",
            {"kind": "contract"},
        ),
        (
            "hu-contract-0002",
            "BÉRLETI SZERZŐDÉS\n\n"
            f"Bérbeadó: {ORG('Kitalált Ingatlan Kft.')} (cégjegyzékszám: Cg. {CO('01-09-123456')}, "
            f"adószám: {CO(CO_TAX_1)}), képviseli {P('Minta Márta')} ügyvezető.\n"
            f"Bérlő: {P('Próba Piroska')}, anyja neve: {P('Példa Ilona')}, személyi igazolvány "
            f"száma: {IDD('123456AB')}, TAJ: {TAJ(TAJ_1)}.\n"
            f"A bérlemény címe: {A('9021 Győr, Gyöngyvirág utca 7. fszt. 2.')}. "
            "A havi bérleti díj 185 000 Ft, a kaució két havi bérnek megfelelő összeg.",
            {"kind": "contract"},
        ),
        (
            "hu-poa-0003",
            "MEGHATALMAZÁS\n\n"
            f"Alulírott {P('Kovács Teszt Ödön')} ({DOB('1960. január 30.')}-án született, "
            f"lakik: {A('3300 Eger, Próba köz 1.')}) meghatalmazom {P('Mintás Ilona')} "
            f"ügyvédet ({ORG('Mintás és Társa Ügyvédi Iroda')}), hogy a "
            f"{HRSZ('1452/7')} hrsz. alatti ingatlan ügyében a földhivatal előtt eljárjon.",
            {"kind": "power-of-attorney"},
        ),
        (
            "hu-landreg-0004",
            "TULAJDONI LAP - NEM HITELES MÁSOLAT\n"
            f"Település: Kecskemét, helyrajzi szám: {HRSZ('0412/18')}\n"
            f"Tulajdonos: {P('Képzelt Béla')}, cím: {A('6000 Kecskemét, Kitalált sor 33.')}\n"
            "Tulajdoni hányad: 1/1. Széljegy: nincs. Bejegyző határozat: 2019. május 6.",
            {"kind": "land-registry"},
        ),
        (
            "hu-letter-0005",
            f"Tisztelt {P('Gipsz Jakab')} Úr!\n\n"
            "Értesítjük, hogy a 2026/1187. számú ügyben a tárgyalást november 12-én 9 órakor "
            "tartjuk. Kérjük, hozza magával személyazonosító igazolványát és lakcímkártyáját. "
            f"Kérdés esetén hívja a {PH('+36 1 234 5678')} számot.\n\nÜdvözlettel:\n"
            f"{P('Teszt Elekné')} bírósági titkár",
            {"kind": "court-notice"},
        ),
        (
            "hu-invoice-0006",
            f"SZÁMLA - {ORG('Próbafa Asztalos Bt.')}, adószám: {CO(CO_TAX_2)}\n"
            f"Vevő: {P('Példa Pál')}, {A('7621 Pécs, Mintakert utca 18.')}\n"
            "Számlaszám: 2026-000418. Teljesítés: 2026. október 20. Összeg: 236 220 Ft. "
            f"Átutalás: {BANK(IBAN_HU_1)}.",
            {"kind": "invoice"},
        ),
        (
            "hu-email-0007",
            f"Szia {P('Márta')}!\n\nKüldöm a papírokat, a TAJ számom {TAJ(TAJ_2)}, "
            "az adóazonosítóm "
            f"{TAX(TAX_3)}. Ha valami kell, írj a {E('teszt.elek@example.com')} címre vagy "
            f"hívj a {PH('06 30 123 4567')} számon.\n\nPuszi, {P('Elek')}",
            {"kind": "email"},
        ),
        (
            "hu-email-0008",
            f"Tárgy: kaució visszautalása\n\nKedves {P('Próba Piroska')}!\n\n"
            f"A kauciót a {BANK(GIRO_2)} számlaszámra utaltuk vissza. A számlakivonatot a "
            f"{E('ugyfelszolgalat@example.org')}-ra küldtük.\n\n{P('Minta Márta')}\n"
            f"{ORG('Kitalált Ingatlan Kft.')}",
            {"kind": "email"},
        ),
        (
            "hu-chat-0009",
            f"szia, en {P('Gipsz Jakab')} vagyok, az autom rendszama {PLATE('TES-123')}, "
            f"holnap tudnal jonni? a szamom {PH('+36 70 555 0123')}",
            {"kind": "chat", "tags": ["informal", "no-diacritics"]},
        ),
        (
            "hu-chat-0010",
            f"Az új kocsi rendszáma {PLATE('AB CD-456')}, a régi {PLATE('PRB-987')}-et eladtam "
            f"{P('Teszt Elek')}nek. Ő {A('Debrecen, Kitalált utca 5.')} alatt lakik.",
            {"kind": "chat"},
        ),
        (
            "hu-chat-0011",
            f"jo reggelt! {P('Minta Annának')} odaadtam a kulcsot, a szigszamat is lefotoztam: "
            f"{IDD('654321CD')}. a cime {A('1134 Budapest, Képzelt utca 41.')}",
            {"kind": "chat", "tags": ["inflected-stem"]},
        ),
        (
            "hu-email-0012",
            f"Tisztelt {P('Kovács Teszt Ödön')}!\n\nAz útlevél ({IDD('BA1234567')}) megérkezett. "
            f"Átvehető a {A('3300 Eger, Próba köz 1.')} szám alatti irodánkban, vagy "
            f"{P('Kovács Teszt Ödön')}nel egyeztetett időpontban kiszállítjuk. Telefon: "
            f"{PH('06-20-987-6543')}.",
            {"kind": "email"},
        ),
        (
            "hu-contract-0013",
            "KÖLCSÖNSZERZŐDÉS\n\n"
            f"Kölcsönadó: {P('Bárány Hajnal')}, Kölcsönvevő: {P('Fekete Virág')}. "
            "A kölcsön összege 2 000 000 Ft, visszafizetés havi 50 000 Ft részletekben. "
            f"Kölcsönvevő bankszámlája: {BANK(IBAN_HU_2)}. "
            f"Kölcsönvevő TAJ száma: {TAJ(TAJ_3)}.",
            {"kind": "contract", "tags": ["common-word-names"]},
        ),
        (
            "hu-letter-0014",
            f"Kedves {P('Szabó Molnár Kata')}!\n\n"
            f"Gratulálunk! A pályázatát a {ORG('Mintavár Közösségi Alapítvány')} kuratóriuma "
            f"támogatta. Kérjük, igazolja a születési dátumát ({DOB('1999. 08. 15.')}) és "
            f"küldje el a {E('palyazat@example.net')} címre.",
            {"kind": "letter", "tags": ["common-word-names"]},
        ),
        (
            "hu-poa-0015",
            "MEGHATALMAZÁS GÉPJÁRMŰ ÁTÍRÁSÁHOZ\n\n"
            f"Alulírott {P('Példa Pál')} (szül.: Pécs, {DOB('1978.04.09.')}, "
            f"személyi ig. szám: {IDD('987654EF')}) meghatalmazom {P('Képzelt Bélát')}, hogy "
            f"a {PLATE('MNT-321')} forgalmi rendszámú gépjárművet a nevemben átírassa. "
            f"Vezetői engedély száma: {IDD('CB765432')}.",
            {"kind": "power-of-attorney"},
        ),
        (
            "hu-email-0016",
            f"Tárgy: Re: ajánlat\n\n{P('Gipsz Jakab')} írta:\n"
            f"> Küldd el a {ORG('Próbafa Asztalos Bt.')} "
            f"ajánlatát!\n\nItt van. Az elérhetőségük {PH('+36 (1) 456 7890')}, "
            f"e-mail: {E('iroda@probafa.example.com')}.",
            {"kind": "email", "tags": ["quoted-reply"]},
        ),
        (
            "hu-letter-0017",
            "Tárgy: lakcímváltozás bejelentése\n\n"
            f"Új lakcímem: {A('2400 Dunaújváros,\nMinta Pál utca 9. 2. em. 8.')}\n"
            f"Régi lakcímem: {A('8200 Veszprém, Próba utca 3.')}\n"
            f"Aláírás: {P('Mintás Ilona')}",
            {"kind": "letter", "tags": ["address-across-lines"]},
        ),
        (
            "hu-contract-0018",
            "VÁLLALKOZÁSI SZERZŐDÉS\n\n"
            f"Megrendelő: {ORG('Mintavár Építő Zrt.')} (Cg. {CO('13-10-041234')}), "
            f"Vállalkozó: {P('Molnár Teszt Lajos')} egyéni vállalkozó, adóazonosító jel: "
            f"{TAX(tax_id('845454546'))}. A munkaterület: Szentendre, {HRSZ('2231/14')} hrsz. "
            "A vállalkozói díj nettó 12 400 000 Ft + ÁFA, a teljesítési határidő 2027. március 31.",
            {"kind": "contract"},
        ),
        (
            "hu-chat-0019",
            f"{P('Virág')}, felhívnád {P('Fekete')} urat? a szama {PH('+36 30 765 4321')}, "
            f"az email cime {E('fekete.u@example.com')}",
            {"kind": "chat", "tags": ["common-word-names"]},
        ),
        (
            "hu-email-0020",
            f"Kedves {P('Képzelt Béla')}!\n\nA {ORG('Példa Biztosító Zrt.')} kárbejelentését "
            f"rögzítettük. Gépjármű: {PLATE('AA BB-001')}. A kárszám: 2026-KB-00731. "
            f"A kártérítést a {BANK(giro('1155555', '0000777'))} számlára utaljuk.",
            {"kind": "email"},
        ),
        # Hard negatives: identifier look-alikes, common words, non-birth dates. No PII.
        (
            "hu-negative-0021",
            f"Rendelésszám: {bad_tax_id('812345678')}. Cikkszám: {bad_taj('12345678')}. "
            "A szállítás 2026. november 3-án várható, a csomag súlya 12,5 kg. Ügyfélszolgálat: "
            "munkanapokon 8 és 16 óra között.",
            {"kind": "notice", "tags": ["hard-negative"]},
        ),
        (
            "hu-negative-0022",
            "A kertben fekete virág nyílt, a szabó és a molnár a hajnal első óráiban indult a "
            "vásárba. A bárány a kovács udvarán legelt.",
            {"kind": "prose", "tags": ["hard-negative", "common-words"]},
        ),
        (
            "hu-negative-0023",
            "Az ülés jegyzőkönyve: a 2026. évi költségvetés 1 234 567 890 Ft. A 4/2026. (X. 12.) "
            f"számú határozat elfogadva. Hivatkozási szám: {bad_company_tax_number('1234567')}. "
            "A következő ülés 2026. december 1-jén 10:00-kor lesz a 2. emeleti tárgyalóban.",
            {"kind": "minutes", "tags": ["hard-negative"]},
        ),
        (
            "hu-negative-0024",
            "Termékkód: ABC-1234, tétel: XY-12. A modell gyártási éve 1999, a garancia 24 hónap. "
            "A szerződés kelte: 2026. október 26. Az 1848-as forradalom évfordulóján zárva.",
            {"kind": "notice", "tags": ["hard-negative"]},
        ),
        (
            "hu-mixed-0025",
            f"Hi {P('Teszt Elek')}, the Hungarian tax ID you sent ({TAX(TAX_1)}) is fine. "
            f"Please also send your TAJ ({TAJ(TAJ_1)}). Kösz, {P('Minta Márta')}",
            {"kind": "email", "tags": ["mixed-language"]},
        ),
        (
            "hu-letter-0026",
            f"Tisztelt Hölgyem!\n\nÉrtesítjük, hogy {P('Példa Ilona')} (szül. idő: "
            f"{DOB('1952. december 24.')}, TAJ: {TAJ(taj('31415926'))}) a "
            f"{ORG('Képzelt Városi Kórház')} belgyógyászati osztályára került felvételre.",
            {"kind": "letter"},
        ),
        (
            "hu-chat-0027",
            f"ok, utald a {BANK(hu_iban('1033333', '000000055500111'))}-ra, a megjegyzésbe írd be "
            f"hogy {P('Gipsz')}. a cím {A('1096 Budapest, Kitalált u. 2/b')}",
            {"kind": "chat"},
        ),
        (
            "hu-email-0028",
            f"Tárgy: hiányzó adatok\n\nKedves {P('Szabó Molnár Kata')}!\n\nA nyilvántartásunkban "
            f"a következő szerepel: {E('kata.sz.m@example.org')}, {PH('+36 20 111 2233')}, "
            f"{A('4025 Debrecen, Mintás tér 6.')}. Kérjük, jelezze, ha változott.",
            {"kind": "email"},
        ),
    ]
    return [from_markup(doc_id, text, language="hu", meta=meta) for doc_id, text, meta in docs]


# --- English -----------------------------------------------------------------------------


def en_documents() -> list[Document]:
    iban_gb = iban("GB", "EXMP00000012345678")
    iban_de = iban("DE", "100000000123456789")
    docs: list[tuple[str, str, dict[str, object]]] = [
        (
            "en-email-0001",
            f"Subject: tenancy\n\nHi {P('Jane Example')},\n\nThe deposit will be returned to "
            f"{BANK(iban_gb)}. Call me on {PH('+44 20 7946 0123')} or reply to "
            f"{E('jane.example@example.com')}.\n\nBest,\n{P('John Sample')}",
            {"kind": "email"},
        ),
        (
            "en-contract-0002",
            "SERVICE AGREEMENT\n\n"
            f"This agreement is made between {ORG('Fictional Widgets Ltd')} and "
            f"{P('Alex Placeholder')} (born {DOB('14 March 1988')}), residing at "
            f"{A('12 Sample Road, Exampleton EX1 2AB')}. Payments are made to {BANK(iban_de)}.",
            {"kind": "contract"},
        ),
        (
            "en-letter-0003",
            f"Dear {P('Ms Testwood')},\n\nYour passport {IDD('X1234567')} is ready for "
            f"collection at {A('400 Imaginary Avenue, Suite 9, Springfield')}. Please bring a "
            f"copy of this letter.\n\n{ORG('Example County Records Office')}",
            {"kind": "letter"},
        ),
        (
            "en-chat-0004",
            f"hey its {P('Sam Dummy')}, my new number is {PH('+1 202 555 0143')}, "
            f"email {E('sam.dummy@example.net')}. car plate is {PLATE('EX12 MPL')} btw",
            {"kind": "chat", "tags": ["informal"]},
        ),
        (
            "en-email-0005",
            "Subject: invoice 2026-0042\n\n"
            f"Please pay EUR 1,250.00 to {BANK(iban('NL', 'EXMP0123456789'))} "
            f"by 30 November 2026. Questions: {E('billing@example.org')} or "
            f"{PH('+31 20 555 0199')}.\n\n{ORG('Sample Consulting B.V.')}",
            {"kind": "email"},
        ),
        (
            "en-letter-0006",
            f"To whom it may concern,\n\nI confirm that {P('Robin Exampleford')}, date of birth "
            f"{DOB('02/07/1991')}, has lived at {A('Flat 3, 77 Fiction Lane, Exampleton EX4 9ZZ')} "
            "since 2019.\n\nYours faithfully,\n"
            f"{P('Chris Mockley')}, {ORG('Mockley & Partners')}",
            {"kind": "letter"},
        ),
        (
            "en-mixed-0007",
            f"Hi {P('Teszt Elek')}, we received your Hungarian tax ID {TAX(TAX_2)} and your "
            f"bank details ({BANK(IBAN_HU_1)}). Kind regards, {P('Jane Example')}",
            {"kind": "email", "tags": ["mixed-language"]},
        ),
        (
            "en-negative-0008",
            "Order 4417-2209-3301 shipped on 3 November 2026. Reference GB00 0000 0000, "
            "tracking number 1Z999AA10123456784. Customer support is open 9am to 5pm, Monday "
            "to Friday. Room 101, Building 7.",
            {"kind": "notice", "tags": ["hard-negative"]},
        ),
        (
            "en-negative-0009",
            "The baker and the smith walked down Bishop Street past the Rose and Crown. "
            "May turned to June, and Hope was in the air.",
            {"kind": "prose", "tags": ["hard-negative", "common-words"]},
        ),
        (
            "en-chat-0010",
            f"meet at {A('5 Placeholder Square, Exampleton')} at 7? ask for {P('Dana')}. "
            f"my mobile {PH('+44 7700 900123')}",
            {"kind": "chat"},
        ),
    ]
    return [from_markup(doc_id, text, language="en", meta=meta) for doc_id, text, meta in docs]


def hu_inflection_documents() -> list[Document]:
    """Hungarian names whose stem changes before a suffix, each in several cases.

    A final ``a``/``e`` lengthens (``Zsuzsanna`` -> ``Zsuzsannának``), a final digraph doubles
    (``Szabolcs`` -> ``Szabolccsal``), a single final consonant doubles into ``-val``
    (``Elek`` -> ``Elekkel``). Measures that every form is masked by one placeholder
    (placeholder consistency) and that the suffix stays outside it.
    """
    docs = [
        (
            "hu-inflection-0001",
            f"{P('Próba Zsuzsannának')} küldtük a levelet. {P('Próba Zsuzsanna')} holnap "
            f"válaszol, {P('Próba Zsuzsannát')} hívjuk. E-mail: {E('zsuzsanna.proba@example.com')}",
            {"kind": "email", "tags": ["inflected-stem", "vowel-lengthening"]},
        ),
        (
            "hu-inflection-0002",
            f"A szerződést {P('Minta Kende')} írta alá. {P('Minta Kendének')} megküldtük, "
            f"{P('Minta Kendét')} a jövő héten keressük, {P('Minta Kendével')} egyeztetünk. "
            f"Telefon: {PH('+36 30 555 0142')}.",
            {"kind": "letter", "tags": ["inflected-stem", "vowel-lengthening"]},
        ),
        (
            "hu-inflection-0003",
            f"{P('Kovács Szabolcs')} meghatalmazta a cégét. A {P('Kovács Szabolccsal')} kötött "
            f"megállapodás szerint {P('Kovács Szabolcs')}nak kell fizetni a(z) "
            f"{BANK(giro('1177301', '61111018'))} számlára.",
            {"kind": "contract", "tags": ["inflected-stem", "digraph-doubling"]},
        ),
        (
            "hu-inflection-0004",
            f"{P('Teszt Elek')} és {P('Teszt Elek')}kel együtt érkezett {P('Teszt Hajna')}. "
            f"{P('Teszt Hajnának')} átadtuk a kulcsot, {P('Teszt Hajnáról')} és "
            f"{P('Teszt Elek')}ről is készült feljegyzés.",
            {"kind": "note", "tags": ["inflected-stem", "consonant-doubling"]},
        ),
        (
            "hu-inflection-0005",
            f"szia! {P('Példa Emese')} nem ér rá, {P('Példa Emesével')} majd jövő héten "
            f"beszélünk, {P('Példa Emesének')} írj te is. a rendszám {PLATE('PRB-321')}, a "
            f"{PLATE('PRB-321')}-nek lejár a vizsgája.",
            {"kind": "chat", "tags": ["inflected-stem", "vowel-lengthening", "informal"]},
        ),
        (
            "hu-inflection-0006",
            f"Tisztelt {P('Minta Gergely')}! A {P('Minta Gergellyel')} folytatott egyeztetés "
            f"alapján {P('Minta Gergely')}nek küldjük az iratokat a "
            f"{A('6720 Szeged, Kitalált tér 3.')} címre.",
            {"kind": "letter", "tags": ["inflected-stem", "digraph-doubling"]},
        ),
        (
            "hu-inflection-0007",
            f"{P('Próba Kornél')} kor szerint a legidősebb. {P('Próba Kornél')}nak és "
            f"{P('Teszt Zoltán')}nak is szóltunk; {P('Teszt Zoltánt')} holnap hívjuk vissza.",
            {"kind": "note", "tags": ["inflected-look-alike"]},
        ),
        (
            "hu-inflection-0008",
            f"{P('PRÓBA ZSUZSANNA')} (született {DOB('1988. 03. 14.')}) részére. Kérjük, "
            f"{P('Próba Zsuzsannával')} és {P('Minta Kendével')} is közölje a döntést.",
            {"kind": "form", "tags": ["inflected-stem", "upper-case"]},
        ),
    ]
    return [from_markup(doc_id, text, language="hu", meta=meta) for doc_id, text, meta in docs]


OUTPUTS = {
    "hu-smoke.jsonl": hu_documents,
    "en-smoke.jsonl": en_documents,
    "hu-inflection.jsonl": hu_inflection_documents,
}


def main() -> None:
    for name, build in OUTPUTS.items():
        write_fixtures(HERE / name, build())
        print(f"wrote {HERE / name}")


if __name__ == "__main__":
    main()
