"""Build the phase-1 multilingual gate sets (LAB-1525): ``eval/fixtures/eu/``.

Per language: ``<lang>-smoke.jsonl`` (short documents with every common type, plus one
document with numbers but no personal data, for over-masking) and ``<lang>-inflection.jsonl``
(names in the forms the language actually writes them in: case endings in lv, lt, hr, sl and
ro, elision and standalone surnames in fr, es, it, nl and mt, initial mutations in ga). Plus
``en-court-smoke.jsonl``: English court-style text with standalone surnames, the weak spot the
MAPA baseline (LAB-1516) found. These are hand-written gates for the NER candidates of the
phase-1 training; they exist before any training on the new data.

Every person, address, number and organisation below is **fictional** (ADR 0005). People are
invented given name + surname pairs (not drawn from the training generator's lists, so a gate
doesn't reward memorised names); e-mail domains are the reserved ``example.*``; IBANs, and IDs
with a check digit, are computed from made-up payloads, so they are valid in form but issued
to nobody. Nothing here is copied or adapted from court text (MAPA and TAB never leave the
machine, policy LAB-1419).

Labels are inline ``{{TYPE|value}}`` markup (:func:`pii_guard.eval.from_markup`). A declined
or mutated name is labelled as a whole word (``{{PERSON|Valtera Krasta}}``, ``{{PERSON|Sheáin Uí
Bhriain}}``), as ``hu-inflection.jsonl`` does for Hungarian stem-changing forms; a detachable
ending that leaves the name intact stays outside (Dutch ``{{PERSON|Pieter}}s``). Honorifics
(``M.``, ``Sr.``, ``domnul``, ``Mr``) stay outside the span, as in the OpenPII eval policy;
elided prepositions (``d'``, ``l'``) too.

Regenerate after editing::

    uv run --no-sync python eval/fixtures/build_eu_gates.py
"""

# ruff: noqa: RUF001

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from pii_guard.detect.checksums import iban_check_digits
from pii_guard.eval import Document, from_markup, write_fixtures

HERE = Path(__file__).resolve().parent / "eu"


def P(v: str) -> str:
    return f"{{{{PERSON|{v}}}}}"


def O(v: str) -> str:  # noqa: E743
    return f"{{{{ORGANIZATION|{v}}}}}"


def A(v: str) -> str:
    return f"{{{{ADDRESS|{v}}}}}"


def E(v: str) -> str:
    return f"{{{{EMAIL|{v}}}}}"


def PH(v: str) -> str:
    return f"{{{{PHONE|{v}}}}}"


def B(v: str) -> str:
    return f"{{{{BANK_ACCOUNT|{v}}}}}"


def ID(v: str) -> str:
    return f"{{{{ID_DOCUMENT|{v}}}}}"


def DOB(v: str) -> str:
    return f"{{{{DATE_OF_BIRTH|{v}}}}}"


def iban(country: str, bban: str, grouped: bool = True) -> str:
    compact = country + iban_check_digits(country, bban) + bban
    return " ".join(compact[i : i + 4] for i in range(0, len(compact), 4)) if grouped else compact


# --- Fictional national identifiers -----------------------------------------------------------


def lt_code(body10: str) -> str:
    digits = [int(c) for c in body10]
    for weights in ((1, 2, 3, 4, 5, 6, 7, 8, 9, 1), (3, 4, 5, 6, 7, 8, 9, 1, 2, 3)):
        check = sum(d * w for d, w in zip(digits, weights, strict=True)) % 11
        if check != 10:
            return body10 + str(check)
    return body10 + "0"


def hr_oib(body10: str) -> str:
    acc = 10
    for c in body10:
        acc = (acc + int(c)) % 10 or 10
        acc = (acc * 2) % 11
    return body10 + str((11 - acc) % 10)


def si_emso(body12: str) -> str:
    weights = (7, 6, 5, 4, 3, 2, 7, 6, 5, 4, 3, 2)
    rest = sum(int(c) * w for c, w in zip(body12, weights, strict=True)) % 11
    return body12 + str(0 if rest == 0 else (11 - rest) % 10)


def es_dni(number8: str) -> str:
    return number8 + "TRWAGMYFPDXBNJZSQVHLCKE"[int(number8) % 23]


def nl_bsn(body8: str) -> str:
    total = sum(int(c) * w for c, w in zip(body8, range(9, 1, -1), strict=True))
    check = total % 11
    if check == 10:
        raise ValueError("pick another payload")
    return body8 + str(check)


def ro_cnp(body12: str) -> str:
    weights = "279146358279"
    rest = sum(int(c) * int(w) for c, w in zip(body12, weights, strict=True)) % 11
    return body12 + ("1" if rest == 10 else str(rest))


def ie_pps(digits7: str) -> str:
    total = sum(int(c) * w for c, w in zip(digits7, range(8, 1, -1), strict=True))
    return digits7 + "WABCDEFGHIJKLMNOPQRSTUV"[total % 23]


def doc(lang: str, kind: str, n: int, text: str, tags: tuple[str, ...] = ()) -> Document:
    meta: dict[str, object] = {"kind": kind}
    if tags:
        meta["tags"] = list(tags)
    return from_markup(f"{lang}-{kind}-{n:04d}", text, language=lang, meta=meta)


# --- Latvian ----------------------------------------------------------------------------------


LV_COMPANY = 'SIA "Mežābeles"'


