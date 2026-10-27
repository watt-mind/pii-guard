"""Fetch public Hungarian name and place lists and normalise them into compact lexicons.

Two steps, both re-runnable:

``fetch``
    Download every source into ``data/lexicons/raw/`` (gitignored), politely: an identifying
    User-Agent, at most one request per second, ``robots.txt`` checked first, and an existing
    file is never downloaded again (``--force`` to refresh). Nothing is downloaded during
    tests or normal use.
``normalise``
    Read the cached raw files (offline) and write

    - the **committed** lexicons to ``src/pii_guard/lang/data/hu/`` (only sources whose terms
      allow redistribution with attribution, see ``MANIFEST.md``), and
    - the **local-only** lexicons to ``data/lexicons/raw/derived/hu/`` (sources without such
      terms, and the full OpenStreetMap street-name list, ODbL). Point
      ``PII_GUARD_LEXICON_DIR`` at that directory to use them on your machine.

Every lexicon is a UTF-8 TSV file, one entry per line: ``value<TAB>weight`` (plus extra
columns for settlements and postcodes), sorted, with a ``#`` header naming its source.

Usage (the parsers need two extra packages, never needed at runtime)::

    uv run --with openpyxl --with pypdf --with osmium python data/lexicons/fetch.py fetch
    uv run --with openpyxl --with pypdf --with osmium python data/lexicons/fetch.py normalise
    uv run --with openpyxl --with pypdf --with osmium python data/lexicons/fetch.py all

The lists are names and places only: no person records are fetched or written.
"""

# The parsers below only read files this script downloaded from the sources it names.
# ruff: noqa: S310

from __future__ import annotations

import argparse
import collections
import hashlib
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.request
import urllib.robotparser
from collections.abc import Callable, Iterable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
RAW = HERE / "raw"
LOCAL = RAW / "derived" / "hu"
COMMITTED = REPO / "src" / "pii_guard" / "lang" / "data" / "hu"

USER_AGENT = "pii-guard-lexicon-fetch/0.1 (+https://github.com/watt-mind/pii-guard)"
MIN_INTERVAL_S = 1.0

#: People with a given name or surname rarer than this are not listed (no near-unique names).
MIN_NAME_COUNT = 50
#: OpenStreetMap street names committed: a small, non-substantial sample (ODbL).
OSM_COMMITTED_TOP = 100


@dataclass(frozen=True, slots=True)
class Source:
    key: str
    url: str
    file: str
    licence: str
    committed: bool
    note: str = ""


SOURCES: tuple[Source, ...] = (
    Source(
        "ksh-hnt",
        "https://www.ksh.hu/docs/helysegnevtar/hnt_letoltes_2026.xlsx",
        "ksh-hnt-2026.xlsx",
        "CC BY 4.0 (ksh.hu/copyright)",
        committed=True,
        note="KSH Helységnévtár 2026-01-01: settlements, counties, KSH codes, postcodes",
    ),
    *(
        Source(
            f"ksh-names-{span}",
            f"https://www.ksh.hu/infografika/{year}/nevek_{span}.pdf",
            f"ksh-nevek_{span}.pdf",
            "CC BY 4.0 (ksh.hu/copyright)",
            committed=True,
            note="KSH infographic: 50 most chosen given names of newborns (BM data)",
        )
        for year, span in (
            ("2026", "2000-2025"),
            ("2026", "2015-2025"),
            ("2026", "2024-2025"),
            ("2025", "2014-2024"),
            ("2024", "2013-2023"),
            ("2023", "2012-2022"),
            ("2019", "2008-2018"),
        )
    ),
    Source(
        "posta-irsz",
        "https://www.posta.hu/static/internet/download/Iranyitoszam-Internet_uj.xlsx",
        "posta-iranyitoszam.xlsx",
        "All rights reserved (Magyar Posta Zrt.): fetch-only",
        committed=False,
        note="Magyar Posta postcode table; used locally to cross-check the KSH postcodes",
    ),
    Source(
        "bm-surnames",
        "https://cdn.kormany.hu/uploads/document/a/ab/abb/abb23fee88bca655a7148ed448b50298bb0e5fa6.xlsx",
        "bm-csaladinev-2026.xlsx",
        "No licence stated (kormany.hu): fetch-only",
        committed=False,
        note="BM: 100 most frequent birth family names in the register, 2026-01-01",
    ),
    Source(
        "bm-given",
        "https://cdn.kormany.hu/uploads/document/3/32/322/3222d7d872357b8e86e19012582062708af44955.xlsx",
        "bm-utonev-2026.xlsx",
        "No licence stated (kormany.hu): fetch-only",
        committed=False,
        note="BM: 100 most frequent given names per sex in the register, 2026-01-01",
    ),
    Source(
        "osm-hu",
        "https://download.geofabrik.de/europe/hungary-latest.osm.pbf",
        "osm-hungary-latest.osm.pbf",
        "ODbL 1.0 (© OpenStreetMap contributors): fetch-only, top-100 sample committed",
        committed=False,
        note="Geofabrik extract; highway=* name values",
    ),
)
SOURCE_BY_KEY = {s.key: s for s in SOURCES}


