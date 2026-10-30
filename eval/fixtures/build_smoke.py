"""Build the hand-written smoke fixtures: ``hu-smoke.jsonl``, ``en-smoke.jsonl``,
``hu-inflection.jsonl`` (Hungarian stem-changing forms of names), ``de-smoke.jsonl`` (the
German language pack's smoke set, see ``docs/languages.md``) and ``pl-smoke.jsonl`` (the
Polish pack's, LAB-1400).

Every person, address, number and organisation below is **fictional** (ADR 0005). Names use
placeholder-style Hungarian and English surnames; e-mail domains are the reserved
``example.com`` / ``example.org`` / ``example.net``; English and German phone numbers come from
ranges set aside for drama and fiction (German: the Bundesnetzagentur drama numbers), and
Hungarian ones use a real area code with an ascending-run or ``555 01xx`` subscriber number
(ADR 0005). Checksummed identifiers are computed from made-up payloads with
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
    hu_personal_id_check_digit,
    hu_tax_id_check_digit,
    hu_tax_number_check_digit,
    iban_check_digits,
    mrz_check_digit,
    taj_check_digit,
)
from pii_guard.eval import Document, from_markup, label, write_fixtures
from pii_guard.languages.de.checksums import (
    is_valid_steuer_id,
    steuer_id_check_digit,
    sv_number_check_digit,
)
from pii_guard.languages.pl.checksums import (
    id_card_check_digit,
    is_valid_pesel,
    nip_check_digit,
    passport_check_digit,
    pesel_check_digit,
    regon_check_digit,
)

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


def personal_id(payload10: str) -> str:
    """A checksum-valid személyi azonosító, written ``S-YYMMDD-NNNC``."""
    check = hu_personal_id_check_digit(payload10)
    if check is None:
        raise ValueError("payload has no valid check digit; pick another")
    return f"{payload10[0]}-{payload10[1:7]}-{payload10[7:]}{check}"


def mrz_td1(doc: str, born: str, sex: str, expires: str, surname: str, given: str) -> str:
    """A TD1 (ID card) machine-readable zone with valid check digits, issued by ``HUN``."""
    number = doc.ljust(9, "<")
    line1 = f"I<HUN{number}{mrz_check_digit(number)}".ljust(30, "<")
    head = f"{born}{mrz_check_digit(born)}{sex}{expires}{mrz_check_digit(expires)}HUN"
    head = head.ljust(29, "<")
    composite = line1[5:30] + head[0:7] + head[8:15] + head[18:29]
    line2 = head + str(mrz_check_digit(composite))
    line3 = f"{surname}<<{given}".ljust(30, "<")
    return "\n".join((line1, line2, line3))


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
            f"{PH('06-20-555-0187')}.",
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
            f"{P('Virág')}, felhívnád {P('Fekete')} urat? a szama {PH('+36 30 345 6789')}, "
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
            f"a következő szerepel: {E('kata.sz.m@example.org')}, {PH('+36 20 555 0161')}, "
            f"{A('4025 Debrecen, Mintás tér 6.')}. Kérjük, jelezze, ha változott.",
            {"kind": "email"},
        ),
        (
            "hu-idcard-0029",
            "SZEMÉLYAZONOSÍTÓ IGAZOLVÁNY (beolvasott másolat)\n"
            f"Név: {P('Próba Piroska')}\nSzemélyi azonosító: {IDD(personal_id('2950817124'))}\n"
            f"Okmányazonosító: {IDD('765432KL')}\n"
            f"{IDD(mrz_td1('765432KL', '950817', 'F', '310817', 'PROBA', 'PIROSKA'))}",
            {"kind": "id_scan"},
        ),
        (
            "hu-contract-0030",
            "TULAJDONJOG-BEJEGYZÉSI KÉRELEM\n\n"
            f"Alulírott {P('Minta Márton')}, a {IDD('345678MN')} számú személyi igazolvánnyal "
            f"és a {IDD('AB2345678')} sz. útlevéllel rendelkező kérelmező kérem, hogy a Vác "
            f"belterület, hrsz.: {HRSZ('0123/4/A/12')} és {HRSZ('0123/4/A/13')} ingatlanokra "
            "1/2 arányú tulajdoni hányadomat jegyezzék be. A kérelem 3/5. oldalán szereplő "
            "adatok a 2026/10. havi állapotot tükrözik.",
            {"kind": "contract"},
        ),
        (
            "hu-court-0031",
            "VÉGZÉS\n\nÜgyszám: 12.P.21.345/2025/7.\nA bíróság a 2025.10.27. napján kelt "
            "keresetlevelet a 3/2025. (X. 27.) számú rendelkezés alapján áttette. A felperes "
            "tulajdoni hányada 1/4, az alperesé 3/4. Az iratok 14/22. oldalán szereplő "
            "számla száma 2026/0042, a rendelésszám AB1234567. Az ingatlan helyrajzi számának "
            "megállapítása folyamatban van.",
            {"kind": "court_notice"},
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


# --- German --------------------------------------------------------------------------


def steuer_id(payload10: str, grouped: bool = True) -> str:
    """A valid Steuer-ID: ten digits with exactly one repeated digit, plus the check digit."""
    digits = payload10 + str(steuer_id_check_digit(payload10))
    if not is_valid_steuer_id(digits):
        raise ValueError("payload has no valid Steuer-ID structure; pick another")
    return f"{digits[:2]} {digits[2:5]} {digits[5:8]} {digits[8:]}" if grouped else digits


def bad_steuer_id(payload10: str) -> str:
    """Looks like a Steuer-ID, fails the check digit."""
    good = steuer_id(payload10, grouped=False)
    return good[:10] + str((int(good[10]) + 1) % 10)


def sv_number(payload11: str, grouped: bool = True) -> str:
    """A valid Sozialversicherungsnummer ``AA DDMMYY L SS C`` from ``AADDMMYYLSS``."""
    value = payload11 + str(sv_number_check_digit(payload11))
    if not grouped:
        return value
    return f"{value[:2]} {value[2:8]} {value[8]} {value[9:11]} {value[11]}"


def de_documents() -> list[Document]:
    iban_de_1 = iban("DE", "100000000123456789")
    iban_de_2 = iban("DE", "370000000987654321", grouped=False)
    st_1, st_2 = steuer_id("4710382946"), steuer_id("5921730481", grouped=False)
    st_3 = steuer_id("3608142973")
    sv_1, sv_2 = sv_number("12150885M01"), sv_number("53270139J48", grouped=False)
    sv_3 = sv_number("28010472B07")
    docs: list[tuple[str, str, dict[str, object]]] = [
        (
            "de-email-0001",
            f"Betreff: Kaution\n\nHallo {P('Erika Beispiel')},\n\ndie Kaution überweisen "
            f"wir auf {BANK(iban_de_1)}. Rückfragen gern unter {PH('+49 30 23125042')} oder an "
            f"{E('erika.beispiel@example.com')}.\n\nViele Grüße\n{P('Jonas Muster')}",
            {"kind": "email"},
        ),
        (
            "de-contract-0002",
            "ARBEITSVERTRAG\n\n"
            f"Zwischen der {ORG('Beispielwerk GmbH')} und {P('Max Platzhalter')}, geboren am "
            f"{DOB('14.03.1988')}, wohnhaft {A('Musterstraße 12, 10115 Berlin')}.\n"
            f"Steuer-ID: {IDD(st_1)}, Sozialversicherungsnummer: {IDD(sv_1)}.\n"
            f"Das Gehalt wird auf das Konto {BANK(iban_de_2)} gezahlt.",
            {"kind": "contract"},
        ),
        (
            "de-letter-0003",
            f"{P('Lena Testmann')}\n{A('Am Beispielweg 3a\n50667 Köln')}\n\n"
            f"Sehr geehrte Frau {P('Testmann')},\n\nbitte rufen Sie uns unter "
            f"{PH('(0221) 4710123')} an. Ihre Rentenversicherungsnummer {IDD(sv_2)} liegt "
            f"uns vor.\n\nMit freundlichen Grüßen\n{ORG('Musterkasse Rheinland')}",
            {"kind": "letter"},
        ),
        (
            "de-chat-0004",
            f"hi, hier ist {P('Tim Fiktiv')}! meine neue nummer ist {PH('0171 3920042')}, "
            f"mail an {E('tim.fiktiv@example.net')} geht auch",
            {"kind": "chat", "tags": ["informal"]},
        ),
        (
            "de-genitive-0005",
            f"{P('Anna Probst')} zieht um. {P('Anna')}s neue Adresse ist "
            f"{A('Lindenallee 7, 04109 Leipzig')}. {P('Hans')}' Fahrrad steht noch im Hof, "
            f"und {P('Probst')}s Briefkasten wird erst im Mai geleert.",
            {"kind": "note", "tags": ["genitive"]},
        ),
        (
            "de-form-0006",
            "Antrag auf Erstattung\n"
            f"Name: {P('Paula Beispielfrau')}\nGeburtsdatum: {DOB('02.07.1979')}\n"
            f"Anschrift: {A('Hauptstraße 101, 80331 München')}\n"
            f"Identifikationsnummer: {IDD(st_2)}\nTelefon: {PH('089 99998123')}",
            {"kind": "form"},
        ),
        (
            "de-invoice-0007",
            f"RECHNUNG Nr. 2026-0815\n{ORG('Kitalit Software AG')}\n"
            f"Kunde: {P('Ole Exemplar')}, {A('Gartenweg 5, 20095 Hamburg')}\n"
            "Betrag: 12500 Euro, fällig am 01.12.2026.\n"
            f"Bitte geben Sie bei der Zahlung Ihre Steuernummer {IDD(st_3)} an.",
            {"kind": "invoice"},
        ),
        (
            "de-insurance-0008",
            f"Versicherte Person: {P('Greta Fiktiva')}, geb. {DOB('28.01.1972')}\n"
            f"Versicherungsnummer {IDD(sv_3)}\n"
            f"Rückruf erbeten an {E('g.fiktiva@example.org')} oder {PH('+49 40 66969123')}.",
            {"kind": "form"},
        ),
        (
            "de-negative-0009",
            "Protokoll der Sitzung vom 01.02.2026\n"
            "Die Studie mit 20000 Teilnehmern lief über 18 Monate. Bestellnummer 4711-0815, "
            f"Vorgang {bad_steuer_id('4710382946')}, Aktenzeichen 12 150885 M 01 0. "
            "Nach Paragraph 3 Absatz 2 wurden 12500 Euro überwiesen.",
            {"kind": "minutes", "tags": ["hard-negative"]},
        ),
        (
            "de-negative-0010",
            "Der Mieter und die Vermieterin vereinbaren eine Staffelmiete. Die Miete steigt "
            "zum 01.01.2027 um 2,5 Prozent. Die Wohnung hat 3 Zimmer auf 78 Quadratmetern.",
            {"kind": "contract", "tags": ["hard-negative"]},
        ),
    ]
    return [from_markup(doc_id, text, language="de", meta=meta) for doc_id, text, meta in docs]


# --- Polish --------------------------------------------------------------------------


def pesel(payload10: str) -> str:
    """A valid PESEL from a made-up ``YYMMDDZZZX`` (the month carries the century)."""
    value = payload10 + str(pesel_check_digit(payload10))
    if not is_valid_pesel(value):
        raise ValueError("payload has no possible date of birth; pick another")
    return value


def bad_pesel(payload10: str) -> str:
    """Looks like a PESEL, fails the check digit."""
    good = pesel(payload10)
    return good[:10] + str((int(good[10]) + 1) % 10)


def nip(payload9: str, layout: str = "3-3-2-2") -> str:
    """A valid NIP, grouped ``3-3-2-2`` (people), ``3-2-2-3`` (companies) or compact."""
    check = nip_check_digit(payload9)
    if check is None:
        raise ValueError("payload has no NIP check digit; pick another")
    digits = payload9 + str(check)
    if layout == "3-3-2-2":
        return f"{digits[:3]}-{digits[3:6]}-{digits[6:8]}-{digits[8:]}"
    if layout == "3-2-2-3":
        return f"{digits[:3]}-{digits[3:5]}-{digits[5:7]}-{digits[7:]}"
    return digits


def regon(payload8: str) -> str:
    """A valid 9-digit REGON."""
    return payload8 + str(regon_check_digit(payload8))


def id_card(letters: str, digits5: str, sep: str = "") -> str:
    """A valid dowód osobisty number ``AAA`` + check digit + five digits."""
    return f"{letters}{sep}{id_card_check_digit(letters, digits5)}{digits5}"


def passport_pl(letters: str, digits6: str, sep: str = "") -> str:
    """A valid Polish passport number ``AA`` + check digit + six digits."""
    return f"{letters}{sep}{passport_check_digit(letters, digits6)}{digits6}"


def pl_documents() -> list[Document]:
    iban_pl_1 = iban("PL", "123400000000001234567890")
    iban_pl_2 = iban("PL", "432100000000009876543210", grouped=False)
    pesel_1, pesel_2, pesel_3 = pesel("8503140123"), pesel("9211250456"), pesel("0227080362")
    nip_1, nip_2 = nip("777000124"), nip("526000111", layout="3-2-2-3")
    nip_3 = nip("951000345", layout="compact")
    regon_1 = regon("99000123")
    dowod_1, dowod_2 = id_card("ZZB", "00123", sep=" "), id_card("ZXA", "45678")
    paszport_1 = passport_pl("ZS", "000321")
    docs: list[tuple[str, str, dict[str, object]]] = [
        (
            "pl-email-0001",
            f"Temat: Kaucja\n\nDzień dobry Pani {P('Anna Przykładowa')},\n\nkaucję przelejemy "
            f"na rachunek {BANK(iban_pl_1)}. W razie pytań proszę dzwonić pod "
            f"{PH('+48 555 010 203')} albo pisać na {E('anna.przykladowa@example.com')}.\n\n"
            f"Z poważaniem\n{P('Jan Testowy')}",
            {"kind": "email"},
        ),
        (
            "pl-contract-0002",
            "UMOWA O PRACĘ\n\n"
            f"zawarta pomiędzy {ORG('Fikcyjna Spółka z o.o.')} a {P('Piotrem Zmyślonym')}, "
            f"urodzonym {DOB('14.03.1985')}, zamieszkałym przy "
            f"{A('ul. Wymyślona 12/5, 00-950 Warszawa')}, PESEL {IDD(pesel_1)}, legitymującym "
            f"się dowodem osobistym seria i numer {IDD(dowod_1)}.\n"
            f"Wynagrodzenie będzie wypłacane na konto {BANK(iban_pl_2)}.",
            {"kind": "contract"},
        ),
        (
            "pl-invoice-0003",
            "FAKTURA VAT nr FV/2026/10/0815\n"
            f"Sprzedawca: {P('Tomasz Próbny')} Usługi Remontowe, NIP: {IDD(nip_1)}, "
            f"REGON: {IDD(regon_1)}\n"
            f"Nabywca: {ORG('Wzorcowa Sp. z o.o.')}, NIP {IDD(nip_2)}, "
            f"{A('al. Testowa 100, 31-008 Kraków')}\n"
            "Do zapłaty: 12 500,00 zł, termin płatności 01.12.2026.",
            {"kind": "invoice"},
        ),
        (
            "pl-letter-0004",
            f"{P('Katarzyna Wzorcowa')}\n{A('os. Kwiatowe 3 m. 14\n61-001 Poznań')}\n\n"
            f"Szanowna Pani,\n\ninformujemy, że paszport nr {IDD(paszport_1)} jest gotowy do "
            f"odbioru. Prosimy o kontakt pod numerem {PH('(61) 555 12 34')}.\n\n"
            f"Z wyrazami szacunku\n{ORG('Urząd Fikcyjny w Poznaniu')}",
            {"kind": "letter"},
        ),
        (
            "pl-chat-0005",
            f"hej, tu {P('Ola Fikcyjna')}! mój nowy numer to {PH('555 123 456')}, "
            f"możesz też pisać na {E('ola.fikcyjna@example.net')}",
            {"kind": "chat", "tags": ["informal"]},
        ),
        (
            "pl-inflection-0006",
            f"{P('Marek Nowak')} się przeprowadza. Klucze oddaliśmy {P('Nowak')}owi, a umowę "
            f"podpisaliśmy z {P('Nowak')}iem w poniedziałek. Paczka dla "
            f"{P('Jana Kowalskiego')} czeka u {P('Kowalski')}ch na "
            f"{A('ul. 3 Maja 7, 40-001 Katowice')}.",
            {"kind": "note", "tags": ["inflected"]},
        ),
        (
            "pl-form-0007",
            "Wniosek o zwrot kosztów\n"
            f"Imię i nazwisko: {P('Ewa Zmyślona')}\nData urodzenia: {DOB('02.07.1992')}\n"
            f"PESEL: {IDD(pesel_2)}\nAdres: {A('ul. Jana Pawła II 15, 80-001 Gdańsk')}\n"
            f"Nr prawa jazdy: {IDD('00123/16/1234')}\nTelefon: {PH('58 555 01 23')}",
            {"kind": "form"},
        ),
        (
            "pl-bank-0008",
            f"Wyciąg z rachunku\nPosiadacz: {P('Adam Testowy')}, NIP {IDD(nip_3)}\n"
            f"Karta płatnicza nr {BANK('4111 1111 1111 1111')}, dowód osobisty "
            f"{IDD(dowod_2)}.\nSaldo końcowe: 3 456,78 zł.",
            {"kind": "statement"},
        ),
        (
            "pl-registry-0009",
            f"Dane dziecka: {P('Zofia Próbna')}, ur. {DOB('08.07.2002')}, numer PESEL "
            f"{IDD(pesel_3)}. Opiekun prawny: {P('Paweł Próbny')}, "
            f"e-mail {E('pawel.probny@example.org')}.",
            {"kind": "form"},
        ),
        (
            "pl-negative-0010",
            "Protokół z zebrania z dnia 01.02.2026\n"
            "W badaniu wzięło udział 20000 osób przez 18 miesięcy. Numer zamówienia "
            f"{bad_pesel('8503140123')}, sygn. akt I C 123/26, kod produktu ZZB100123. "
            "Uchwałą nr 12/2026 przyznano 500 000 000 zł na lata 2026-2030.",
            {"kind": "minutes", "tags": ["hard-negative"]},
        ),
        (
            "pl-negative-0011",
            "Najemca i Wynajmujący ustalają czynsz w wysokości 2 400 zł miesięcznie. Od "
            "01.01.2027 czynsz wzrośnie o 2,5 procent. Mieszkanie ma 3 pokoje i 54 metry "
            "kwadratowe na 4 piętrze.",
            {"kind": "contract", "tags": ["hard-negative"]},
        ),
    ]
    return [from_markup(doc_id, text, language="pl", meta=meta) for doc_id, text, meta in docs]


def hu_inflection_documents() -> list[Document]:
    """Hungarian names whose stem changes before a suffix, each in several cases.

    A final ``a``/``e`` lengthens (``Zsuzsanna`` -> ``Zsuzsannának``), a final digraph doubles
    (``Szabolcs`` -> ``Szabolccsal``), a single final consonant doubles into ``-val``
    (``Elek`` -> ``Elekkel``). Since LAB-1342 also stacked suffixes: the family suffix ``-ék``,
    the possessive ``-é`` and ``-éi``, with a case ending after them (``Ottóéknál``,
    ``Hajnáéknak``, ``Hubáéit``). Measures that every form is masked by one placeholder
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
        # Stacked suffixes (LAB-1342): the family suffix -ék, the possessive -é and the plural
        # possessive -éi, each with or without a case ending after it. An unchanged stem keeps
        # the chain outside the span; a lengthened stem is labelled as the whole word.
        (
            "hu-inflection-0009",
            f"{P('Kerekes Ottó')} tegnap írt. Szombaton {P('Kerekes Ottó')}éknál vacsorázunk, "
            f"a csomagot {P('Kerekes Ottó')}éknak visszük, és {P('Teszt Elek')}ékhez is "
            f"beugrunk. {P('Teszt Elek')} címe: {A('1095 Budapest, Képzelt utca 12.')}",
            {"kind": "chat", "tags": ["stacked-suffix", "family-suffix", "back-harmony"]},
        ),
        (
            "hu-inflection-0010",
            f"{P('Teszt Hajna')} jelezte, hogy költözik. {P('Teszt Hajnáéknál')} marad a kulcs, "
            f"{P('Teszt Hajnáéktól')} kérjük vissza, és {P('Teszt Hajnáékat')} értesítjük. "
            f"A kék autó {P('Teszt Hajnáé')}, rendszáma {PLATE('TSZ-417')}.",
            {"kind": "note", "tags": ["stacked-suffix", "family-suffix", "vowel-lengthening"]},
        ),
        (
            "hu-inflection-0011",
            f"{P('Gyakorló Tihamér')} és {P('Próba Bence')} közös irodát bérel. "
            f"{P('Gyakorló Tihamér')}éknek és {P('Próba Bencééknek')} is elküldtük a számlát. "
            f"A szerződés {P('Gyakorló Tihamér')}éké, a bérleti díjat {P('Próba Bencéék')} "
            f"fizetik. E-mail: {E('bence.proba@example.org')}",
            {
                "kind": "email",
                "tags": ["stacked-suffix", "family-suffix", "front-harmony", "vowel-lengthening"],
            },
        ),
        (
            "hu-inflection-0012",
            f"{P('Minta Huba')} levelet küldött. A régi iroda {P('Minta Hubáé')} volt, a miénk "
            f"{P('Minta Hubáéval')} szemben van. {P('Minta Hubáéit')} holnap visszük el, "
            f"{P('Minta Hubáéinak')} a raktárban a helye. Telefon: {PH('+36 20 555 0177')}.",
            {"kind": "letter", "tags": ["stacked-suffix", "possessive", "vowel-lengthening"]},
        ),
    ]
    return [from_markup(doc_id, text, language="hu", meta=meta) for doc_id, text, meta in docs]


OUTPUTS = {
    "hu-smoke.jsonl": hu_documents,
    "en-smoke.jsonl": en_documents,
    "hu-inflection.jsonl": hu_inflection_documents,
    "de-smoke.jsonl": de_documents,
    "pl-smoke.jsonl": pl_documents,
}


def main() -> None:
    for name, build in OUTPUTS.items():
        write_fixtures(HERE / name, build())
        print(f"wrote {HERE / name}")


if __name__ == "__main__":
    main()