def lv_smoke() -> list[Document]:
    return [
        doc("lv", "email", 1,
            f"Temats: Dzīvokļa īre\n\nLabdien, {P('Kristiāna Zeltiņa')}!\n\nLūdzu, pārskaitiet "
            f"īres maksu uz kontu {B(iban('LV', 'TEST0001234567890'))} līdz mēneša beigām. "
            f"Jautājumu gadījumā zvaniet {PH('+371 2955 0143')} vai rakstiet uz "
            f"{E('aivis.lapsa@example.com')}.\n\nAr cieņu\n{P('Aivis Lapsa')}"),
        doc("lv", "contract", 2,
            f"PIRKUMA LĪGUMS\n\nPārdevējs: {P('Ģirts Kauliņš')}, personas kods "
            f"{ID('150378-11542')}, dzimis {DOB('15.03.1978.')}, dzīvo "
            f"{A('Ziedu iela 7-3, Valmiera, LV-4201')}.\nPircējs: {O(LV_COMPANY)}, "
            f"juridiskā adrese {A('Dzelzceļa iela 18, Jelgava, LV-3001')}."),
        doc("lv", "court", 3,
            f"{O('Zemgales rajona tiesa')} izskatīja lietu pēc {P('Raimonda Puriņa')} prasības "
            f"pret {P('Viktoriju Akmeni')} par aizdevuma atmaksu. {P('Akmene')} prasību "
            f"neatzina.", ("declined",)),
        doc("lv", "chat", 4,
            f"Klients: Sveiki, esmu {P('Elza Krastiņa')}, mans e-pasts ir "
            f"{E('elza.krastina@example.org')}.\nOperators: Paldies, {P('Elza')}! Kāds ir jūsu "
            f"tālruņa numurs?\nKlients: {PH('2641 0778')}."),
        doc("lv", "negative", 5,
            "Rēķins Nr. 2026-004517, summa 1 245,00 EUR, apmaksas termiņš 14 dienas. Pasūtījuma "
            "numurs: 88310442. Sūtījums tiks piegādāts 3–5 darba dienu laikā; preces kods "
            "LV-55-0912."),
    ]  # fmt: skip


def lv_inflection() -> list[Document]:
    return [
        doc("lv", "inflection", 1,
            f"Vakar runāju ar {P('Valteru Krastu')}. {P('Valtera Krasta')} piedāvājums mums "
            f"patika, "
            f"tāpēc nosūtījām {P('Valteram Krastam')} līgumu.", ("acc", "gen", "dat")),
        doc("lv", "inflection", 2,
            f"Dokumentus parakstīja {P('Inga Rudzīte')}. {P('Ingai Rudzītei')} tika nosūtīta "
            f"kopija, bet {P('Ingas Rudzītes')} vietniece vēl gaida atbildi.", ("dat", "gen")),
        doc("lv", "inflection", 3,
            f"Tiesa uzklausīja {P('Kārli Vilku')}. {P('Vilks')} apgalvoja, ka naudu atdevis, "
            f"taču {P('Vilka')} liecība nesakrita ar dokumentiem.", ("standalone-surname",)),
        doc("lv", "inflection", 4,
            f"Sveiks, {P('Mārtiņ')}! Vai {P('Mārtiņam Liepam')} jau pastāstīji par "
            f"sapulci?", ("vocative", "dat")),
        doc("lv", "inflection", 5,
            f"Paldies {P('Annai Smilgai')} un {P('Robertam Dzērvītim')} par palīdzību. "
            f"Tālrunis: {PH('+371 6712 0456')}.", ("dat",)),
    ]  # fmt: skip


# --- Lithuanian -------------------------------------------------------------------------------


def lt_smoke() -> list[Document]:
    return [
        doc("lt", "email", 1,
            f"Tema: Buto nuoma\n\nLaba diena, {P('Gintare')},\n\nnuomos mokestį prašome pervesti "
            f"į sąskaitą {B(iban('LT', '7300010123456789'))}. Kilus klausimams, skambinkite "
            f"{PH('+370 612 34098')} arba rašykite {E('tadas.jurkus@example.com')}.\n\n"
            f"Pagarbiai\n{P('Tadas Jurkus')}", ("vocative",)),
        doc("lt", "contract", 2,
            f"PIRKIMO–PARDAVIMO SUTARTIS\n\nPardavėjas {P('Arūnas Steponavičius')}, asmens kodas "
            f"{ID(lt_code('3820314123'))}, gimęs {DOB('1982-03-14')}, gyvenantis "
            f"{A('Klevų g. 9-4, LT-44280 Kaunas')}, ir pirkėja {O('UAB „Šilagėlė“')}, "
            f"buveinės adresas {A('Stoties g. 21, LT-91100 Klaipėda')}."),
        doc("lt", "court", 3,
            f"{O('Kauno apylinkės teismas')} išnagrinėjo {P('Ramunės Vaitkevičienės')} ieškinį "
            f"atsakovui {P('Mariui Gudaičiui')}. {P('Gudaitis')} ieškinio nepripažino.",
            ("declined",)),
        doc("lt", "chat", 4,
            f"Klientas: Sveiki, aš {P('Vilius Sabaliauskas')}, el. paštas "
            f"{E('vilius.s@example.net')}.\nOperatorė: Ačiū, {P('Viliau')}! Koks jūsų telefono "
            f"numeris?\nKlientas: {PH('8612 77041')}.", ("vocative",)),
        doc("lt", "negative", 5,
            "Sąskaita faktūra Nr. SF-2026-08812, suma 3 410,50 EUR, apmokėti per 10 dienų. "
            "Užsakymo numeris 55120934, siuntos sekimo numeris LT9938201744."),
    ]  # fmt: skip