# --- Fetch ---------------------------------------------------------------------------------


class Fetcher:
    """One request per second at most, robots.txt respected, identifying User-Agent."""

    def __init__(self, min_interval: float = MIN_INTERVAL_S) -> None:
        self.min_interval = min_interval
        self._last = 0.0
        self._robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}

    def _wait(self) -> None:
        delay = self._last + self.min_interval - time.monotonic()
        if delay > 0:
            time.sleep(delay)
        self._last = time.monotonic()

    def _open(self, url: str):  # urllib response
        self._wait()
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        return urllib.request.urlopen(request, timeout=120)

    def allowed(self, url: str) -> bool:
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self._robots:
            parser = urllib.robotparser.RobotFileParser()
            try:
                with self._open(origin + "/robots.txt") as response:
                    parser.parse(response.read().decode("utf-8", "replace").splitlines())
            except urllib.error.HTTPError as exc:
                if exc.code in (401, 403):
                    self._robots[origin] = None  # the site refuses automated access
                    return False
                parser.parse([])  # no robots.txt: everything allowed
            self._robots[origin] = parser
        parser = self._robots[origin]
        return parser is not None and parser.can_fetch(USER_AGENT, url)

    def download(self, url: str, target: Path) -> None:
        if not self.allowed(url):
            raise PermissionError(f"robots.txt or the server disallows {url}")
        tmp = target.with_suffix(target.suffix + ".part")
        with self._open(url) as response, tmp.open("wb") as out:
            while chunk := response.read(1 << 20):
                out.write(chunk)
        tmp.replace(target)


def fetch(keys: Sequence[str], force: bool = False) -> int:
    RAW.mkdir(parents=True, exist_ok=True)
    fetcher = Fetcher()
    failures = 0
    for key in keys:
        source = SOURCE_BY_KEY[key]
        target = RAW / source.file
        if target.exists() and not force:
            print(f"  cached   {source.key}: {target.name}")
            continue
        try:
            fetcher.download(source.url, target)
        except (OSError, PermissionError) as exc:
            failures += 1
            print(f"  FAILED   {source.key}: {exc}", file=sys.stderr)
            continue
        print(f"  fetched  {source.key}: {target.name} ({target.stat().st_size} bytes)")
    return failures


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


# --- Parsing (pure functions over rows, tested with small fixtures) --------------------------

_COUNTY_CAPITAL = "főváros"


def title_name(raw: str) -> str:
    """``"SZŰCS"`` -> ``"Szűcs"``, ``"KIS-NAGY"`` -> ``"Kis-Nagy"`` (register names are upper)."""
    return "-".join(part[:1].upper() + part[1:].lower() for part in raw.strip().split("-"))


