"""The lexicon fetcher's offline parts (data/lexicons/fetch.py): parsers over small fixtures.

No network: downloading is never exercised here, and robots.txt handling is tested against a
parser fed from a string.
"""

from __future__ import annotations

import importlib.util
import sys
import urllib.robotparser
from pathlib import Path
from types import ModuleType

import pytest

REPO = Path(__file__).resolve().parents[2]
FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def fetch() -> ModuleType:
    spec = importlib.util.spec_from_file_location("lexicon_fetch", REPO / "data/lexicons/fetch.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _rows(name: str) -> list[tuple[object, ...]]:
    rows = []
    for line in (FIXTURES / name).read_text(encoding="utf-8").splitlines():
        if line.startswith("#"):
            continue
        cells = line.split("\t")
        population = int(cells[-1]) if cells[-1].isdigit() else cells[-1]
        rows.append((*cells[:-1], population))
    return rows


def test_every_source_says_whether_it_may_be_committed(fetch: ModuleType) -> None:
    for source in fetch.SOURCES:
        assert source.url.startswith("https://") and source.licence
        if not source.committed:
            assert "fetch-only" in source.licence
    committed = {s.key for s in fetch.SOURCES if s.committed}
    assert "ksh-hnt" in committed and "posta-irsz" not in committed and "osm-hu" not in committed


def test_ksh_settlements_fold_districts_and_skip_totals(fetch: ModuleType) -> None:
    rows = fetch.parse_ksh_settlements(_rows("ksh_helysegek.tsv"))
    assert rows == [
        ("Algyő", "Csongrád-Csanád", "03267", 4864),
        ("Budapest", "Budapest", "13578", 1671004),
        ("Szeged", "Csongrád-Csanád", "33367", 157695),
    ]


def test_ksh_postcodes(fetch: ModuleType) -> None:
    rows = [
        ("x", "Budapest 05. kerület", "x", "x", "x", "1051"),
        ("x", "Algyő", "x", "x", "x", "6750"),
        ("x", "Szeged", "x", "x", "x", "*"),
        ("x", "Rövid"),
    ]
    assert fetch.parse_ksh_postcodes(rows) == {("1051", "Budapest"), ("6750", "Algyő")}


def test_posta_postcodes(fetch: ModuleType) -> None:
    rows = [("IRSZ", "Település"), ("3300", "Eger"), (6720, "Szeged"), ("0123", "Sehol"), ("1",)]
    assert fetch.parse_posta_postcodes(rows) == {("3300", "Eger"), ("6720", "Szeged")}


def test_name_infographic_takes_names_per_page(fetch: ModuleType) -> None:
    # one name per table row, the row starting with the name
    text = "Fiú\nHelyezés Név\nBence 1 1234\nMáté 2 1100\n\fLány\nHanna 1 1300\nForrás: BM\n"
    assert fetch.parse_ksh_name_infographic(text) == ({"Bence", "Máté"}, {"Hanna"})


def test_register_names_are_title_cased_and_rare_ones_dropped(fetch: ModuleType) -> None:
    assert fetch.title_name(" SZŰCS ") == "Szűcs"
    assert fetch.title_name("KIS-NAGY") == "Kis-Nagy"
    surnames = fetch.parse_bm_surnames(
        [("Sorszám", "Név", "Darab"), (1, "NAGY", 230000), (2, "RITKANÉV", 3), (None, None)]
    )
    assert surnames == {"Nagy": 230000}
    male, female = fetch.parse_bm_given(
        [
            (1, "LÁSZLÓ", 200000, 30000, None, 1, "MÁRIA", 250000, 40000),
            (2, "RITKA", 1, 1, None, 2, "ÉVA", 100000, 20000),
            ("Rang", "Férfi"),
        ]
    )
    assert male == {"László": 230000} and female == {"Mária": 290000, "Éva": 120000}


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Kossuth Lajos utca", ("Kossuth Lajos", "utca")),
        ("Szent István körút", ("Szent István", "körút")),
        ("Május 1. tér", ("Május 1.", "tér")),
        ("Fő  Utca", ("Fő", "utca")),
        ("utca", None),
        ("M0 autóút", None),
        ("árok utca", None),
    ],
)
def test_split_street(fetch: ModuleType, name: str, expected: tuple[str, str] | None) -> None:
    assert fetch.split_street(name) == expected


def test_count_streets(fetch: ModuleType) -> None:
    bases, kinds = fetch.count_streets(["Fő utca", "Fő utca", "Fő tér", "Petőfi Sándor utca", "x"])
    assert bases == {"Fő": 3, "Petőfi Sándor": 1}
    assert kinds == {"utca": 3, "tér": 1}


def test_write_tsv_has_a_source_header(
    fetch: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = fetch.SOURCE_BY_KEY["ksh-hnt"]
    header = fetch._header([source], "settlement\tcounty")
    target = tmp_path / "out.tsv"
    # the progress line prints paths relative to the repository
    monkeypatch.setattr(fetch, "REPO", tmp_path)
    fetch.write_tsv(target, header, [("Eger", "Heves")])
    lines = target.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "# settlement\tcounty"
    assert lines[1] == f"# source: {source.url} ({source.licence})"
    assert lines[-1] == "Eger\tHeves"


def test_normalise_without_raw_files_writes_nothing(
    fetch: ModuleType,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in ("RAW", "LOCAL", "COMMITTED", "REPO"):
        monkeypatch.setattr(fetch, name, tmp_path / name.lower())
    fetch.normalise()
    # a missing source never empties the committed lists
    assert not (tmp_path / "committed").exists() and not (tmp_path / "local").exists()
    assert "run 'fetch' first" in capsys.readouterr().err


def test_robots_txt_is_respected(fetch: ModuleType) -> None:
    robots = urllib.robotparser.RobotFileParser()
    robots.parse(["User-agent: *", "Disallow: /apps/"])
    assert not robots.can_fetch(fetch.USER_AGENT, "https://www.ksh.hu/apps/hntr.main")
    assert robots.can_fetch(fetch.USER_AGENT, "https://www.ksh.hu/docs/helysegnevtar/x.xlsx")
    assert "pii-guard" in fetch.USER_AGENT and fetch.MIN_INTERVAL_S >= 1.0