def lt_inflection() -> list[Document]:
    return [
        doc("lt", "inflection", 1,
            f"Vakar kalbėjau su {P('Jurgiu Stasiūnu')}. {P('Jurgio Stasiūno')} pasiūlymas mums "
            f"patiko, todėl išsiuntėme {P('Jurgiui Stasiūnui')} sutartį.", ("ins", "gen", "dat")),
        doc("lt", "inflection", 2,
            f"Dokumentą pasirašė {P('Lina Bielskienė')}. {P('Linai Bielskienei')} "
            f"išsiuntėme kopiją, o {P('Linos Bielskienės')} pavaduotoja dar laukia atsakymo.",
            ("dat", "gen")),
        doc("lt", "inflection", 3,
            f"Teismas apklausė {P('Kęstutį Raudonaitį')}. {P('Raudonaitis')} teigė, kad pinigus "
            f"grąžino, tačiau {P('Raudonaičio')} parodymai neatitiko dokumentų.",
            ("standalone-surname", "stem-change")),
        doc("lt", "inflection", 4,
            f"Labas, {P('Giedriau')}! Ar jau pasakei {P('Austėjai Vilkaitei')} apie "
            f"susitikimą?", ("vocative", "dat")),
        doc("lt", "inflection", 5,
            f"Ačiū {P('Rūtai Gudienei')} ir {P('Tomui Sinkevičiui')} už pagalbą. Telefonas: "
            f"{PH('+370 5 210 4477')}.", ("dat",)),
    ]  # fmt: skip


# --- Croatian ---------------------------------------------------------------------------------


def hr_smoke() -> list[Document]:
    return [
        doc("hr", "email", 1,
            f"Predmet: Najam stana\n\nPoštovana gospođo {P('Perković')},\n\nmolimo da "
            f"najamninu uplatite na račun {B(iban('HR', '23600001234567890'))}. Za pitanja "
            f"nazovite {PH('091 555 0187')} ili pišite na {E('zvonimir.sertic@example.com')}.\n\n"
            f"S poštovanjem,\n{P('Zvonimir Sertić')}"),
        doc("hr", "contract", 2,
            f"UGOVOR O KUPOPRODAJI\n\nProdavatelj: {P('Damir Šimunović')}, OIB "
            f"{ID(hr_oib('7410236589'))}, rođen {DOB('22. 7. 1979.')}, "
            f"{A('Vinogradska ulica 12, 31000 Osijek')}.\nKupac: "
            f"{O('Jadranska Lavanda d.o.o.')}, {A('Obala 3, 21000 Split')}."),
        doc("hr", "court", 3,
            f"{O('Općinski sud u Splitu')} odlučio je o tužbi {P('Mladena Rukavine')} protiv "
            f"{P('Ivane Kolar')}. {P('Rukavina')} traži povrat zajma.", ("declined",)),
        doc("hr", "chat", 4,
            f"Korisnica: Dobar dan, ja sam {P('Mirjana Galić')}, rođena {DOB('04.09.1983.')}, "
            f"e-mail {E('mirjana.galic@example.org')}.\nAgent: Hvala, gospođo {P('Galić')}. "
            f"Na koji broj vas možemo zvati?\nKorisnica: {PH('+385 98 441 2290')}."),
        doc("hr", "negative", 5,
            "Račun br. 2026-11-04417, iznos 1.870,00 EUR, rok plaćanja 15 dana. Broj narudžbe "
            "73310045, šifra artikla HR-2291-7."),
    ]  # fmt: skip


def hr_inflection() -> list[Document]:
    return [
        doc("hr", "inflection", 1,
            f"Jučer sam razgovarao s {P('Antunom Despotom')}. Prijedlog {P('Antuna Despota')} nam "
            f"se svidio pa smo {P('Antunu Despotu')} poslali ugovor.", ("ins", "gen", "dat")),
        doc("hr", "inflection", 2,
            f"Dokument je potpisala {P('Snježana Bilić')}. {P('Snježani Bilić')} poslali smo "
            f"presliku, a zamjenica {P('Snježane Bilić')} još čeka odgovor.", ("dat", "gen")),
        doc("hr", "inflection", 3,
            f"Sud je saslušao {P('Tomislava Mesića')}. {P('Mesić')} je tvrdio da je novac "
            f"vratio, ali iskaz {P('Mesića')} nije u skladu s dokumentima.",
            ("standalone-surname",)),
        doc("hr", "inflection", 4,
            f"Bok {P('Marko')}! Jesi li javio {P('Petri Žužul')} za sastanak?", ("dat",)),
        doc("hr", "inflection", 5,
            f"Zahvaljujemo {P('Ani Rajković')} i {P('Petru Matošiću')} na pomoći. Telefon: "
            f"{PH('01 4870 225')}.", ("dat", "fleeting-a")),
    ]  # fmt: skip


# --- Slovenian --------------------------------------------------------------------------------