def _clean(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def parse_ksh_settlements(rows: Iterable[Sequence[object]]) -> list[tuple[str, str, str, int]]:
    """KSH "Helységek" sheet rows -> ``(name, county, ksh_code, population)``.

    Budapest's districts (``Budapest 05. ker.``) are folded into ``Budapest``; header and
    total rows are skipped.
    """
    out: list[tuple[str, str, str, int]] = []
    for row in rows:
        if len(row) < 11:
            continue
        name, code, status, county, population = (
            _clean(row[0]),
            _clean(row[1]),
            _clean(row[2]),
            _clean(row[3]),
            row[10],
        )
        if not code.isdigit() or not isinstance(population, int | float):
            continue
        if status == "fővárosi kerület":
            continue
        if status.startswith(_COUNTY_CAPITAL):
            county = "Budapest"
        out.append((name, county, code.zfill(5), int(population)))
    return sorted(out)


def parse_ksh_postcodes(rows: Iterable[Sequence[object]]) -> set[tuple[str, str]]:
    """KSH "Településrészek" rows -> ``{(postcode, settlement)}``.

    Budapest district rows (``Budapest 05. kerület``) map to ``Budapest``; ``*`` (many
    postcodes, listed only by Magyar Posta) is skipped: Budapest postcodes are validated by
    their structure instead (``1`` + district + digit).
    """
    pairs: set[tuple[str, str]] = set()
    for row in rows:
        if len(row) < 6:
            continue
        settlement, postcode = _clean(row[1]), _clean(row[5])
        if not re.fullmatch(r"[1-9]\d{3}", postcode):
            continue
        if settlement.startswith("Budapest"):
            settlement = "Budapest"
        pairs.add((postcode, settlement))
    return pairs


def parse_posta_postcodes(rows: Iterable[Sequence[object]]) -> set[tuple[str, str]]:
    """Magyar Posta "Települések" sheet rows -> ``{(postcode, settlement)}``."""
    pairs: set[tuple[str, str]] = set()
    for row in rows:
        if len(row) < 2:
            continue
        postcode, settlement = _clean(row[0]), _clean(row[1])
        if re.fullmatch(r"[1-9]\d{3}", postcode) and settlement:
            pairs.add((postcode, settlement))
    return pairs


_NAME_RE = re.compile(r"[A-ZÁÉÍÓÖŐÚÜŰ][a-záéíóöőúüű]+")


def parse_ksh_name_infographic(text: str) -> tuple[set[str], set[str]]:
    """Text of a KSH ``nevek_<y1>-<y2>.pdf`` -> ``(boys' names, girls' names)``.

    The PDF has one page per sex (boys first), each a table of the 50 most chosen names in two
    years. Only the names are taken; their counts are not reliably recoverable from the layout.
    """
    pages = text.split("\f")
    out: list[set[str]] = [set(), set()]
    for index, page in enumerate(pages[:2]):
        page = unicodedata.normalize("NFC", page.replace("ﬁ", "fi").replace("ﬂ", "fl"))
        for line in page.splitlines():
            match = _NAME_RE.match(line.strip())
            if match and not _is_header_word(match.group(0)):
                out[index].add(match.group(0))
    return out[0], out[1]


_HEADER_WORDS = frozenset(
    {"Az", "Gyermekek", "Név", "Helyezés", "Helyezésén", "Helyezése", "Új", "Már", "Forrás",
     "Változás", "Fiú", "Lány", "Leány", "Összesen"}
)  # fmt: skip


def _is_header_word(word: str) -> bool:
    return word in _HEADER_WORDS


def parse_bm_surnames(rows: Iterable[Sequence[object]]) -> dict[str, int]:
    """BM family-name sheet rows (``rank, NAME, count``) -> ``{Name: count}``."""
    out: dict[str, int] = {}
    for row in rows:
        cells = [c for c in row if c is not None]
        names = [c for c in cells if isinstance(c, str) and _NAME_RE.fullmatch(title_name(c))]
        counts = [c for c in cells if isinstance(c, int)]
        if len(names) == 1 and len(counts) >= 1 and counts[-1] >= MIN_NAME_COUNT:
            out[title_name(names[0])] = counts[-1]
    return out


def parse_bm_given(rows: Iterable[Sequence[object]]) -> tuple[dict[str, int], dict[str, int]]:
    """BM given-name sheet rows ``(rank, MALE, first, second, [gap], rank, FEMALE, first,
    second)`` -> ``({male: count}, {female: count})``, counting first and second given names.
    """
    male: dict[str, int] = {}
    female: dict[str, int] = {}
    for row in rows:
        found: list[tuple[str, int]] = []
        cells = list(row)
        for i, cell in enumerate(cells):
            if not (isinstance(cell, str) and _NAME_RE.fullmatch(title_name(cell))):
                continue
            counts = [c for c in cells[i + 1 : i + 3] if isinstance(c, int)]
            if counts:
                found.append((title_name(cell), sum(counts)))
        if len(found) != 2:
            continue
        for (name, total), target in zip(found, (male, female), strict=True):
            if total >= MIN_NAME_COUNT:
                target[name] = total
    return male, female


# Public-space types (közterület jellege), longest first so "körút" wins over "út".
STREET_TYPES: tuple[str, ...] = (
    "utca", "út", "tér", "körút", "köz", "sor", "sétány", "rakpart", "lépcső", "lejtő",
    "liget", "park", "dűlő", "dűlőút", "fasor", "határút", "kert", "körtér", "lakótelep",
    "átjáró", "udvar", "telep", "tanya", "sugárút", "árok", "part", "domb", "hegy",
    "ösvény", "sikátor", "útja", "tere", "major", "erdősor", "mélyút", "kapu", "zug",
    "bekötőút", "híd", "puszta", "sziget", "aluljáró",
)  # fmt: skip


def split_street(name: str) -> tuple[str, str] | None:
    """``"Kossuth Lajos utca"`` -> ``("Kossuth Lajos", "utca")``; None without a known type."""
    parts = _clean(name).split(" ")
    if len(parts) < 2:
        return None
    kind = parts[-1].casefold()
    if kind not in STREET_TYPES:
        return None
    base = " ".join(parts[:-1])
    if not base or not (base[0].isupper() or base[0].isdigit()):
        return None
    return base, kind


def count_streets(
    names: Iterable[str],
) -> tuple[collections.Counter[str], collections.Counter[str]]:
    """Street names (one per OSM way) -> (base-name counts, street-type counts)."""
    bases: collections.Counter[str] = collections.Counter()
    kinds: collections.Counter[str] = collections.Counter()
    for name in names:
        split = split_street(name)
        if split is None:
            continue
        bases[split[0]] += 1
        kinds[split[1]] += 1
    return bases, kinds


# --- Raw readers (need the optional parsers) -----------------------------------------------


def _xlsx_rows(path: Path, sheet: int = 0) -> Iterator[tuple[object, ...]]:
    import openpyxl  # optional: only the normaliser needs it

    workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        yield from workbook.worksheets[sheet].iter_rows(values_only=True)
    finally:
        workbook.close()


def _pdf_text(path: Path) -> str:
    import pypdf  # optional: only the normaliser needs it

    reader = pypdf.PdfReader(path)
    return "\f".join(page.extract_text() or "" for page in reader.pages)


def _osm_street_names(path: Path) -> Iterator[str]:
    import osmium  # optional: only the normaliser needs it

    for way in osmium.FileProcessor(str(path), osmium.osm.WAY):
        tags = way.tags
        if "highway" in tags and "name" in tags:
            yield tags["name"]


# --- Writers ---------------------------------------------------------------------------------


def _header(sources: Sequence[Source], columns: str) -> list[str]:
    lines = [f"# {columns}"]
    for source in sources:
        lines.append(f"# source: {source.url} ({source.licence})")
    lines.append("# generated by data/lexicons/fetch.py normalise; see data/lexicons/MANIFEST.md")
    return lines


def write_tsv(path: Path, header: list[str], rows: Iterable[Sequence[object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = ["\t".join(str(c) for c in row) for row in rows]
    path.write_text("\n".join([*header, *body]) + "\n", encoding="utf-8")
    print(f"  wrote    {path.relative_to(REPO)} ({len(body)} entries)")


def _weighted(counter: dict[str, int] | collections.Counter[str]) -> list[tuple[str, int]]:
    return sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))


# --- Normalise -------------------------------------------------------------------------------


def _have(key: str) -> Path | None:
    path = RAW / SOURCE_BY_KEY[key].file
    if path.exists():
        return path
    print(f"  missing  {key}: run 'fetch' first ({path.name})", file=sys.stderr)
    return None


def normalise_ksh() -> set[tuple[str, str]]:
    path = _have("ksh-hnt")
    if path is None:
        return set()
    source = SOURCE_BY_KEY["ksh-hnt"]
    settlements = parse_ksh_settlements(_xlsx_rows(path, 0))
    write_tsv(
        COMMITTED / "settlements.tsv",
        _header([source], "settlement\tcounty\tksh_code\tpopulation"),
        settlements,
    )
    postcodes = parse_ksh_postcodes(_xlsx_rows(path, 1))
    write_tsv(
        COMMITTED / "postcodes.tsv",
        _header([source], "postcode\tsettlement (Budapest: also any 1 + district 01-23 + digit)"),
        sorted(postcodes),
    )
    return postcodes


def normalise_given_names() -> None:
    sources = [s for s in SOURCES if s.key.startswith("ksh-names-")]
    boys: collections.Counter[str] = collections.Counter()
    girls: collections.Counter[str] = collections.Counter()
    for source in sources:
        path = _have(source.key)
        if path is None:
            continue
        b, g = parse_ksh_name_infographic(_pdf_text(path))
        boys.update(b)
        girls.update(g)
    if not boys and not girls:
        return  # nothing fetched: keep the committed lists rather than emptying them
    # Weight: in how many of the infographics' year lists the name is a top-50 name.
    for kind, counter in (("given_names_m", boys), ("given_names_f", girls)):
        write_tsv(
            COMMITTED / f"recent_{kind}.tsv",
            _header(sources, "given name\tweight (top-50 appearances across the yearly lists)"),
            _weighted(counter),
        )


def normalise_bm() -> None:
    path = _have("bm-surnames")
    if path is not None:
        surnames = parse_bm_surnames(_xlsx_rows(path))
        write_tsv(
            LOCAL / "surnames.tsv",
            _header([SOURCE_BY_KEY["bm-surnames"]], "surname\tpeople"),
            _weighted(surnames),
        )
    path = _have("bm-given")
    if path is not None:
        male, female = parse_bm_given(_xlsx_rows(path))
        for kind, counts in (("given_names_m", male), ("given_names_f", female)):
            write_tsv(
                LOCAL / f"{kind}.tsv",
                _header([SOURCE_BY_KEY["bm-given"]], "given name\tpeople"),
                _weighted(counts),
            )


def normalise_posta(ksh_postcodes: set[tuple[str, str]]) -> None:
    path = _have("posta-irsz")
    if path is None:
        return
    posta = parse_posta_postcodes(_xlsx_rows(path, 0))
    write_tsv(
        LOCAL / "postcodes_posta.tsv",
        _header([SOURCE_BY_KEY["posta-irsz"]], "postcode\tsettlement"),
        sorted(posta),
    )
    if ksh_postcodes:
        non_bp = {p for p in posta if not p[0].startswith("1")}
        ksh_non_bp = {p for p in ksh_postcodes if not p[0].startswith("1")}
        both = non_bp & ksh_non_bp
        print(
            f"  check    postcode pairs outside Budapest: KSH {len(ksh_non_bp)}, "
            f"Posta {len(non_bp)}, in both {len(both)}"
        )


def normalise_osm() -> None:
    path = _have("osm-hu")
    if path is None:
        return
    source = SOURCE_BY_KEY["osm-hu"]
    bases, kinds = count_streets(_osm_street_names(path))
    write_tsv(
        LOCAL / "street_names.tsv",
        _header([source], "street name without its type\tOSM ways"),
        [(b, n) for b, n in _weighted(bases) if n >= 2],
    )
    # Committed: only the most common names (generic: Kossuth Lajos, Petőfi Sándor, Fő ...)
    # and the type counts, a non-substantial extract of the database.
    write_tsv(
        COMMITTED / "street_names.tsv",
        _header([source], "street name without its type\tOSM ways"),
        _weighted(bases)[:OSM_COMMITTED_TOP],
    )
    write_tsv(
        COMMITTED / "street_types.tsv",
        _header([source], "public-space type\tOSM ways"),
        [(k, kinds.get(k, 0)) for k in sorted(set(STREET_TYPES), key=lambda k: (-kinds[k], k))],
    )


def normalise() -> None:
    postcodes = normalise_ksh()
    normalise_given_names()
    normalise_bm()
    normalise_posta(postcodes)
    normalise_osm()


def checksums() -> None:
    """Print a SHA-256 table of the raw files (for MANIFEST.md)."""
    for source in SOURCES:
        path = RAW / source.file
        digest = sha256(path) if path.exists() else "(not fetched)"
        print(f"| `{source.key}` | `{source.file}` | `{digest}` |")


COMMANDS: dict[str, Callable[[argparse.Namespace], int]] = {
    "fetch": lambda a: fetch(a.sources or [s.key for s in SOURCES], force=a.force),
    "normalise": lambda a: normalise() or 0,
    "checksums": lambda a: checksums() or 0,
    "all": lambda a: (
        fetch(a.sources or [s.key for s in SOURCES], force=a.force) or normalise() or 0
    ),
}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("command", choices=sorted(COMMANDS))
    parser.add_argument("--source", dest="sources", action="append", choices=sorted(SOURCE_BY_KEY))
    parser.add_argument("--force", action="store_true", help="download again even if cached")
    args = parser.parse_args(argv)
    return COMMANDS[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
