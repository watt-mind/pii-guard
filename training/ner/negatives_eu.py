"""Hard negatives for the multilingual NER phase 1 (LAB-1525): numbers that are *not* personal data.

The same idea and number shapes as ``negatives.py`` (v2.0's hu / en / de set, left
unchanged): short, seeded, template-based documents full of order, invoice, tracking, case,
article and ticket numbers and amounts, with **no** gold spans. OpenPII rows mark nearly every
number as personal data, so a student trained on them alone over-masks business references.
The cue words are generic (the reference numbers any business text carries) and the numbers
are random; nothing here is personal data. One set per language the phase-1 mix adds: the
OpenPII-1M languages of ``openpii_eu.py`` plus Irish and Maltese (fictional Muse documents
only, no OpenPII rows)::

    uv run --no-sync python training/ner/negatives_eu.py --n 2000 --seed 1525 \\
        --out eval/generated/negatives-eu
"""

# Seeded synthetic data: the standard PRNG is the point.
# ruff: noqa: S311, RUF001, E501

from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
from collections.abc import Sequence
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from negatives import amount, number

from pii_guard.eval.fixtures import Document, write_fixtures

#: Per language: (currency, cue phrases, sentence templates). ``{cue}`` starts a sentence,
#: ``{cue2}`` is the same cue lower-cased for mid-sentence use.
LANGS: dict[str, tuple[str, tuple[str, ...], tuple[str, ...]]] = {
    "lv": (
        "EUR",
        (
            "Pasūtījuma numurs",
            "Rēķina numurs",
            "Preces kods",
            "Artikula numurs",
            "Sūtījuma izsekošanas numurs",
            "Lietas numurs",
            "Līguma numurs",
            "Pieteikuma numurs",
            "Rezervācijas kods",
            "Sērijas numurs",
            "Partijas numurs",
            "Atsauces numurs",
        ),
        (
            "{cue}: {num}. Lūdzu, norādiet to turpmākajā sarakstē.",
            "Jūsu {cue2} ir {num}, piegāde aizņems apmēram {days} darba dienas.",
            "{cue}: {num}, kopā {amount} EUR, apmaksas termiņš {days} dienas.",
            "Paldies par pasūtījumu! {cue}: {num}. {cue_b}: {num_b}.",
            "Vienības cena ir {amount} EUR, noliktavā ir {qty} gab. ({cue}: {num}).",
            "Gada budžets ir {amount} EUR, no tā iztērēti {amount_b} EUR.",
        ),
    ),
    "lt": (
        "EUR",
        (
            "Užsakymo numeris",
            "Sąskaitos faktūros numeris",
            "Prekės kodas",
            "Siuntos sekimo numeris",
            "Bylos numeris",
            "Sutarties numeris",
            "Paraiškos numeris",
            "Rezervacijos kodas",
            "Serijos numeris",
            "Partijos numeris",
            "Nuorodos numeris",
            "Užklausos numeris",
        ),
        (
            "{cue}: {num}. Prašome jį nurodyti tolesniame susirašinėjime.",
            "Jūsų {cue2} yra {num}, pristatymas užtruks apie {days} darbo dienas.",
            "{cue}: {num}, iš viso {amount} EUR, apmokėti per {days} dienas.",
            "Dėkojame už užsakymą! {cue}: {num}. {cue_b}: {num_b}.",
            "Vieneto kaina {amount} EUR, sandėlyje yra {qty} vnt. ({cue}: {num}).",
            "Metinis biudžetas yra {amount} EUR, iš jo išleista {amount_b} EUR.",
        ),
    ),
    "hr": (
        "EUR",
        (
            "Broj narudžbe",
            "Broj računa",
            "Šifra artikla",
            "Broj za praćenje pošiljke",
            "Broj predmeta",
            "Broj ugovora",
            "Broj zahtjeva",
            "Kod rezervacije",
            "Serijski broj",
            "Broj serije",
            "Poziv na broj",
            "Broj prijave kvara",
        ),
        (
            "{cue}: {num}. Molimo navedite ga u daljnjoj korespondenciji.",
            "{cue}: {num}. Dostava traje oko {days} radnih dana.",
            "{cue}: {num}, ukupno {amount} EUR, rok plaćanja {days} dana.",
            "Hvala na narudžbi! {cue}: {num}. {cue_b}: {num_b}.",
            "Jedinična cijena je {amount} EUR, na zalihi je {qty} kom. ({cue}: {num}).",
            "Godišnji proračun iznosi {amount} EUR, od čega je potrošeno {amount_b} EUR.",
        ),
    ),
    "sl": (
        "EUR",
        (
            "Številka naročila",
            "Številka računa",
            "Šifra artikla",
            "Številka za sledenje pošiljke",
            "Opravilna številka",
            "Številka pogodbe",
            "Številka zahtevka",
            "Koda rezervacije",
            "Serijska številka",
            "Številka serije",
            "Sklic",
            "Številka prijave napake",
        ),
        (
            "{cue}: {num}. Prosimo, navedite jo v nadaljnji korespondenci.",
            "{cue}: {num}. Dostava traja približno {days} delovnih dni.",
            "{cue}: {num}, skupaj {amount} EUR, rok plačila {days} dni.",
            "Hvala za naročilo! {cue}: {num}. {cue_b}: {num_b}.",
            "Cena na enoto je {amount} EUR, na zalogi je {qty} kosov ({cue}: {num}).",
            "Letni proračun znaša {amount} EUR, od tega je porabljenih {amount_b} EUR.",
        ),
    ),
    "fr": (
        "EUR",
        (
            "Numéro de commande",
            "Numéro de facture",
            "Référence article",
            "Numéro de suivi du colis",
            "Numéro de dossier",
            "Numéro de contrat",
            "Numéro de ticket",
            "Code de réservation",
            "Numéro de série",
            "Numéro de lot",
            "Référence",
            "Bon de livraison",
        ),
        (
            "{cue} : {num}. Merci de le rappeler dans toute correspondance.",
            "{cue} : {num}. La livraison prend environ {days} jours ouvrés.",
            "{cue} {num}, total {amount} EUR, payable sous {days} jours.",
            "Merci pour votre commande ! {cue} : {num}. {cue_b} : {num_b}.",
            "Le prix unitaire est de {amount} EUR et nous avons {qty} pièces en stock ({cue} {num}).",
            "Le budget annuel est de {amount} EUR, dont {amount_b} EUR déjà dépensés.",
        ),
    ),
    "es": (
        "EUR",
        (
            "Número de pedido",
            "Número de factura",
            "Referencia del artículo",
            "Número de seguimiento del envío",
            "Número de expediente",
            "Número de contrato",
            "Número de incidencia",
            "Código de reserva",
            "Número de serie",
            "Número de lote",
            "Referencia",
            "Albarán",
        ),
        (
            "{cue}: {num}. Indíquelo en cualquier comunicación posterior.",
            "Su {cue2} es {num}; la entrega tarda unos {days} días laborables.",
            "{cue} {num}, total {amount} EUR, a pagar en {days} días.",
            "¡Gracias por su pedido! {cue}: {num}. {cue_b}: {num_b}.",
            "El precio unitario es de {amount} EUR y hay {qty} unidades en stock ({cue} {num}).",
            "El presupuesto anual es de {amount} EUR, de los que se han gastado {amount_b} EUR.",
        ),
    ),
    "it": (
        "EUR",
        (
            "Numero d'ordine",
            "Numero di fattura",
            "Codice articolo",
            "Numero di tracciamento della spedizione",
            "Numero di pratica",
            "Numero di contratto",
            "Numero di ticket",
            "Codice di prenotazione",
            "Numero di serie",
            "Numero di lotto",
            "Riferimento",
            "Documento di trasporto",
        ),
        (
            "{cue}: {num}. Si prega di indicarlo in ogni comunicazione successiva.",
            "Il suo {cue2} è {num}; la consegna richiede circa {days} giorni lavorativi.",
            "{cue} {num}, totale {amount} EUR, da pagare entro {days} giorni.",
            "Grazie per l'ordine! {cue}: {num}. {cue_b}: {num_b}.",
            "Il prezzo unitario è di {amount} EUR e ci sono {qty} pezzi in magazzino ({cue} {num}).",
            "Il budget annuale è di {amount} EUR, di cui {amount_b} EUR già spesi.",
        ),
    ),
    "nl": (
        "EUR",
        (
            "Bestelnummer",
            "Factuurnummer",
            "Artikelnummer",
            "Track-and-tracecode",
            "Dossiernummer",
            "Contractnummer",
            "Ticketnummer",
            "Reserveringscode",
            "Serienummer",
            "Batchnummer",
            "Kenmerk",
            "Pakbonnummer",
        ),
        (
            "{cue}: {num}. Vermeld dit nummer bij verdere correspondentie.",
            "Uw {cue2} is {num}; de levering duurt ongeveer {days} werkdagen.",
            "{cue} {num}, totaal {amount} EUR, te betalen binnen {days} dagen.",
            "Bedankt voor uw bestelling! {cue}: {num}. {cue_b}: {num_b}.",
            "De stuksprijs is {amount} EUR en er zijn {qty} stuks op voorraad ({cue} {num}).",
            "Het jaarbudget is {amount} EUR, waarvan {amount_b} EUR is besteed.",
        ),
    ),
    "ro": (
        "RON",
        (
            "Numărul comenzii",
            "Numărul facturii",
            "Cod articol",
            "Număr de urmărire AWB",
            "Numărul dosarului",
            "Numărul contractului",
            "Numărul tichetului",
            "Cod de rezervare",
            "Număr de serie",
            "Numărul lotului",
            "Referință",
            "Aviz de însoțire",
        ),
        (
            "{cue}: {num}. Vă rugăm să îl menționați în corespondența ulterioară.",
            "{cue} este {num}; livrarea durează aproximativ {days} zile lucrătoare.",
            "{cue} {num}, total {amount} RON, de plătit în {days} zile.",
            "Vă mulțumim pentru comandă! {cue}: {num}. {cue_b}: {num_b}.",
            "Prețul unitar este de {amount} RON și avem {qty} bucăți în stoc ({cue} {num}).",
            "Bugetul anual este de {amount} RON, din care s-au cheltuit {amount_b} RON.",
        ),
    ),
    "bg": (
        "лв.",
        (
            "Номер на поръчка",
            "Номер на фактура",
            "Код на артикул",
            "Номер за проследяване на пратката",
            "Номер на дело",
            "Номер на договор",
            "Номер на заявка",
            "Код на резервация",
            "Сериен номер",
            "Номер на партида",
            "Референтен номер",
            "Номер на товарителница",
        ),
        (
            "{cue}: {num}. Моля, посочвайте го в по-нататъшната кореспонденция.",
            "{cue}: {num}; доставката отнема около {days} работни дни.",
            "{cue} {num}, общо {amount} лв., платими в срок от {days} дни.",
            "Благодарим за поръчката! {cue}: {num}. {cue_b}: {num_b}.",
            "Единичната цена е {amount} лв., на склад има {qty} бр. ({cue} {num}).",
            "Годишният бюджет е {amount} лв., от които са изразходвани {amount_b} лв.",
        ),
    ),
    "cs": (
        "Kč",
        (
            "Číslo objednávky",
            "Číslo faktury",
            "Kód zboží",
            "Sledovací číslo zásilky",
            "Spisová značka",
            "Číslo smlouvy",
            "Číslo požadavku",
            "Rezervační kód",
            "Sériové číslo",
            "Číslo šarže",
            "Variabilní symbol",
            "Číslo dodacího listu",
        ),
        (
            "{cue}: {num}. Uveďte jej prosím v další korespondenci.",
            "{cue}: {num}; doručení trvá přibližně {days} pracovních dní.",
            "{cue} {num}, celkem {amount} Kč, splatné do {days} dnů.",
            "Děkujeme za objednávku! {cue}: {num}. {cue_b}: {num_b}.",
            "Jednotková cena je {amount} Kč, skladem je {qty} ks ({cue} {num}).",
            "Roční rozpočet činí {amount} Kč, z toho je vyčerpáno {amount_b} Kč.",
        ),
    ),
    "da": (
        "kr.",
        (
            "Ordrenummer",
            "Fakturanummer",
            "Varenummer",
            "Forsendelsesnummer",
            "Sagsnummer",
            "Kontraktnummer",
            "Billetnummer",
            "Reservationskode",
            "Serienummer",
            "Batchnummer",
            "Reference",
            "Følgeseddelnummer",
        ),
        (
            "{cue}: {num}. Angiv det venligst ved al videre korrespondance.",
            "{cue}: {num}. Leveringen tager cirka {days} hverdage.",
            "{cue} {num}, i alt {amount} kr., betales inden {days} dage.",
            "Tak for din ordre! {cue}: {num}. {cue_b}: {num_b}.",
            "Stykprisen er {amount} kr., og vi har {qty} stk. på lager ({cue} {num}).",
            "Årsbudgettet er {amount} kr., hvoraf {amount_b} kr. er brugt.",
        ),
    ),
    "el": (
        "EUR",
        (
            "Αριθμός παραγγελίας",
            "Αριθμός τιμολογίου",
            "Κωδικός είδους",
            "Αριθμός αποστολής",
            "Αριθμός φακέλου",
            "Αριθμός σύμβασης",
            "Αριθμός αιτήματος",
            "Κωδικός κράτησης",
            "Σειριακός αριθμός",
            "Αριθμός παρτίδας",
            "Αριθμός αναφοράς",
            "Αριθμός δελτίου αποστολής",
        ),
        (
            "{cue}: {num}. Παρακαλούμε να τον αναφέρετε σε κάθε επόμενη επικοινωνία.",
            "{cue}: {num}· η παράδοση διαρκεί περίπου {days} εργάσιμες ημέρες.",
            "{cue} {num}, σύνολο {amount} EUR, πληρωτέο εντός {days} ημερών.",
            "Ευχαριστούμε για την παραγγελία! {cue}: {num}. {cue_b}: {num_b}.",
            "Η τιμή μονάδας είναι {amount} EUR και υπάρχουν {qty} τεμάχια σε απόθεμα ({cue} {num}).",
            "Ο ετήσιος προϋπολογισμός είναι {amount} EUR, από τα οποία έχουν δαπανηθεί {amount_b} EUR.",
        ),
    ),
    "et": (
        "EUR",
        (
            "Tellimuse number",
            "Arve number",
            "Tootekood",
            "Saadetise jälgimiskood",
            "Toimiku number",
            "Lepingu number",
            "Pöördumise number",
            "Broneeringu kood",
            "Seerianumber",
            "Partii number",
            "Viitenumber",
            "Saatelehe number",
        ),
        (
            "{cue}: {num}. Palun viidake sellele edasises kirjavahetuses.",
            "{cue}: {num}; tarne võtab umbes {days} tööpäeva.",
            "{cue} {num}, kokku {amount} EUR, maksetähtaeg {days} päeva.",
            "Täname tellimuse eest! {cue}: {num}. {cue_b}: {num_b}.",
            "Ühiku hind on {amount} EUR ja laos on {qty} tk ({cue} {num}).",
            "Aastaeelarve on {amount} EUR, millest on kulutatud {amount_b} EUR.",
        ),
    ),
    "fi": (
        "EUR",
        (
            "Tilausnumero",
            "Laskun numero",
            "Tuotekoodi",
            "Lähetystunnus",
            "Asianumero",
            "Sopimusnumero",
            "Tukipyynnön numero",
            "Varauskoodi",
            "Sarjanumero",
            "Eränumero",
            "Viitenumero",
            "Lähetteen numero",
        ),
        (
            "{cue}: {num}. Mainitsethan sen jatkossa kaikessa viestinnässä.",
            "{cue}: {num}; toimitus kestää noin {days} arkipäivää.",
            "{cue} {num}, yhteensä {amount} EUR, eräpäivä {days} päivän kuluttua.",
            "Kiitos tilauksestasi! {cue}: {num}. {cue_b}: {num_b}.",
            "Kappalehinta on {amount} EUR ja varastossa on {qty} kpl ({cue} {num}).",
            "Vuosibudjetti on {amount} EUR, josta on käytetty {amount_b} EUR.",
        ),
    ),
    "pl": (
        "zł",
        (
            "Numer zamówienia",
            "Numer faktury",
            "Kod produktu",
            "Numer przesyłki",
            "Sygnatura akt",
            "Numer umowy",
            "Numer zgłoszenia",
            "Kod rezerwacji",
            "Numer seryjny",
            "Numer partii",
            "Numer referencyjny",
            "Numer listu przewozowego",
        ),
        (
            "{cue}: {num}. Prosimy podawać go w dalszej korespondencji.",
            "{cue}: {num}; dostawa trwa około {days} dni roboczych.",
            "{cue} {num}, razem {amount} zł, płatne w ciągu {days} dni.",
            "Dziękujemy za zamówienie! {cue}: {num}. {cue_b}: {num_b}.",
            "Cena jednostkowa wynosi {amount} zł, na stanie jest {qty} szt. ({cue} {num}).",
            "Roczny budżet wynosi {amount} zł, z czego wydano {amount_b} zł.",
        ),
    ),
    "pt": (
        "EUR",
        (
            "Número da encomenda",
            "Número da fatura",
            "Referência do artigo",
            "Número de seguimento",
            "Número do processo",
            "Número do contrato",
            "Número do pedido",
            "Código de reserva",
            "Número de série",
            "Número do lote",
            "Referência",
            "Guia de remessa",
        ),
        (
            "{cue}: {num}. Indique-o em toda a correspondência futura.",
            "{cue}: {num}; a entrega demora cerca de {days} dias úteis.",
            "{cue} {num}, total {amount} EUR, a pagar em {days} dias.",
            "Obrigado pela sua encomenda! {cue}: {num}. {cue_b}: {num_b}.",
            "O preço unitário é de {amount} EUR e temos {qty} unidades em stock ({cue} {num}).",
            "O orçamento anual é de {amount} EUR, dos quais já foram gastos {amount_b} EUR.",
        ),
    ),
    "sk": (
        "EUR",
        (
            "Číslo objednávky",
            "Číslo faktúry",
            "Kód tovaru",
            "Sledovacie číslo zásielky",
            "Spisová značka",
            "Číslo zmluvy",
            "Číslo požiadavky",
            "Rezervačný kód",
            "Sériové číslo",
            "Číslo šarže",
            "Variabilný symbol",
            "Číslo dodacieho listu",
        ),
        (
            "{cue}: {num}. Uveďte ho, prosím, v ďalšej korešpondencii.",
            "{cue}: {num}; doručenie trvá približne {days} pracovných dní.",
            "{cue} {num}, spolu {amount} EUR, splatné do {days} dní.",
            "Ďakujeme za objednávku! {cue}: {num}. {cue_b}: {num_b}.",
            "Jednotková cena je {amount} EUR, na sklade je {qty} ks ({cue} {num}).",
            "Ročný rozpočet je {amount} EUR, z toho sa minulo {amount_b} EUR.",
        ),
    ),
    "sv": (
        "kr",
        (
            "Ordernummer",
            "Fakturanummer",
            "Artikelnummer",
            "Sändningsnummer",
            "Ärendenummer",
            "Avtalsnummer",
            "Biljettnummer",
            "Bokningskod",
            "Serienummer",
            "Batchnummer",
            "Referensnummer",
            "Följesedelsnummer",
        ),
        (
            "{cue}: {num}. Ange det i all vidare korrespondens.",
            "{cue}: {num}. Leveransen tar ungefär {days} arbetsdagar.",
            "{cue} {num}, totalt {amount} kr, att betala inom {days} dagar.",
            "Tack för din beställning! {cue}: {num}. {cue_b}: {num_b}.",
            "Styckpriset är {amount} kr och vi har {qty} st i lager ({cue} {num}).",
            "Årsbudgeten är {amount} kr, varav {amount_b} kr har använts.",
        ),
    ),
    "ga": (
        "EUR",
        (
            "Uimhir ordaithe",
            "Uimhir sonraisc",
            "Cód earra",
            "Uimhir rianaithe",
            "Uimhir an cháis",
            "Uimhir chonartha",
            "Uimhir thicéid",
            "Cód áirithinte",
            "Sraithuimhir",
            "Uimhir bhaisc",
            "Uimhir thagartha",
            "Uimhir an nóta seachadta",
        ),
        (
            "{cue}: {num}. Luaigh é i ngach comhfhreagras eile, le do thoil.",
            "{cue}: {num}; tógfaidh an seachadadh thart ar {days} lá oibre.",
            "{cue} {num}, iomlán {amount} EUR, le híoc laistigh de {days} lá.",
            "Go raibh maith agat as d'ordú! {cue}: {num}. {cue_b}: {num_b}.",
            "Is é {amount} EUR an praghas aonaid agus tá {qty} earra i stoc ({cue} {num}).",
            "Is é {amount} EUR an buiséad bliantúil, agus caitheadh {amount_b} EUR de.",
        ),
    ),
    "mt": (
        "EUR",
        (
            "Numru tal-ordni",
            "Numru tal-fattura",
            "Kodiċi tal-oġġett",
            "Numru tat-traċċar",
            "Numru tal-każ",
            "Numru tal-kuntratt",
            "Numru tat-talba",
            "Kodiċi tar-riżerva",
            "Numru tas-serje",
            "Numru tal-lott",
            "Numru ta' referenza",
            "Numru tan-nota tal-kunsinna",
        ),
        (
            "{cue}: {num}. Jekk jogħġbok semmih f'kull korrispondenza oħra.",
            "{cue}: {num}; il-kunsinna tieħu madwar {days} ġranet tax-xogħol.",
            "{cue} {num}, total {amount} EUR, li għandu jitħallas fi żmien {days} jum.",
            "Grazzi tal-ordni tiegħek! {cue}: {num}. {cue_b}: {num_b}.",
            "Il-prezz ta' kull unità huwa {amount} EUR u għandna {qty} biċċa fl-istokk ({cue} {num}).",
            "Il-baġit annwali huwa {amount} EUR, li minnhom intefqu {amount_b} EUR.",
        ),
    ),
}