def sl_smoke() -> list[Document]:
    return [
        doc("sl", "email", 1,
            f"Zadeva: Najem stanovanja\n\nSpoštovana gospa {P('Vesna Pirc')},\n\nnajemnino "
            f"prosimo nakažite na račun {B(iban('SI', '029000012345678'))}. Za vprašanja "
            f"pokličite {PH('041 555 218')} ali pišite na {E('rok.sustar@example.com')}.\n\n"
            f"Lep pozdrav,\n{P('Rok Šuštar')}"),
        doc("sl", "contract", 2,
            f"KUPOPRODAJNA POGODBA\n\nProdajalec: {P('Aljoša Gorenc')}, EMŠO "
            f"{ID(si_emso('120397650012'))}, rojen {DOB('12. 3. 1997')}, "
            f"{A('Vrtna ulica 5, 3000 Celje')}.\nKupec: {O('Smrekov Log d.o.o.')}, "
            f"{A('Industrijska cesta 14, 4000 Kranj')}."),
        doc("sl", "court", 3,
            f"{O('Okrajno sodišče v Mariboru')} je odločalo o tožbi {P('Damjana Lesjaka')} "
            f"zoper {P('Andrejo Kokalj')}. {P('Lesjak')} zahteva vračilo posojila.",
            ("declined",)),
        doc("sl", "chat", 4,
            f"Stranka: Dober dan, sem {P('Nuša Pavlič')}, e-pošta {E('nusa.pavlic@example.net')}."
            f"\nOperater: Hvala, gospa {P('Pavlič')}. Na katero številko vas lahko pokličemo?\n"
            f"Stranka: {PH('+386 31 270 914')}."),
        doc("sl", "negative", 5,
            "Račun št. 2026-0088713, znesek 2.115,40 EUR, rok plačila 8 dni. Številka naročila "
            "61009382, sklic SI00 2026-114."),
    ]  # fmt: skip


def sl_inflection() -> list[Document]:
    return [
        doc("sl", "inflection", 1,
            f"Včeraj sem govoril z {P('Lovrom Perkom')}. Predlog {P('Lovra Perka')} nam je "
            f"bil všeč, zato smo {P('Lovru Perku')} poslali pogodbo.", ("ins", "gen", "dat")),
        doc("sl", "inflection", 2,
            f"Dokument je podpisala {P('Mojca Bergant')}. {P('Mojci Bergant')} smo poslali kopijo, "
            f"namestnica {P('Mojce Bergant')} pa še čaka na odgovor.", ("dat", "gen")),
        doc("sl", "inflection", 3,
            f"Sodišče je zaslišalo {P('Boštjana Rupnika')}. {P('Rupnik')} je trdil, da je denar "
            f"vrnil, vendar izpoved {P('Rupnika')} ni skladna z dokumenti.",
            ("standalone-surname",)),
        doc("sl", "inflection", 4,
            f"Živjo, {P('Miha')}! Si že povedal {P('Tini Kuhar')} za sestanek?", ("dat",)),
        doc("sl", "inflection", 5,
            f"Zahvaljujemo se {P('Ani Jereb')} in {P('Petru Medvedu')} za pomoč. Telefon: "
            f"{PH('01 425 33 17')}.", ("dat", "fleeting-e")),
    ]  # fmt: skip


# --- French -----------------------------------------------------------------------------------


def fr_smoke() -> list[Document]:
    return [
        doc("fr", "email", 1,
            f"Objet : Loyer de novembre\n\nBonjour Mme {P('Roussel')},\n\nmerci de virer le loyer "
            f"sur le compte {B(iban('FR', '20041010050500013M02606'))}. Pour toute question, "
            f"appelez le {PH('06 39 98 12 34')} ou écrivez à {E('julien.brunet@example.fr')}.\n\n"
            f"Cordialement,\n{P('Julien Brunet')}"),
        doc("fr", "contract", 2,
            f"CONTRAT DE VENTE\n\nVendeur : {P('Gaëlle Faure')}, née le {DOB('3 février 1981')}, "
            f"passeport n° {ID('19FA45821')}, demeurant {A('12 rue des Lilas, 69003 Lyon')}.\n"
            f"Acheteur : {O('Ateliers Vernier SARL')}, "
            f"{A('8 avenue Jean Jaurès, 31000 Toulouse')}."),
        doc("fr", "court", 3,
            f"Le {O('tribunal judiciaire de Nantes')} a entendu {P('Antoine Mercier')}. "
            f"{P('Mercier')} soutient avoir remboursé la somme ; les déclarations de "
            f"{P('Mercier')} sont contredites par les relevés.", ("standalone-surname",)),
        doc("fr", "chat", 4,
            f"Client : Bonjour, je suis {P('Nadia Benali')}, mon e-mail est "
            f"{E('nadia.benali@example.org')}.\nConseiller : Merci, Madame {P('Benali')}. "
            f"Votre numéro ?\nClient : {PH('01 99 00 42 17')}."),
        doc("fr", "negative", 5,
            "Facture n° FA-2026-00871, montant 1 240,00 EUR, payable sous 30 jours. Numéro de "
            "commande 44012987, numéro de suivi 6A12345678901."),
    ]  # fmt: skip


