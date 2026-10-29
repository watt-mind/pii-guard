"""Person names inside Hungarian company names (LAB-1149). All names are fictional (ADR 0005)."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from pii_guard.detect.pipeline import resolve_spans
from pii_guard.detect.rules import RuleDetector
from pii_guard.eval import dump_document, load_fixtures
from pii_guard.eval.cli import main as eval_main
from pii_guard.languages.hu.companies import (
    SCORE_FULL_NAME,
    SCORE_WEAK,
    find_company_person,
)
from pii_guard.types import EntityType, Span
from pii_guard.vault import PLACEHOLDER_RE, Vault

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = REPO_ROOT / "eval" / "fixtures"
COMPANY_FIXTURE = FIXTURES / "hu-company-names.jsonl"


def persons(text: str) -> list[str]:
    return [text[h.start : h.end] for h in find_company_person(text)]


def scores(text: str) -> list[float]:
    return [h.score for h in find_company_person(text)]


# --- Legal forms -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Számlát ad Horváth Emese e.v. a munkáról.", ["Horváth Emese"]),
        ("Számlát ad Horváth Emese e. v. a munkáról.", ["Horváth Emese"]),
        ("Számlát ad Horváth Emese E.V. a munkáról.", ["Horváth Emese"]),
        ("Számlát ad Horváth Emese ev. a munkáról.", ["Horváth Emese"]),
        ("Számlát ad Horváth Emese, e.v. a munkáról.", ["Horváth Emese"]),
        ("Megbízott: Balogh Ernő egyéni vállalkozó.", ["Balogh Ernő"]),
        ("A Tóth és Társa Bt. ajánlata.", ["Tóth"]),
        ("A Horváth Bt ajánlata.", ["Horváth"]),
        ("A Balogh és Fia Kkt. ajánlata.", ["Balogh"]),
        ("A Kiss-Lukács Kft. ajánlata.", ["Kiss-Lukács"]),
        ("A Szilágyi Attila Zrt. ajánlata.", ["Szilágyi Attila"]),
        ("A Vincze Nyrt. ajánlata.", ["Vincze"]),
        ("A Bodnár-Rácz Kht. közleménye.", ["Bodnár-Rácz"]),
        ("A Hegedűs Nonprofit Kft. műhelye.", ["Hegedűs"]),
        ("AZ ORBÁN LILLA KFT. NEVÉRE", ["ORBÁN LILLA"]),
        ("NÉMETH ÉS TÁRSA BT.", ["NÉMETH"]),
    ],
)
def test_each_legal_form(text: str, expected: list[str]) -> None:
    assert persons(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("A Horváth Bt.-nek küldtük.", ["Horváth"]),
        ("A Horváth Bt-től kérjük.", ["Horváth"]),
        ("A Kiss-Lukács Kft.-vel egyeztetünk.", ["Kiss-Lukács"]),
        ("A Balogh és Fia Kkt.-val kötött szerződés.", ["Balogh"]),
        ("Papp Zsófia ev.-től kérj ajánlatot.", ["Papp Zsófia"]),
        ("Kelemen János e.v.-nek utaltunk.", ["Kelemen János"]),
        ("Balogh Ernő egyéni vállalkozónak fizetünk.", ["Balogh Ernő"]),
        ("A Fekete Bendegúz egyéni vállalkozóval kötött szerződés.", ["Fekete Bendegúz"]),
        ("A Szilágyi Attila Zrt.-ben szavaz.", ["Szilágyi Attila"]),
    ],
)
def test_inflected_forms(text: str, expected: list[str]) -> None:
    assert persons(text) == expected


def test_married_names_and_two_partners() -> None:
    assert persons("Tárgy: Kovács Jánosné e.v. bérleti díja.") == ["Kovács Jánosné"]
    assert persons("A Varga és Kiss Kkt. két tagja.") == ["Varga", "Kiss"]
    assert persons("A Simon & Társa Bt.-vel megyünk tovább.") == ["Simon"]
    assert persons("Bérlő: Pintér Zoltán és Társa Bt.") == ["Pintér Zoltán"]
    # A child names a parent even when the surname isn't in the lexicon; a partner doesn't.
    assert persons("A Zsombok és Fia Kkt. ajánlata.") == ["Zsombok"]
    assert scores("A Zsombok és Fia Kkt. ajánlata.") == [SCORE_WEAK]
    assert persons("A Pannon és Társa Bt. ajánlata.") == []
    assert persons("Tisztelt Kft.!") == []
    # Two companies in a row without full stops: each form takes only its own name.
    assert persons("A Fodor Bt és Gulyás Kkt ajánlata.") == ["Fodor", "Gulyás"]


def test_sole_traders_are_masked_without_a_lexicon_match() -> None:
    text = "A fuvarozást Ördögh Tihamér e.v. végzi."
    assert persons(text) == ["Ördögh Tihamér"]
    assert scores(text) == [SCORE_WEAK]
    assert scores("Számlát ad Horváth Emese e.v.") == [SCORE_FULL_NAME]
    # Unknown surname: only with a given name, never alone, for other forms.
    assert persons("A Zsombok Tamás Bt. ajánlata.") == ["Zsombok Tamás"]
    assert persons("A Zsombok Bt. ajánlata.") == []


# --- False positives: surnames that are ordinary words -----------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "A Pannon Csempe Kft. és a Duna Lámpa Bt. közös standdal érkezik.",
        "A Magyar Kalapács Zrt. beszállítója a Fekete Kavics Kft.",
        "A Kék Madár Nyrt. és az Arany Kulcs Zrt. közleménye.",
        "Ajánlatot kértünk a Fekete Kft.-től, a Magyar Kft.-től és a Szép Zrt.-től.",
        "A Kis Csiga Kft. és a Nagy Ugrás Bt. játszóházat üzemeltet.",
        "Pékáru: Budai Pékség Bt., kerámia: Pécsi Kerámia Kft., bútor: Lengyel Bútor Kft.",
        "A Vörös Rózsa Kft. virágküldő szolgálat.",
        "A Fekete és Fehér Kft. grafikai stúdió.",
        "A Napfény Nonprofit Kft. és az Ezüstnyír Kht. pályázata.",
        "Szerintük a bt.-k és kft.-k könyvelése drágább lett.",
        "A Mókusdomb Tanácsadó Bt. egyéni vállalkozókat segít.",
        "Tisztelt Arany Kulcs Zrt.! A falu kovácsa is ott árul.",
        "a kovács bt. lezárta az évet",  # lower case: left to the NER and the LLM
    ],
)
def test_hard_negatives(text: str) -> None:
    assert persons(text) == []


def test_common_word_surnames_need_person_evidence() -> None:
    # A given name, a family connector or a partnership form is evidence; a brand word isn't.
    assert persons("A Fekete Kft. ajánlata.") == []
    assert persons("A Fekete Anna Kft. ajánlata.") == ["Fekete Anna"]
    assert persons("A Szabó és Fiai Kkt. ajánlata.") == ["Szabó"]
    assert persons("A Kis Bt. ajánlata.") == ["Kis"]
    assert scores("A Kis Bt. ajánlata.") == [SCORE_WEAK]
    assert persons("A Kovács Autószerviz Kft. ajánlata.") == []
    assert persons("A Mészáros Építő Kft. ajánlata.") == ["Mészáros"]


def test_runs_only_for_hungarian_text() -> None:
    detector = RuleDetector()
    text = "Invoice from Tóth és Társa Bt. attached."
    assert [s.text for s in detector.detect(text, "hu") if s.entity_type is EntityType.PERSON]
    assert not [s for s in detector.detect(text, "en") if s.entity_type is EntityType.PERSON]


# --- Resolution and placeholders ---------------------------------------------------------


def _org(text: str, value: str, start: int = 0) -> Span:
    at = text.index(value, start)
    return Span(at, at + len(value), EntityType.ORGANIZATION, value, 0.99, "ner")


def test_person_nested_in_a_kept_organization_wins_and_the_rest_stays_kept() -> None:
    text = "A könyvelést a Tóth és Társa Bt. végzi."
    spans = [*RuleDetector().detect(text, "hu"), _org(text, "Tóth és Társa Bt.")]
    resolved = resolve_spans(text, spans, detector_order=["rules", "ner"])
    assert [(s.entity_type, s.text) for s in resolved] == [
        (EntityType.PERSON, "Tóth"),
        (EntityType.ORGANIZATION, "és Társa Bt"),  # the resolver trims a remainder's dot
    ]
    to_mask = [s for s in resolved if s.entity_type is not EntityType.ORGANIZATION]
    masked = Vault(b"k" * 32).session().mask(text, to_mask, language="hu")
    assert "Tóth" not in masked
    assert PLACEHOLDER_RE.search(masked)
    assert masked.endswith(" és Társa Bt. végzi.")


def test_one_placeholder_for_the_person_and_their_sole_trader_name() -> None:
    text = "Kovács János szerint kész. Kovács János e.v.-nek utaltunk, Kovács János e.v. számláz."
    first = text.index("Kovács János")
    ner = Span(first, first + 12, EntityType.PERSON, "Kovács János", 0.99, "ner")
    resolved = resolve_spans(text, [*RuleDetector().detect(text, "hu"), ner])
    assert [s.text for s in resolved if s.entity_type is EntityType.PERSON] == ["Kovács János"] * 3
    masked = Vault(b"k" * 32).session().mask(text, resolved, language="hu")
    assert "Kovács" not in masked
    assert len({m.group(0) for m in PLACEHOLDER_RE.finditer(masked)}) == 1
    assert " e.v.-nek utaltunk" in masked


# --- The fixture -------------------------------------------------------------------------


def _builder() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "build_company_names", FIXTURES / "build_company_names.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_committed_fixture_matches_the_builder() -> None:
    builder = _builder()
    for name, build in builder.OUTPUTS.items():
        expected = "\n".join(dump_document(d) for d in build()) + "\n"
        assert (FIXTURES / name).read_text(encoding="utf-8") == expected, (
            f"{name} is stale: run `uv run python eval/fixtures/build_company_names.py`"
        )


def test_fixture_coverage() -> None:
    docs = load_fixtures(COMPANY_FIXTURE)
    assert len(docs) >= 40
    assert {d.language for d in docs} == {"hu"}
    negatives = [d for d in docs if "hard-negative" in d.meta["tags"]]
    assert len(negatives) >= 10
    assert all(s.entity_type is not EntityType.PERSON for d in negatives for s in d.spans)
    tags = {t for d in docs for t in d.meta["tags"]}
    for form in ("e.v.", "ev.", "egyéni vállalkozó", "Bt.", "Bt", "Kkt.", "Kft.", "Zrt."):
        assert form in tags
    for form in ("Nyrt.", "Kht.", "Nonprofit Kft.", "inflected", "consistency"):
        assert form in tags
    for doc in docs:  # every listed company occurs in its document
        assert all(c["name"] in doc.text for c in doc.meta["companies"])


def test_rules_meet_the_targets_on_the_fixture() -> None:
    report = _builder().measure(["rules"])
    assert report["person_occurrences"] >= 50
    assert report["plain_company_occurrences"] >= 25
    assert report["person_leak_rate"] <= 0.05
    assert report["plain_company_over_masking_rate"] <= 0.05


def test_company_report_counts_partial_cover_as_a_leak() -> None:
    builder = _builder()
    doc = load_fixtures(COMPANY_FIXTURE)[0]  # "Horváth Emese e.v." twice
    gold = [s for s in doc.spans if s.entity_type is EntityType.PERSON]
    half = SimpleNamespace(start=gold[0].start, end=gold[0].start + 7)  # "Horváth" only
    full = SimpleNamespace(start=gold[1].start, end=gold[1].end)
    result = SimpleNamespace(document=doc, masked_spans=[half, full])
    report = builder.company_report([result])
    assert (report["person_occurrences"], report["person_leaked"]) == (2, 1)


def test_eval_accepts_fixture_paths_as_arguments(capsys: pytest.CaptureFixture[str]) -> None:
    assert eval_main([str(COMPANY_FIXTURE), "--detectors", "rules"]) == 0
    assert "PERSON" in capsys.readouterr().out
