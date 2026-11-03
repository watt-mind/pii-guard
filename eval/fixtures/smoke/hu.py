"""Hungarian smoke fixtures: ``hu-smoke.jsonl`` and ``hu-inflection.jsonl`` (stem-changing
forms of names). Built by ``eval/fixtures/build_smoke.py``; fictional values only (ADR 0005)."""

from __future__ import annotations

from collections.abc import Callable

from build_smoke import (
    BANK,
    CO,
    DOB,
    HRSZ,
    IDD,
    ORG,
    PH,
    PLATE,
    TAJ,
    TAX,
    A,
    E,
    P,
    bad_company_tax_number,
    bad_taj,
    bad_tax_id,
    company_tax_number,
    giro,
    hu_iban,
    mrz_td1,
    personal_id,
    taj,
    tax_id,
)

from pii_guard.eval import Document, from_markup

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


OUTPUTS: dict[str, Callable[[], list[Document]]] = {
    "hu-smoke.jsonl": hu_documents,
    "hu-inflection.jsonl": hu_inflection_documents,
}