def fr_inflection() -> list[Document]:
    return [
        doc("fr", "inflection", 1,
            f"C'est l'avis d'{P('Hélène Garnier')} ; selon {P('Garnier')}, le délai était trop "
            f"court.", ("elision", "standalone-surname")),
        doc("fr", "inflection", 2,
            f"Le contrat a été signé par M. {P('Lefèvre')} et Mme {P('Camille Roussel')}.",
            ("title",)),
        doc("fr", "inflection", 3,
            f"Bonjour {P('Hélène')}, peux-tu transmettre le dossier à {P('Bruno Masson')} ? "
            f"L'adresse d'{P('Masson')} a changé.", ("given-only", "elision")),
        doc("fr", "inflection", 4,
            f"Les témoins, {P('Paul Girard')} et {P('Inès Chevalier')}, ont confirmé la date. "
            f"Seule {P('Chevalier')} a vu le véhicule.", ("standalone-surname",)),
    ]  # fmt: skip


# --- Spanish ----------------------------------------------------------------------------------


def es_smoke() -> list[Document]:
    return [
        doc("es", "email", 1,
            f"Asunto: Alquiler de noviembre\n\nEstimada Sra. {P('Herrero')}:\n\nle rogamos que "
            f"ingrese el alquiler en la cuenta {B(iban('ES', '21000418450200051332'))}. Para "
            f"cualquier duda, llame al {PH('612 345 678')} o escriba a "
            f"{E('sergio.navarro@example.es')}.\n\nAtentamente,\n{P('Sergio Navarro')}"),
        doc("es", "contract", 2,
            f"CONTRATO DE COMPRAVENTA\n\nVendedor: {P('Javier Molina Ruiz')}, DNI "
            f"{ID(es_dni('48213907'))}, nacido el {DOB('14/05/1976')}, con domicilio en "
            f"{A('Calle del Olmo 14, 3.º B, 28012 Madrid')}.\nComprador: "
            f"{O('Talleres Albaida S.L.')}, {A('Avenida del Puerto 51, 46021 Valencia')}."),
        doc("es", "court", 3,
            f"El {O('Juzgado de Primera Instancia n.º 4 de Sevilla')} oyó a "
            f"{P('Pilar Domínguez Sanz')}. {P('Domínguez')} sostuvo que había devuelto el "
            f"dinero, pero la declaración de {P('Domínguez')} no coincide con los extractos.",
            ("standalone-surname",)),
        doc("es", "chat", 4,
            f"Cliente: Hola, soy {P('Lucía Herrero Campos')}, mi correo es "
            f"{E('lucia.herrero@example.org')}.\nAgente: Gracias, {P('Lucía')}. ¿Su teléfono?\n"
            f"Cliente: {PH('+34 699 120 334')}."),
        doc("es", "negative", 5,
            "Factura n.º 2026/004412, importe 980,50 EUR, a pagar en 15 días. Número de pedido "
            "70021834, número de seguimiento ES44102938."),
    ]  # fmt: skip


def es_inflection() -> list[Document]:
    return [
        doc("es", "inflection", 1,
            f"El contrato lo firmaron el Sr. {P('Ortega')} y la Sra. {P('Marina Ortega Gil')}.",
            ("title", "two-surnames")),
        doc("es", "inflection", 2,
            f"Hola {P('Marta')}, ¿puedes enviarle el informe a {P('Raúl Iglesias')}? Según "
            f"{P('Iglesias')}, falta la última página.", ("given-only", "standalone-surname")),
        doc("es", "inflection", 3,
            f"La demanda de {P('Andrés Prieto')} contra {P('Rocío Vidal')} fue desestimada; "
            f"{P('Vidal')} no tendrá que pagar las costas.", ("standalone-surname",)),
        doc("es", "inflection", 4,
            f"Del informe de {P('Óscar Fuentes')} se deduce que {P('Fuentes')} conocía el "
            f"defecto.", ("contraction",)),
    ]  # fmt: skip


# --- Italian ----------------------------------------------------------------------------------


def it_smoke() -> list[Document]:
    return [
        doc("it", "email", 1,
            f"Oggetto: Affitto di novembre\n\nGentile sig.ra {P('Moretti')},\n\nla preghiamo di "
            f"versare l'affitto sul conto {B(iban('IT', 'X0542811101000000123456'))}. Per "
            f"domande chiami il {PH('347 123 4567')} o scriva a {E('lorenzo.galli@example.it')}."
            f"\n\nCordiali saluti,\n{P('Lorenzo Galli')}"),
        doc("it", "contract", 2,
            f"CONTRATTO DI COMPRAVENDITA\n\nVenditore: {P('Matteo Colombo')}, nato il "
            f"{DOB('9 aprile 1974')}, carta d'identità {ID('CA48213JK')}, residente in "
            f"{A('Via dei Mille 27, 40121 Bologna')}.\nAcquirente: "
            f"{O('Officine Brenta S.r.l.')}, {A('Corso Venezia 8, 20121 Milano')}."),
        doc("it", "court", 3,
            f"Il {O('Tribunale di Torino')} ha sentito {P('Elena Barbieri')}. {P('Barbieri')} "
            f"sostiene di aver restituito la somma, ma la deposizione della {P('Barbieri')} "
            f"contrasta con gli estratti conto.", ("standalone-surname", "article")),
        doc("it", "chat", 4,
            f"Cliente: Buongiorno, sono {P('Chiara Fontana')}, la mia email è "
            f"{E('chiara.fontana@example.org')}.\nOperatore: Grazie, signora {P('Fontana')}. "
            f"Il suo numero?\nCliente: {PH('+39 333 210 9876')}."),
        doc("it", "negative", 5,
            "Fattura n. 2026/00731, importo 1.120,00 EUR, da pagare entro 30 giorni. Numero "
            "d'ordine 50039127, codice articolo IT-7741-B."),
    ]  # fmt: skip