def document(language: str, seed: int, index: int) -> Document:
    _, cues, templates = LANGS[language]
    rng = random.Random(f"pii-guard-negatives-eu/{seed}/{language}/{index}")
    sentences = []
    for _ in range(rng.randint(1, 3)):
        cue, cue_b = rng.sample(cues, 2)
        sentences.append(
            rng.choice(templates).format(
                cue=cue,
                cue2=cue[0].lower() + cue[1:],
                cue_b=cue_b,
                num=number(rng),
                num_b=number(rng),
                amount=amount(rng),
                amount_b=amount(rng),
                days=rng.randint(2, 60),
                qty=rng.randint(2, 5000),
            )
        )
    meta = {"kind": "negative-numbers", "split": "train", "source": "synthetic", "seed": seed}
    doc_id = f"{language}-negatives-eu-s{seed}-{index:05d}"
    return Document(doc_id, language, " ".join(sentences), (), meta)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--n", type=int, default=2000, help="documents per language")
    parser.add_argument("--seed", type=int, default=1525)
    parser.add_argument("--languages", default=",".join(LANGS))
    parser.add_argument("--out", type=Path, default=Path("eval/generated/negatives-eu"))
    parser.add_argument("--stats", type=Path, help="write per-language counts and hashes here")
    args = parser.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    stats: dict[str, dict[str, object]] = {}
    for language in args.languages.split(","):
        docs = [document(language, args.seed, i) for i in range(args.n)]
        path = args.out / f"{language}-negatives-train.jsonl"
        write_fixtures(path, docs)
        stats[language] = {
            "documents": len(docs),
            "file_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
        print(f"negatives-eu: {len(docs)} {language} documents -> {path}", file=sys.stderr)
    if args.stats:
        args.stats.write_text(json.dumps(stats, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
