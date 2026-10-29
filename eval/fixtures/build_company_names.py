"""Build ``hu-company-names.jsonl``: person names inside Hungarian company names.

Sole traders (``Horváth Emese e.v.``, ``... egyéni vállalkozó``) and small partnerships
(``Tóth és Társa Bt.``, ``Balogh és Fia Kkt.``, ``Kiss-Lukács Kft.``) carry a person's name in
the company name. The organisation itself is kept by default policy (``docs/entities.md``),
but the person's name must be masked; this set measures exactly that, plus hard negatives:
company names made of ordinary words, some of which are also surnames (``Fekete Kavics Kft.``,
``Magyar Kalapács Zrt.``, ``Pécsi Kerámia Kft.``), which must not be masked.

Every company and person below is **fictional** (ADR 0005): surnames and given names come from
the language pack's lexicons, but each combination is invented, and brand words are made up.

Labels: the person's name inside a company name is ``PERSON`` (only the name part:
``{{PERSON|Tóth}} és Társa Bt.``); a company name without a person is ``ORGANIZATION``.
Each document's ``meta.companies`` lists the companies it mentions
(``{"name": ..., "person": ...|null}``), which :func:`measure` uses for the two numbers the
fixture exists for:

- **company person leak**: occurrences of a person's name inside a company name that are not
  fully covered by a masked span;
- **company over-masking**: occurrences of a company name without a person that any masked
  span overlaps.

Regenerate after editing (a test fails if the committed file is stale)::

    uv run python eval/fixtures/build_company_names.py

Measure (fast mode = ``rules,ner``; the NER model comes from ``PII_GUARD_NER_MODEL``)::

    uv run python eval/fixtures/build_company_names.py --measure --detectors rules,ner
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from pii_guard.eval import Document, from_markup, label, load_fixtures, write_fixtures

HERE = Path(__file__).resolve().parent
NAME = "hu-company-names.jsonl"


def P(v: str) -> str:
    return label("PERSON", v)


def ORG(v: str) -> str:
    return label("ORGANIZATION", v)


def E(v: str) -> str:
    return label("EMAIL", v)


def PH(v: str) -> str:
    return label("PHONE", v)


def A(v: str) -> str:
    return label("ADDRESS", v)


def _co(name: str, person: str | None = None) -> dict[str, str | None]:
    return {"name": name, "person": person}


# (id suffix, marked text, companies, kind, tags)
_DOCS: list[tuple[str, str, list[dict[str, str | None]], str, list[str]]] = [
    # --- Sole traders: e.v., ev., egyéni vállalkozó ---------------------------------------
    (
        "0001",
        f"Számla kiállítója: {P('Horváth Emese')} e.v., adószáma a fejlécen. A teljesítés "
        f"igazolását {P('Horváth Emese')} e.v.-nek kell visszaküldeni.",
        [_co("Horváth Emese e.v.", "Horváth Emese")],
        "invoice",
        ["sole-trader", "e.v.", "inflected"],
    ),
    (
        "0002",
        f"Megbízott: {P('Balogh Ernő')} egyéni vállalkozó. A megbízási díjat "
        f"{P('Balogh Ernő')} egyéni vállalkozónak havonta utaljuk.",
        [_co("Balogh Ernő egyéni vállalkozó", "Balogh Ernő")],
        "contract",
        ["sole-trader", "egyéni vállalkozó", "inflected"],
    ),
    (
        "0003",
        f"szia, a burkolást {P('Papp Zsófia')} ev. csinálja, {P('Papp Zsófia')} ev.-től "
        "kérj árajánlatot jövő hétre",
        [_co("Papp Zsófia ev.", "Papp Zsófia")],
        "chat",
        ["sole-trader", "ev.", "inflected", "informal"],
    ),
    (
        "0004",
        f"{P('LUKÁCS GÁBOR')} E.V.\nVállalkozói nyilvántartási szám a számla alján.\n"
        f"Vevő: {ORG('Kitalált Ingatlan Kft.')}",
        [_co("LUKÁCS GÁBOR E.V.", "LUKÁCS GÁBOR"), _co("Kitalált Ingatlan Kft.")],
        "invoice",
        ["sole-trader", "e.v.", "upper-case"],
    ),
    (
        "0005",
        f"A fuvarozást {P('Ördögh Tihamér')} e.v. végzi; a rakodásról "
        f"{P('Ördögh Tihamér')} e.v. küld visszaigazolást.",
        [_co("Ördögh Tihamér e.v.", "Ördögh Tihamér")],
        "email",
        ["sole-trader", "e.v.", "out-of-lexicon"],
    ),
    (
        "0006",
        f"Alvállalkozó: {P('Kalocsai-Fenyő Tímea')} egyéni vállalkozó, "
        f"{E('kalocsai.fenyo@example.com')}.",
        [_co("Kalocsai-Fenyő Tímea egyéni vállalkozó", "Kalocsai-Fenyő Tímea")],
        "contract",
        ["sole-trader", "egyéni vállalkozó", "out-of-lexicon", "hyphenated"],
    ),
    (
        "0007",
        f"Kedves {P('Szabó Réka')}! Az ajánlatot továbbítottuk, a szerződést "
        f"{P('Szabó Réka')} e.v. nevére állítjuk ki. Üdvözlettel: {P('Fodor Bálint')}",
        [_co("Szabó Réka e.v.", "Szabó Réka")],
        "email",
        ["sole-trader", "e.v.", "consistency", "common-word-surname"],
    ),
    (
        "0008",
        f"Szállító: {P('Nagy Ilona')}, e.v., a szállítólevelet {P('Nagy Ilona')} e.v.-vel "
        f"egyeztettük, és {P('Nagy Ilona')} aláírta.",
        [_co("Nagy Ilona, e.v.", "Nagy Ilona"), _co("Nagy Ilona e.v.", "Nagy Ilona")],
        "note",
        ["sole-trader", "e.v.", "consistency", "common-word-surname", "inflected"],
    ),
    (
        "0009",
        f"Tárgy: {P('Kovács Jánosné')} e.v. bérleti díja. {P('Kovács Jánosné')} "
        "e.v. a második negyedévre is fizetett.",
        [_co("Kovács Jánosné e.v.", "Kovács Jánosné")],
        "letter",
        ["sole-trader", "e.v.", "married-name"],
    ),
    (
        "0010",
        f"A {P('Fekete Bendegúz')} egyéni vállalkozóval kötött keretszerződés 2027. június "
        "30-ig érvényes.",
        [_co("Fekete Bendegúz egyéni vállalkozó", "Fekete Bendegúz")],
        "contract",
        ["sole-trader", "egyéni vállalkozó", "inflected", "common-word-surname"],
    ),
    (
        "0011",
        f"Telefon: {PH('+36 30 555 0198')}, {P('Zsombok Vendelin')} ev., kertépítés és fakivágás.",
        [_co("Zsombok Vendelin ev.", "Zsombok Vendelin")],
        "form",
        ["sole-trader", "ev.", "out-of-lexicon"],
    ),
    # --- Bt., Kkt.: partnerships named after their members ---------------------------------
    (
        "0012",
        f"A könyvelést a {P('Tóth')} és Társa Bt. végzi, a {P('Tóth')} és Társa Bt.-nek "
        "minden hónap 5-ig küldjük a bizonylatokat.",
        [_co("Tóth és Társa Bt.", "Tóth")],
        "email",
        ["Bt.", "és Társa", "inflected"],
    ),
    (
        "0013",
        f"Vállalkozó: {P('Balogh')} és Fia Kkt., képviseli az ügyvezető. A "
        f"{P('Balogh')} és Fia Kkt.-val kötött szerződés melléklete a műszaki leírás.",
        [_co("Balogh és Fia Kkt.", "Balogh")],
        "contract",
        ["Kkt.", "és Fia", "inflected"],
    ),
    (
        "0014",
        f"A {P('Szabó')} és Fiai Kkt. ajánlata a legkedvezőbb, a {P('Szabó')} és Fiai Kkt. "
        "határideje viszont hosszabb.",
        [_co("Szabó és Fiai Kkt.", "Szabó")],
        "note",
        ["Kkt.", "és Fiai", "common-word-surname"],
    ),
    (
        "0015",
        f"Címzett: {P('Molnár Péter')} Bt., {A('6720 Szeged, Kitalált tér 3.')}",
        [_co("Molnár Péter Bt.", "Molnár Péter")],
        "letter",
        ["Bt.", "surname-given", "common-word-surname"],
    ),
    (
        "0016",
        f"A tetőfedést a {P('Horváth')} Bt végezte, a garanciális javítást a "
        f"{P('Horváth')} Bt-től kérjük.",
        [_co("Horváth Bt", "Horváth")],
        "email",
        ["Bt", "no-dot", "bare-surname", "inflected"],
    ),
    (
        "0017",
        f"NYILATKOZAT\nAlulírott, a {P('NÉMETH')} ÉS TÁRSA BT. képviselője kijelentem, hogy a "
        "társaság nem áll végelszámolás alatt.",
        [_co("NÉMETH ÉS TÁRSA BT.", "NÉMETH")],
        "form",
        ["Bt.", "és Társa", "upper-case"],
    ),
    (
        "0018",
        f"A {P('Varga')} és {P('Kiss')} Kkt. két tagja egyetemlegesen felel a társaság "
        "tartozásaiért.",
        [_co("Varga és Kiss Kkt.", "Varga")],
        "contract",
        ["Kkt.", "two-surnames", "common-word-surname"],
    ),
    (
        "0019",
        f"ok, akkor a {P('Simon')} & Társa Bt.-vel megyünk tovább, a másik ajánlat drága volt",
        [_co("Simon & Társa Bt.", "Simon")],
        "chat",
        ["Bt.", "és Társa", "ampersand", "inflected", "informal"],
    ),
    (
        "0020",
        f"Bérlő: {P('Pintér Zoltán')} és Társa Bt. A bérleti díjat a {P('Pintér Zoltán')} "
        "és Társa Bt. negyedévente előre fizeti.",
        [_co("Pintér Zoltán és Társa Bt.", "Pintér Zoltán")],
        "contract",
        ["Bt.", "és Társa", "surname-given"],
    ),
    (
        "0021",
        f"A {P('Fodor')} Bt.-nek és a {P('Gulyás')} Kkt.-nak is kiküldtük a pályázati felhívást.",
        [_co("Fodor Bt.", "Fodor"), _co("Gulyás Kkt.", "Gulyás")],
        "note",
        ["Bt.", "Kkt.", "bare-surname", "inflected"],
    ),
    (
        "0022",
        f"Szerződő fél: {P('Kis')} Bt. A {P('Kis')} Bt. a munkát a helyszínen végzi.",
        [_co("Kis Bt.", "Kis")],
        "contract",
        ["Bt.", "bare-surname", "common-word-surname"],
    ),
    # --- Kft., Zrt., Nyrt., Kht., Nonprofit Kft. --------------------------------------------
    (
        "0023",
        f"A {P('Kiss-Lukács')} Kft. ügyvezetője aláírta a megrendelést, a "
        f"{P('Kiss-Lukács')} Kft.-vel a szállítást is egyeztetjük.",
        [_co("Kiss-Lukács Kft.", "Kiss-Lukács")],
        "email",
        ["Kft.", "hyphenated", "inflected"],
    ),
    (
        "0024",
        f"Ajánlatkérés a {P('Takács Eszter')} Kft. részére: 40 db irodai szék, szállítással.",
        [_co("Takács Eszter Kft.", "Takács Eszter")],
        "email",
        ["Kft.", "surname-given", "common-word-surname"],
    ),
    (
        "0025",
        f"A {P('Mészáros')} Építő Kft. nyerte a tendert; a {P('Mészáros')} Építő Kft.-t "
        "értesítettük.",
        [_co("Mészáros Építő Kft.", "Mészáros")],
        "note",
        ["Kft.", "surname-brand", "inflected"],
    ),
    (
        "0026",
        f"Tulajdonos: {P('Szilágyi Attila')} Zrt. ({P('Szilágyi Attila')} Zrt.-ben a "
        "szavazati jogok 60%-a).",
        [_co("Szilágyi Attila Zrt.", "Szilágyi Attila")],
        "form",
        ["Zrt.", "surname-given", "inflected"],
    ),
    (
        "0027",
        f"Az alapítvány partnere a {P('Hegedűs')} Nonprofit Kft., amely a {P('Hegedűs')} "
        "Nonprofit Kft.-hez tartozó műhelyekben tart foglalkozásokat.",
        [_co("Hegedűs Nonprofit Kft.", "Hegedűs")],
        "letter",
        ["Nonprofit Kft.", "bare-surname", "inflected"],
    ),
    (
        "0028",
        f"A {P('Bodnár-Rácz')} Kht. közleménye szerint a pályázati határidő változatlan.",
        [_co("Bodnár-Rácz Kht.", "Bodnár-Rácz")],
        "letter",
        ["Kht.", "hyphenated"],
    ),
    (
        "0029",
        f"Az {P('Orbán Lilla')} KFT. könyvelője kérte, hogy a számlát az {P('Orbán Lilla')} "
        "KFT. nevére állítsuk ki.",
        [_co("Orbán Lilla KFT.", "Orbán Lilla")],
        "email",
        ["Kft.", "surname-given", "upper-case-form"],
    ),
    (
        "0030",
        f"Ügyfelünk, a {P('Vincze')} Nyrt. leányvállalata, a {P('Vincze')} Kft. is "
        "csatlakozott a programhoz.",
        [_co("Vincze Nyrt.", "Vincze"), _co("Vincze Kft.", "Vincze")],
        "note",
        ["Nyrt.", "Kft.", "bare-surname"],
    ),
    (
        "0031",
        f"A {P('Fekete Anna')} Kft. és a {ORG('Fekete Kavics Kft.')} egy irodaházban "
        "bérel helyiséget.",
        [_co("Fekete Anna Kft.", "Fekete Anna"), _co("Fekete Kavics Kft.")],
        "note",
        ["Kft.", "surname-given", "common-word-surname", "hard-negative-nearby"],
    ),
    # --- Consistency with a standalone mention ----------------------------------------------
    (
        "0032",
        f"{P('Kelemen János')} szerint a raktár kész. {P('Kelemen János')} e.v.-nek "
        f"átutaltuk az előleget, a {P('Kelemen János')} e.v. által kiállított számla "
        "megérkezett.",
        [_co("Kelemen János e.v.", "Kelemen János")],
        "email",
        ["sole-trader", "e.v.", "consistency", "inflected"],
    ),
    (
        "0033",
        f"A {P('Sipos')} és Társa Bt. ügyvezetője {P('Sipos Márta')}. {P('Sipos Márta')} "
        "a Bt. nevében ír alá.",
        [_co("Sipos és Társa Bt.", "Sipos")],
        "contract",
        ["Bt.", "és Társa", "consistency"],
    ),
    # --- Hard negatives: company names without a person ------------------------------------
    (
        "0034",
        f"A {ORG('Pannon Csempe Kft.')} és a {ORG('Duna Lámpa Bt.')} közös standdal érkezik "
        "a vásárra.",
        [_co("Pannon Csempe Kft."), _co("Duna Lámpa Bt.")],
        "note",
        ["hard-negative", "Kft.", "Bt."],
    ),
    (
        "0035",
        f"A {ORG('Magyar Kalapács Zrt.')} beszállítója a {ORG('Fekete Kavics Kft.')}, a "
        f"logisztikát a {ORG('Kék Madár Nyrt.')} intézi.",
        [_co("Magyar Kalapács Zrt."), _co("Fekete Kavics Kft."), _co("Kék Madár Nyrt.")],
        "email",
        ["hard-negative", "common-word-surname"],
    ),
    (
        "0036",
        f"Ajánlatot kértünk a {ORG('Fekete Kft.')}-től, a {ORG('Magyar Kft.')}-től és a "
        f"{ORG('Szép Zrt.')}-től is.",
        [_co("Fekete Kft."), _co("Magyar Kft."), _co("Szép Zrt.")],
        "email",
        ["hard-negative", "common-word-surname", "bare-surname", "inflected"],
    ),
    (
        "0037",
        f"A {ORG('Kis Csiga Kft.')} és a {ORG('Nagy Ugrás Bt.')} játszóházakat üzemeltet; a "
        f"{ORG('Fehér Felhő Kft.')} a dekorációt adja.",
        [_co("Kis Csiga Kft."), _co("Nagy Ugrás Bt."), _co("Fehér Felhő Kft.")],
        "note",
        ["hard-negative", "common-word-surname"],
    ),
    (
        "0038",
        f"Pékáru: {ORG('Budai Pékség Bt.')}, kerámia: {ORG('Pécsi Kerámia Kft.')}, bútor: "
        f"{ORG('Lengyel Bútor Kft.')}.",
        [_co("Budai Pékség Bt."), _co("Pécsi Kerámia Kft."), _co("Lengyel Bútor Kft.")],
        "form",
        ["hard-negative", "place-surname"],
    ),
    (
        "0039",
        f"A {ORG('Vörös Rózsa Kft.')} virágküldő szolgálat; a {ORG('Barna Kenyér Bt.')} és a "
        f"{ORG('Szép Napok Bt.')} is náluk rendel.",
        [_co("Vörös Rózsa Kft."), _co("Barna Kenyér Bt."), _co("Szép Napok Bt.")],
        "note",
        ["hard-negative", "common-word-surname", "common-word-given-name"],
    ),
    (
        "0040",
        f"A {ORG('Napfény Nonprofit Kft.')} és az {ORG('Ezüstnyír Kht.')} közös pályázatát a "
        f"{ORG('Próbabank Nyrt.')} támogatja.",
        [_co("Napfény Nonprofit Kft."), _co("Ezüstnyír Kht."), _co("Próbabank Nyrt.")],
        "letter",
        ["hard-negative", "Nonprofit Kft.", "Kht.", "Nyrt."],
    ),
    (
        "0041",
        f"A {ORG('Zöld Mező Kft.')} szerint a bt.-k és kft.-k könyvelése idén drágább lett; az "
        f"{ORG('Arany Kulcs Zrt.')} ezt nem erősítette meg.",
        [_co("Zöld Mező Kft."), _co("Arany Kulcs Zrt.")],
        "email",
        ["hard-negative", "lower-case-forms"],
    ),
    (
        "0042",
        f"Mintaszöveg: a {ORG('Mókusdomb Tanácsadó Bt.')} egyéni vállalkozókat és kisebb "
        "betéti társaságokat segít a pályázatokban.",
        [_co("Mókusdomb Tanácsadó Bt.")],
        "note",
        ["hard-negative", "generic-sole-trader-mention"],
    ),
    (
        "0043",
        f"A {ORG('Kékfelhő Informatikai Zrt.')} és a {ORG('Vadgesztenye Vendéglátó Kft.')} "
        f"szerződését a {ORG('Mintavár Építő Zrt.')} jogásza készítette.",
        [
            _co("Kékfelhő Informatikai Zrt."),
            _co("Vadgesztenye Vendéglátó Kft."),
            _co("Mintavár Építő Zrt."),
        ],
        "contract",
        ["hard-negative"],
    ),
    (
        "0044",
        f"Tisztelt {ORG('Arany Kulcs Zrt.')}! A falu kovácsa és a molnár is a "
        f"{ORG('Szép Napok Bt.')} vásárán árul.",
        [_co("Arany Kulcs Zrt."), _co("Szép Napok Bt.")],
        "letter",
        ["hard-negative", "common-word-lower-case"],
    ),
]


def company_documents() -> list[Document]:
    return [
        from_markup(
            f"hu-company-names-{suffix}",
            text,
            language="hu",
            meta={"kind": kind, "tags": tags, "companies": companies},
        )
        for suffix, text, companies, kind, tags in _DOCS
    ]


OUTPUTS = {NAME: company_documents}


# --- Measurement -------------------------------------------------------------------------


def _occurrences(text: str, needle: str) -> list[int]:
    found, start = [], text.find(needle)
    while start != -1:
        found.append(start)
        start = text.find(needle, start + 1)
    return found


def company_report(results: Sequence[object]) -> dict[str, object]:
    """Company-level leak and over-masking over ``run_documents`` results."""
    persons = leaked = plain = over = 0
    for result in results:
        doc = result.document  # type: ignore[attr-defined]
        masked = [(s.start, s.end) for s in result.masked_spans]  # type: ignore[attr-defined]
        seen: set[tuple[int, int]] = set()
        for company in doc.meta.get("companies", []):
            name, person = company["name"], company["person"]
            for start in _occurrences(doc.text, name):
                end = start + len(name)
                if person is None:
                    plain += 1
                    over += any(s < end and start < e for s, e in masked)
                    continue
                for gold in doc.spans:
                    key = (gold.start, gold.end)
                    if gold.entity_type.value != "PERSON" or key in seen:
                        continue
                    if start <= gold.start and gold.end <= end:
                        seen.add(key)
                        persons += 1
                        covered = sorted(
                            (s, e) for s, e in masked if s < gold.end and gold.start < e
                        )
                        pos = gold.start
                        for s, e in covered:
                            if s > pos:
                                break
                            pos = max(pos, e)
                        leaked += pos < gold.end

    def ratio(a: int, b: int) -> float | None:
        return round(a / b, 4) if b else None

    return {
        "person_occurrences": persons,
        "person_leaked": leaked,
        "person_leak_rate": ratio(leaked, persons),
        "plain_company_occurrences": plain,
        "plain_company_over_masked": over,
        "plain_company_over_masking_rate": ratio(over, plain),
    }


def measure(detectors: Sequence[str], path: Path = HERE / NAME) -> dict[str, object]:
    from pii_guard.eval import DetectorAnalyzer, run_documents

    analyzer = DetectorAnalyzer(detectors)
    if analyzer.skipped:
        raise SystemExit(f"could not load detectors: {analyzer.skipped}")
    report = company_report(run_documents(load_fixtures(path), analyzer))
    return {"detectors": list(analyzer.loaded), **report}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--measure", action="store_true", help="measure instead of building")
    parser.add_argument("--detectors", default="rules", help="comma-separated (default: rules)")
    args = parser.parse_args(argv)
    if args.measure:
        detectors = [d.strip() for d in args.detectors.split(",") if d.strip()]
        print(json.dumps(measure(detectors), indent=2))
        return 0
    for name, build in OUTPUTS.items():
        write_fixtures(HERE / name, build())
        print(f"wrote {HERE / name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