def it_inflection() -> list[Document]:
    return [
        doc("it", "inflection", 1,
            f"Il contratto è stato firmato dal sig. {P('Ferrari')} e dalla dott.ssa "
            f"{P('Giulia Ricci')}.", ("title",)),
        doc("it", "inflection", 2,
            f"Ciao {P('Giulia')}, puoi girare il file a {P('Davide Marchetti')}? Secondo "
            f"{P('Marchetti')} manca l'allegato.", ("given-only", "standalone-surname")),
        doc("it", "inflection", 3,
            f"Secondo l'avv. {P('Rinaldi')}, la domanda di {P('Silvia Caruso')} è fondata; la "
            f"{P('Caruso')} ha prodotto le ricevute.", ("article",)),
        doc("it", "inflection", 4,
            f"La relazione dell'ing. {P('Pietro Gatti')} conferma che {P('Gatti')} aveva "
            f"segnalato il guasto.", ("elision", "title")),
    ]  # fmt: skip


# --- Dutch ------------------------------------------------------------------------------------


def nl_smoke() -> list[Document]:
    return [
        doc("nl", "email", 1,
            f"Onderwerp: Huur november\n\nBeste mevrouw {P('Van Dijk')},\n\nwilt u de huur "
            f"overmaken op rekening {B(iban('NL', 'ABNA0417164300'))}? Bij vragen kunt u bellen "
            f"met {PH('06-12345678')} of mailen naar {E('joost.mulder@example.nl')}.\n\n"
            f"Met vriendelijke groet,\n{P('Joost Mulder')}"),
        doc("nl", "contract", 2,
            f"KOOPOVEREENKOMST\n\nVerkoper: {P('Thijs Bakker')}, geboren op "
            f"{DOB('11-10-1985')}, BSN {ID(nl_bsn('11122233'))}, wonende "
            f"{A('Lindelaan 42, 3521 AB Utrecht')}.\nKoper: {O('Houtwerf Zeeland B.V.')}, "
            f"{A('Havenweg 3, 4381 LL Vlissingen')}."),
        doc("nl", "court", 3,
            f"De {O('rechtbank Gelderland')} hoorde {P('Femke de Wit')}. {P('De Wit')} stelt "
            f"dat zij het geld heeft terugbetaald, maar de verklaring van {P('De Wit')} strookt "
            f"niet met de afschriften.", ("standalone-surname", "particle")),
        doc("nl", "chat", 4,
            f"Klant: Hallo, ik ben {P('Sanne Verhoeven')}, mijn e-mail is "
            f"{E('sanne.verhoeven@example.org')}.\nMedewerker: Dank u, mevrouw "
            f"{P('Verhoeven')}. Uw telefoonnummer?\nKlant: {PH('+31 20 555 0193')}."),
        doc("nl", "negative", 5,
            "Factuurnummer 2026-00932, bedrag 1.450,00 EUR, te betalen binnen 14 dagen. "
            "Bestelnummer 88123094, track-and-tracecode 3SABC1234567."),
    ]  # fmt: skip


def nl_inflection() -> list[Document]:
    return [
        doc("nl", "inflection", 1,
            f"Het contract werd ondertekend door de heer {P('De Vries')} en mevrouw "
            f"{P('Sanne van Dijk')}.", ("title", "particle")),
        doc("nl", "inflection", 2,
            f"Hoi {P('Lotte')}, kun je het verslag naar {P('Ruben Smit')} sturen? Volgens "
            f"{P('Smit')} ontbreekt de bijlage.", ("given-only", "standalone-surname")),
        doc("nl", "inflection", 3,
            f"{P('Pieter')}s fiets staat bij {P('Fleur de Graaf')} in de schuur.",
            ("genitive-s",)),
        doc("nl", "inflection", 4,
            f"Het beroep van {P('Daan Hendriks')} werd verworpen; {P('Hendriks')} moet de "
            f"proceskosten betalen.", ("standalone-surname",)),
    ]  # fmt: skip


# --- Romanian ---------------------------------------------------------------------------------


def ro_smoke() -> list[Document]:
    return [
        doc("ro", "email", 1,
            f"Subiect: Chiria pe noiembrie\n\nStimată doamnă {P('Dumitrescu')},\n\nvă rugăm să "
            f"virați chiria în contul {B(iban('RO', 'BTRL01301202925690XX'))}. Pentru întrebări "
            f"sunați la {PH('0721 234 567')} sau scrieți la {E('radu.marin@example.ro')}.\n\n"
            f"Cu stimă,\n{P('Radu Marin')}"),
        doc("ro", "contract", 2,
            f"CONTRACT DE VÂNZARE-CUMPĂRARE\n\nVânzător: {P('Andrei Popescu')}, născut la "
            f"{DOB('17.08.1980')}, CNP {ID(ro_cnp('180081712345'))}, domiciliat în "
            f"{A('Strada Teilor nr. 15, ap. 7, 400123 Cluj-Napoca')}.\nCumpărător: "
            f"{O('Livada Verde SRL')}, {A('Bulevardul Unirii nr. 40, 030167 București')}."),
        doc("ro", "court", 3,
            f"{O('Judecătoria Iași')} l-a audiat pe {P('Mihai Stoica')}. {P('Stoica')} susține "
            f"că a restituit suma, însă declarația lui {P('Stoica')} nu se potrivește cu "
            f"extrasele.", ("standalone-surname",)),
        doc("ro", "chat", 4,
            f"Client: Bună ziua, sunt {P('Ioana Dumitrescu')}, e-mailul meu este "
            f"{E('ioana.dumitrescu@example.org')}.\nOperator: Mulțumesc, doamna "
            f"{P('Dumitrescu')}. Numărul de telefon?\nClient: {PH('+40 744 120 556')}."),
        doc("ro", "negative", 5,
            "Factura nr. 2026-00415, valoare 2.340,00 RON, scadentă în 15 zile. Numărul "
            "comenzii 61209384, număr AWB 1029384756."),
    ]  # fmt: skip


def ro_inflection() -> list[Document]:
    return [
        doc("ro", "inflection", 1,
            f"I-am trimis {P('Mariei Constantinescu')} contractul, iar {P('Mariei')} i-a "
            f"plăcut.", ("dat",)),
        doc("ro", "inflection", 2,
            f"Salut, {P('Radule')}! I-ai spus {P('Elenei Marinescu')} despre ședință?",
            ("vocative", "dat")),
        doc("ro", "inflection", 3,
            f"Cererea doamnei {P('Ionescu')} a fost respinsă, iar avocatul lui {P('Ionescu')} "
            f"a declarat apel.", ("title", "standalone-surname")),
        doc("ro", "inflection", 4,
            f"Semnătura {P('Cristinei Lungu')} lipsește de pe contract; {P('Lungu')} va semna "
            f"mâine.", ("gen",)),
    ]  # fmt: skip


# --- Maltese ----------------------------------------------------------------------------------


def mt_smoke() -> list[Document]:
    return [
        doc("mt", "email", 1,
            f"Suġġett: Il-kera ta' Novembru\n\nGħażiża Sinjura {P('Camilleri')},\n\njekk "
            f"jogħġbok ħallsi l-kera fil-kont {B(iban('MT', 'MALT011000012345MTLCAST001S'))}. "
            f"Għal mistoqsijiet, ċempel {PH('+356 7912 3456')} jew ikteb lil "
            f"{E('daniel.zammit@example.com')}.\n\nInsellimlek,\n{P('Daniel Zammit')}"),
        doc("mt", "contract", 2,
            f"KUNTRATT TA' BEJGĦ\n\nBejjiegħ: {P('Joseph Vella')}, imwieled fit-"
            f"{DOB('12/06/1977')}, karta tal-identità {ID('412377M')}, residenti f'"
            f"{A('12, Triq il-Ġnien, Ħaż-Żebbuġ ZBG 1234')}.\nXerrej: "
            f"{O('Ġebla Ħamra Ltd')}, {A('45, Triq il-Kbira, Birkirkara BKR 4011')}."),
        doc("mt", "court", 3,
            f"Il-{O('Qorti tal-Maġistrati')} semgħet lil {P('Rita Farrugia')}. {P('Farrugia')} "
            f"qalet li ħallset lura s-somma, iżda x-xhieda ta' {P('Farrugia')} ma taqbilx "
            f"mad-dokumenti.", ("standalone-surname",)),
        doc("mt", "chat", 4,
            f"Klijent: Bonġu, jiena {P('Mark Grech')}, l-email tiegħi hi "
            f"{E('mark.grech@example.org')}.\nAġent: Grazzi, Sur {P('Grech')}. In-numru tat-"
            f"telefon?\nKlijent: {PH('2122 4567')}."),
        doc("mt", "negative", 5,
            "Fattura numru 2026-00318, ammont 640,00 EUR, li għandu jitħallas fi żmien 30 jum. "
            "Numru tal-ordni 30219847, numru tat-traċċar MT88120394."),
    ]  # fmt: skip


def mt_inflection() -> list[Document]:
    return [
        doc("mt", "inflection", 1,
            f"Il-kuntratt ġie ffirmat mis-Sur {P('Borg')} u mis-Sinjura {P('Maria Cassar')}.",
            ("title",)),
        doc("mt", "inflection", 2,
            f"Għażiż {P('Kevin')}, tista' tibgħat ir-rapport lil {P('Rita Spiteri')}? Skont "
            f"{P('Spiteri')} jonqos l-anness.", ("given-only", "standalone-surname")),
        doc("mt", "inflection", 3,
            f"Skont {P('Paul Micallef')}, il-laqgħa ma' {P('Micallef')} u ma' {P('Galea')} "
            f"ġiet posposta.", ("elision",)),
        doc("mt", "inflection", 4,
            f"Il-karozza ta' {P('Anna Mifsud')} kienet ipparkjata quddiem id-dar ta' "
            f"{P('Mifsud')}.", ("standalone-surname",)),
    ]  # fmt: skip


# --- Irish ------------------------------------------------------------------------------------


def ga_smoke() -> list[Document]:
    return [
        doc("ga", "email", 1,
            f"Ábhar: Cíos mhí na Samhna\n\nA {P('Aoife')}, a chara,\n\níoc an cíos isteach sa "
            f"chuntas {B(iban('IE', 'AIBK93115212345678'))}, le do thoil. Má tá ceist agat, "
            f"glaoigh ar {PH('087 555 0123')} nó scríobh chuig "
            f"{E('ciaran.obriain@example.ie')}.\n\nLe meas,\n{P('Ciarán Ó Briain')}"),
        doc("ga", "contract", 2,
            f"CONRADH DÍOLACHÁIN\n\nDíoltóir: {P('Siobhán Nic Gearailt')}, rugadh "
            f"{DOB('14/02/1983')}, uimhir PPS {ID(ie_pps('8412377'))}, ag cónaí ag "
            f"{A('12 Bóthar na Trá, Gaillimh H91 X2Y3')}.\nCeannaitheoir: "
            f"{O('Cnoc Glas Teoranta')}, {A('5 Sráid an Mhuilinn, Corcaigh T12 K8P4')}."),
        doc("ga", "court", 3,
            f"Chuala an {O('Chúirt Dúiche')} fianaise ó {P('Phádraig Mac Cárthaigh')}. Dúirt "
            f"{P('Mac Cárthaigh')} go raibh an t-airgead íoctha aige.",
            ("lenition", "standalone-surname")),
        doc("ga", "chat", 4,
            f"Custaiméir: Dia duit, is mise {P('Niamh Ní Shé')}, is é mo r-phost "
            f"{E('niamh.nishe@example.org')}.\nGníomhaire: Go raibh maith agat, a "
            f"{P('Niamh')}. D'uimhir fóin?\nCustaiméir: {PH('+353 1 555 0198')}."),
        doc("ga", "negative", 5,
            "Sonrasc uimhir 2026-00517, suim 875,00 EUR, le híoc laistigh de 30 lá. Uimhir "
            "ordaithe 41029384, uimhir rianaithe IE55102938."),
    ]  # fmt: skip


def ga_inflection() -> list[Document]:
    return [
        doc("ga", "inflection", 1,
            f"Shínigh {P('Seán Ó Briain')} an conradh. Thug muid cóip do {P('Sheán Ó Briain')}, "
            f"agus tá teach {P('Sheáin Uí Bhriain')} díolta anois.", ("lenition", "genitive")),
        doc("ga", "inflection", 2,
            f"A {P('Sheáin')}, an bhfuil tú ag teacht? Tá {P('Máire Ní Bhriain')} ag fanacht.",
            ("vocative",)),
        doc("ga", "inflection", 3,
            f"Is í {P('Gráinne Ní Dhónaill')} an t-iarratasóir. Bhí {P('Ní Dhónaill')} i láthair "
            f"sa chúirt.", ("standalone-surname",)),
        doc("ga", "inflection", 4,
            f"A {P('Phádraig')}, labhair mé le {P('Tomás Mac Giolla')} inné.", ("lenition",)),
    ]  # fmt: skip


# --- English court style ----------------------------------------------------------------------


def en_court() -> list[Document]:
    return [
        doc("en", "court", 1,
            f"The claimant, {P('Nathaniel Brookes')}, lent the defendant, {P('Rosalind Ferris')}, "
            f"£12,000 in 2019. {P('Ferris')} accepts receipt of the money but says it was a gift. "
            f"I prefer the evidence of {P('Brookes')}.", ("standalone-surname",)),
        doc("en", "court", 2,
            f"In cross-examination Mr {P('Ogunleye')} accepted that he had signed the "
            f"variation. {P('Ogunleye')}'s explanation for the delay was, in my judgment, "
            f"unconvincing.", ("title", "possessive")),
        doc("en", "court", 3,
            f"{P('Meadows')} was a candid witness. I accept that {P('Meadows')} did not see the "
            f"letter until March, and that {P('Garland')} never told her about it.",
            ("common-word-surname",)),
        doc("en", "court", 4,
            f"The appellant, {P('Declan Stroud')}, appeals against the order in favour of "
            f"Dr {P('Imogen Vance')}. Counsel for {P('Stroud')} submitted that "
            f"{P('Vance')}'s report was not served in time.", ("standalone-surname",)),
        doc("en", "court", 5,
            f"It is common ground that {P('Cooper')} and {P('Short')} were partners in the "
            f"business until 2021.", ("common-word-surname",)),
        doc("en", "negative", 6,
            "The appeal is allowed. The order of 4 March 2024 is set aside and the claim is "
            "remitted for rehearing. Case No. CL-2023-000417; costs reserved to the trial "
            "judge. The claimant's skeleton argument ran to 24 pages."),
    ]  # fmt: skip


OUTPUTS: dict[str, Callable[[], list[Document]]] = {
    **{
        f"{lang}-smoke.jsonl": smoke
        for lang, smoke in (
            ("lv", lv_smoke),
            ("lt", lt_smoke),
            ("hr", hr_smoke),
            ("sl", sl_smoke),
            ("fr", fr_smoke),
            ("es", es_smoke),
            ("it", it_smoke),
            ("nl", nl_smoke),
            ("ro", ro_smoke),
            ("mt", mt_smoke),
            ("ga", ga_smoke),
        )
    },
    **{
        f"{lang}-inflection.jsonl": build
        for lang, build in (
            ("lv", lv_inflection),
            ("lt", lt_inflection),
            ("hr", hr_inflection),
            ("sl", sl_inflection),
            ("fr", fr_inflection),
            ("es", es_inflection),
            ("it", it_inflection),
            ("nl", nl_inflection),
            ("ro", ro_inflection),
            ("mt", mt_inflection),
            ("ga", ga_inflection),
        )
    },
    "en-court-smoke.jsonl": en_court,
}


def main() -> None:
    HERE.mkdir(exist_ok=True)
    for name, build in OUTPUTS.items():
        write_fixtures(HERE / name, build())
        print(f"wrote {HERE / name}")


if __name__ == "__main__":
    main()
