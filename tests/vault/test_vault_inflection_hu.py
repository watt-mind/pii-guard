"""Hungarian stem changes: one vault entry per lemma, suffixes outside, re-inflecting unmask.

All names are fictional (ADR 0005).
"""

from __future__ import annotations

import re

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from vault_helpers import TEST_KEY, span_of

from pii_guard.languages.hu.inflection import HungarianSuffixMatcher
from pii_guard.types import EntityType, Span
from pii_guard.vault import (
    PLACEHOLDER_RE,
    StreamUnmasker,
    Vault,
    VaultSession,
    inflection_for,
)
from pii_guard.vault.inflection import MAX_SUFFIX_LENGTH, Split, following_suffix, restore
from pii_guard.vault.placeholders import derive_id

PERSON = EntityType.PERSON
REPRO = (
    "Próba Zsuzsannának küldtük a levelet. Próba Zsuzsanna holnap válaszol, "
    "Próba Zsuzsannát hívjuk."
)


def base_span() -> Span:
    """The bare "Próba Zsuzsanna" in REPRO (the other two forms are inflected)."""
    start = REPRO.index("Próba Zsuzsanna ")
    return Span(start, start + 15, PERSON, "Próba Zsuzsanna", 1.0, "test")


def placeholders(masked: str) -> list[str]:
    return [m.group(0) for m in PLACEHOLDER_RE.finditer(masked)]


def stream(session: VaultSession, text: str, cuts: list[int]) -> str:
    unmasker = StreamUnmasker(session)
    out, last = [], 0
    for cut in [*cuts, len(text)]:
        out.append(unmasker.feed(text[last:cut]))
        last = cut
    out.append(unmasker.flush())
    return "".join(out)


# --- the ticket's repro ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "detected", ["Próba Zsuzsanna", "Próba Zsuzsannának", "Próba Zsuzsannát", "all"]
)
def test_repro_one_placeholder_with_suffixes_outside(vault: Vault, detected: str) -> None:
    session = vault.session()
    forms = ["Próba Zsuzsannának", "Próba Zsuzsanna", "Próba Zsuzsannát"]
    chosen = forms if detected == "all" else [detected]
    spans = [span_of(REPRO, f + " ", PERSON) for f in chosen]
    spans = [Span(s.start, s.end - 1, PERSON, s.text[:-1], 1.0, "test") for s in spans]
    masked = session.mask(REPRO, spans)
    (placeholder,) = set(placeholders(masked))
    assert masked == (
        f"{placeholder}nak küldtük a levelet. {placeholder} holnap válaszol, {placeholder}t hívjuk."
    )
    assert session.unmask(masked) == REPRO


def test_placeholder_id_is_keyed_on_the_lemma(vault: Vault) -> None:
    # Whichever form the detector returned, the id is the HMAC of the lemma.
    for detected in ("Próba Zsuzsanna", "Próba Zsuzsannának", "PRÓBA ZSUZSANNÁNAK"):
        session = vault.session()
        text = f"{detected}."
        masked = session.mask(text, [span_of(text, detected, PERSON)])
        expected = derive_id(TEST_KEY, session.session_id, PERSON, "próba zsuzsanna")
        assert placeholders(masked) == [f"[[PERSON_{expected}]]"]
        assert session.unmask(masked) == text


@pytest.mark.parametrize(
    ("text", "detected", "entity_type", "suffixes"),
    [
        (
            "Minta Kende ír. Minta Kendének, Minta Kendét, Minta Kendével.",
            "Minta Kende",
            "PERSON",
            ["nek", "t", "vel"],
        ),
        ("Kovács jön, Kováccsal megyünk, Kovácsnál alszunk.", "Kovács", "PERSON", ["al", "nál"]),
        ("Teszt Elek, Teszt Elekkel, Teszt Eleknek.", "Teszt Elek", "PERSON", ["kel", "nek"]),
        ("Teszt Gergely és Teszt Gergellyel.", "Teszt Gergely", "PERSON", ["el"]),
        ("Az ABC-123 rendszám, az ABC-123-nak.", "ABC-123", "VEHICLE_PLATE", ["-nak"]),
        ("Minta Anna és Minta Annának.", "Minta Annának", "PERSON", ["nak"]),
    ],
)
def test_forms_share_one_placeholder(
    vault: Vault, text: str, detected: str, entity_type: str, suffixes: list[str]
) -> None:
    session = vault.session()
    masked = session.mask(text, [span_of(text, detected, entity_type)])
    assert len(set(placeholders(masked))) == 1
    stem = detected.split()[-1][:4].casefold()
    assert stem not in PLACEHOLDER_RE.sub("", masked).casefold()
    for suffix in suffixes:
        assert f"]]{suffix}" in masked
    assert session.unmask(masked) == text


@pytest.mark.parametrize(
    "detected", ["Minta Kendének", "Minta Kendét", "Kováccsal", "Teszt Elekkel", "ABC-123-nak"]
)
def test_inflected_detection_is_narrowed_or_aliased(vault: Vault, detected: str) -> None:
    # Whatever form the detector returns, no other form of the value is left in clear.
    texts = {
        "Minta Kendének": "Minta Kende, Minta Kendének, Minta Kendét.",
        "Minta Kendét": "Minta Kendének, Minta Kendét.",
        "Kováccsal": "Kovács, Kováccsal, Kovácsnak.",
        "Teszt Elekkel": "Teszt Eleknek, Teszt Elekkel.",
        "ABC-123-nak": "ABC-123, ABC-123-nak.",
    }
    text = texts[detected]
    entity_type = EntityType.VEHICLE_PLATE if detected.startswith("ABC") else PERSON
    session = vault.session()
    masked = session.mask(text, [span_of(text, detected, entity_type)])
    assert len(set(placeholders(masked))) == 1
    assert len(placeholders(masked)) == text.count(",") + 1
    assert session.unmask(masked) == text


def test_detector_stem_inside_a_word_is_keyed_on_the_lemma(vault: Vault) -> None:
    # LlmDetector.align returns the lengthened stem "Próba Zsuzsanná" before "nak".
    session = vault.session()
    masked = session.mask(REPRO, [span_of(REPRO, "Próba Zsuzsanná", PERSON)])
    assert len(set(placeholders(masked))) == 1
    assert len(placeholders(masked)) == 3
    assert session.unmask(masked) == REPRO
    assert session.unmask(f"{placeholders(masked)[0]}.") == "Próba Zsuzsanna."


# --- ambiguous splits: recall first, never a guess -------------------------------------------


def test_names_that_look_inflected_are_not_split(vault: Vault) -> None:
    # "Kornél" is not "Kor" + "nél", even though "kor" occurs; "Zoltán" is not "Zolta" + "n".
    session = vault.session()
    text = "Kornél kor szerint, Zoltán és Zoltánnak."
    masked = session.mask(text, [span_of(text, "Kornél", PERSON), span_of(text, "Zoltán", PERSON)])
    assert " kor szerint" in masked
    kornel, zoltan, zoltan_dat = placeholders(masked)
    assert zoltan == zoltan_dat
    assert masked.endswith(f"{zoltan}nak.")
    assert session.unmask(f"{kornel} és {zoltan}nak") == "Kornél és Zoltánnak"


def test_repeated_detections_of_one_form_do_not_confirm_a_split(vault: Vault) -> None:
    session = vault.session()
    text = "Teszt Zoltán írt. Teszt Zoltán válaszolt."
    spans = [span_of(text, "Teszt Zoltán", PERSON, nth=i) for i in range(2)]
    masked = session.mask(text, spans)
    assert "]]n " not in masked
    assert len(set(placeholders(masked))) == 1


def test_two_different_forms_confirm_their_common_lemma(vault: Vault) -> None:
    session = vault.session()
    text = "Teszt Eleket hívtuk, Teszt Eleknek írtunk."
    spans = [span_of(text, "Teszt Eleket", PERSON), span_of(text, "Teszt Eleknek", PERSON)]
    masked = session.mask(text, spans)
    (placeholder,) = set(placeholders(masked))
    assert masked == f"{placeholder}et hívtuk, {placeholder}nek írtunk."


def test_weak_split_confirmed_by_a_bare_occurrence(vault: Vault) -> None:
    session = vault.session()
    text = "Zoltánt hívtuk, Zoltán felvette."
    masked = session.mask(text, [span_of(text, "Zoltánt", PERSON)])
    (placeholder,) = set(placeholders(masked))
    assert masked == f"{placeholder}t hívtuk, {placeholder} felvette."
    assert session.unmask(masked) == text


def test_unconfirmed_weak_split_masks_the_whole_word_and_its_lemma_forms(vault: Vault) -> None:
    session = vault.session()
    text = "Minta Kendét hívtuk, Minta Kendének írtunk."
    masked = session.mask(text, [span_of(text, "Minta Kendét", PERSON)])
    (placeholder,) = set(placeholders(masked))
    assert masked == f"{placeholder} hívtuk, {placeholder}nek írtunk."
    assert session.unmask(masked) == text


def test_split_never_masks_less_than_the_unsplit_value(vault: Vault) -> None:
    # The detected surface itself stays an occurrence pattern of the lemma's entry.
    session = vault.session()
    text = "Próba Zsuzsannának. Később: Próba Zsuzsannának-e?"
    masked = session.mask(text, [span_of(text, "Próba Zsuzsannának", PERSON)])
    assert "Zsuzsann" not in masked


def test_session_confirms_lemma_for_later_requests(vault: Vault) -> None:
    session = vault.session()
    first = session.mask("Minta Kende.", [span_of("Minta Kende.", "Minta Kende", PERSON)])
    text = "Minta Kendét hívtuk."
    second = session.mask(text, [span_of(text, "Minta Kendét", PERSON)])
    assert second == f"{placeholders(first)[0]}t hívtuk."


# --- unmask re-inflects model-authored suffixes ---------------------------------------------


@pytest.mark.parametrize(
    ("lemma", "answer", "expected"),
    [
        ("Próba Zsuzsanna", "{p}nak", "Próba Zsuzsannának"),
        ("Próba Zsuzsanna", "{p}val és {p}ról", "Próba Zsuzsannával és Próba Zsuzsannáról"),
        ("Próba Zsuzsanna", "{p}ként", "Próba Zsuzsannaként"),
        ("Próba Zsuzsanna", "{p}-nak", "Próba Zsuzsanna-nak"),
        ("Minta Kende", "{p}t és {p}nek", "Minta Kendét és Minta Kendének"),
        ("MINTA KENDE", "{p}nek", "MINTA KENDÉnek"),
        ("Kovács", "{p}val, {p}al", "Kováccsal, Kováccsal"),
        ("Kovács", "{p}é", "Kovácsé"),
        ("Teszt Elek", "{p}vel, {p}nek", "Teszt Elekkel, Teszt Eleknek"),
        ("Teszt Kiss", "{p}vel", "Teszt Kissel"),
        ("Teszt Elek", "{p}xyzxyzxyzxyzxyz", "Teszt Elekxyzxyzxyzxyzxyz"),
    ],
)
def test_unmask_reinflects_model_suffixes(
    vault: Vault, lemma: str, answer: str, expected: str
) -> None:
    session = vault.session()
    text = f"{lemma}."
    (placeholder,) = placeholders(session.mask(text, [span_of(text, lemma, PERSON)]))
    model_answer = answer.format(p=placeholder)
    assert session.unmask(model_answer) == expected
    for cut in range(len(model_answer) + 1):
        assert stream(session, model_answer, [cut]) == expected


def test_unmask_prefers_the_form_seen_in_the_input(vault: Vault) -> None:
    # "Annaval" (no lengthening) was in the input: it round-trips as written.
    session = vault.session()
    text = "Minta Anna és Minta Annaval."
    masked = session.mask(text, [span_of(text, "Minta Anna", PERSON)])
    assert session.unmask(masked) == text
    placeholder = placeholders(masked)[0]
    assert session.unmask(f"{placeholder}nak") == "Minta Annának"


def test_streaming_unmask_matches_at_every_split(vault: Vault) -> None:
    session = vault.session()
    masked = session.mask(REPRO, [base_span()])
    answer = masked + " " + placeholders(masked)[0] + "val"
    expected = session.unmask(answer)
    assert expected.endswith("Próba Zsuzsannával")
    for cut in range(len(answer) + 1):
        assert stream(session, answer, [cut]) == expected
    assert stream(session, answer, list(range(1, len(answer)))) == expected


def test_stream_releases_long_runs_after_a_placeholder(vault: Vault) -> None:
    session = vault.session()
    (placeholder,) = placeholders(session.mask("Elek.", [span_of("Elek.", "Elek", PERSON)]))
    unmasker = StreamUnmasker(session)
    assert unmasker.feed(placeholder + "nak") == ""
    assert unmasker.feed(" ") == "Eleknek "  # re-harmonized (LAB-1152)
    assert unmasker.feed(placeholder + "x" * (MAX_SUFFIX_LENGTH + 1)) == (
        "Elek" + "x" * (MAX_SUFFIX_LENGTH + 1)
    )


# --- matcher API ----------------------------------------------------------------------------


def test_splits_and_variants() -> None:
    hu = inflection_for("hu")
    assert isinstance(hu, HungarianSuffixMatcher)
    strong = hu.splits("Próba Zsuzsannának", PERSON)[0]
    assert strong == Split("Próba Zsuzsanna", "Próba Zsuzsanná", "nak", strong=True)
    assert "nak" not in repr(strong) and "Zsuzs" not in repr(strong)
    assert Split("Kovács", "Kováccs", "al") in hu.splits("Kováccsal", PERSON)
    assert Split("Elek", "Elek", "kel") in hu.splits("Elekkel", PERSON)
    assert Split("ABC-123", "ABC-123", "-nak") in hu.splits("ABC-123-nak", PERSON)
    # Vowel harmony: "-nek" after a back-vowel "a" is not a strong reading.
    assert not any(s.strong for s in hu.splits("Zsuzsannánek", PERSON))
    assert hu.splits("teszt@example.com", EntityType.EMAIL) == []
    assert hu.variant_stems("Kovács", PERSON)[0][0] == "Kováccs"
    assert hu.variant_stems("Minta Kende", PERSON)[0][0] == "Minta Kendé"
    assert hu.variant_stems("+36 30 123 4567", EntityType.PHONE) == []
    assert inflection_for("en").suffix_pattern("Smith", PERSON)  # unchanged


def test_fallbacks_for_matchers_without_stem_methods() -> None:
    class Plain:
        def suffix_pattern(self, value: str, entity_type: EntityType) -> str:
            return ""

    assert restore(Plain(), "Anna", "nak", PERSON) == "Annanak"
    assert restore(inflection_for("en"), "Smith", "s", PERSON) == "Smiths"
    assert following_suffix("x[[A]]-nak!", 6) == "-nak"
    assert following_suffix("x[[A]]-!", 6) == ""
    assert following_suffix("x" * 20, 0) == ""


def test_mask_with_report_offsets(vault: Vault) -> None:
    session = vault.session()
    result = session.mask_with_report(REPRO, [base_span()])
    assert result.text == session.mask(REPRO, [])
    stems = [REPRO[start:end] for start, end, _ in result.replacements]
    assert stems == ["Próba Zsuzsanná", "Próba Zsuzsanna", "Próba Zsuzsanná"]
    assert "Zsuzs" not in repr(result)


# --- property: every form of a generated name ----------------------------------------------

# name -> some of its surface forms
NAMES: dict[str, list[str]] = {
    "Próba Zsuzsanna": [
        "Próba Zsuzsanna",
        "Próba Zsuzsannának",
        "Próba Zsuzsannát",
        "Próba Zsuzsannával",
        "Próba Zsuzsannáról",
        "Próba Zsuzsannaként",
    ],
    "Minta Kende": ["Minta Kende", "Minta Kendének", "Minta Kendét", "Minta Kendéhez"],
    "Teszt Elek": ["Teszt Elek", "Teszt Eleknek", "Teszt Eleket", "Teszt Elekkel"],
    "Minta Szabolcs": ["Minta Szabolcs", "Minta Szabolcsnak", "Minta Szabolccsal"],
    "Teszt Gergely": ["Teszt Gergely", "Teszt Gergelynek", "Teszt Gergellyel"],
}
FORMS = [(name, form) for name, forms in NAMES.items() for form in forms]
FILLER = st.text(alphabet=" .,;:!?\n()", min_size=1, max_size=6)
# The given name's first letters identify the person in any form.
MARKERS = {name: re.escape(name.split()[1][:5]) for name in NAMES}


@st.composite
def hu_documents(draw: st.DrawFn) -> tuple[str, list[tuple[str, Span]]]:
    picked = draw(st.lists(st.sampled_from(FORMS), min_size=1, max_size=8))
    text, spans = "", []
    for name, form in picked:
        text += draw(FILLER)
        spans.append((name, Span(len(text), len(text) + len(form), PERSON, form, 1.0, "test")))
        text += form
    return text + draw(FILLER), spans


@given(doc=hu_documents(), keep=st.lists(st.booleans(), min_size=8, max_size=8))
@settings(max_examples=300, deadline=None)
def test_property_hu_forms_round_trip_and_share_a_placeholder(
    doc: tuple[str, list[tuple[str, Span]]], keep: list[bool]
) -> None:
    text, spans = doc
    # The detector reports some occurrences (at least one per name), in any form.
    detected: list[Span] = []
    seen: set[str] = set()
    for index, (name, span) in enumerate(spans):
        if keep[index] or name not in seen:
            detected.append(span)
            seen.add(name)
    session = Vault(TEST_KEY).session()
    result = session.mask_with_report(text, detected)
    assert session.unmask(result.text) == text
    for name in seen:
        assert not re.search(MARKERS[name], PLACEHOLDER_RE.sub("", result.text))
    by_name: dict[str, set[str]] = {}
    for name, span in spans:
        hits = {p for s, e, p in result.replacements if s < span.end and span.start < e}
        assert len(hits) == 1
        by_name.setdefault(name, set()).update(hits)
    assert all(len(ids) == 1 for ids in by_name.values())
    assert len(set().union(*by_name.values())) == len(by_name)


# --- stacked suffixes: -é / -ék / -éi, then a case ending (LAB-1337) -------------------------


@pytest.mark.parametrize(
    ("value", "stem", "chain"),
    [
        ("Kerekes Ottó", "Ottó", "éknál"),  # the ticket's repro: family + adessive
        ("Kerekes Ottó", "Ottó", "ékkal"),  # instrumental doubles the k
        ("Kerekes Ottó", "Ottó", "ékat"),  # accusative takes a linking vowel
        ("Kerekes Ottó", "Ottó", "éval"),  # possessive + instrumental keeps the v
        ("Kerekes Ottó", "Ottó", "éké"),  # the Ottós' (possessive of the family)
        ("Teszt Hajna", "Hajná", "éknál"),  # lengthened stem, then the chain
        ("Teszt Hajna", "Hajná", "éit"),
        ("Gyakorló Tihamér", "Tihamér", "éknek"),  # front harmony
        ("Gyakorló Tihamér", "Tihamér", "éitől"),
        ("Minta Kende", "Kendé", "éktől"),
        ("Kovács", "Kovács", "éknál"),  # a digraph-final value keeps its stem here
    ],
)
def test_stacked_suffixes_are_masked_and_round_trip(
    vault: Vault, value: str, stem: str, chain: str
) -> None:
    surface = value.rsplit(" ", 1)[0] + " " + stem if " " in value else stem
    text = f"{value} írt. Tegnap {surface}{chain} voltunk."
    session = vault.session()
    masked = session.mask(text, [span_of(text, value, PERSON)])
    (placeholder,) = set(placeholders(masked))
    assert masked == f"{placeholder} írt. Tegnap {placeholder}{chain} voltunk."
    assert session.unmask(masked) == text


def test_stacked_suffix_after_an_inflected_detection(vault: Vault) -> None:
    # The ticket's repro: the detector labelled the first, inflected occurrence. On its own
    # the vault keeps that span whole (the detectors' suffix trim ends it at the stem first);
    # the stacked form is still read onto the same lemma.
    text = "Kerekes Ottótól jött, Kerekes Ottóéknál lakik."
    session = vault.session()
    masked = session.mask(text, [span_of(text, "Kerekes Ottótól", PERSON)])
    (placeholder,) = set(placeholders(masked))
    assert masked == f"{placeholder} jött, {placeholder}éknál lakik."
    assert session.unmask(masked) == text


@pytest.mark.parametrize(
    ("lemma", "suffix", "expected"),
    [
        ("Teszt Hajna", "éknak", "Teszt Hajnáéknak"),  # a chain the model added
        ("Teszt Hajna", "áéknak", "Teszt Hajnáéknak"),  # ... with the long vowel written
        ("Kerekes Ottó", "éknál", "Kerekes Ottóéknál"),
        ("Minta Kende", "éktől", "Minta Kendééktől"),
        ("Minta Kende", "ének", "Minta Kendének"),  # still the long vowel + dative
        ("Minta Kende", "ék", "Minta Kendéék"),
    ],
)
def test_restore_stacked(lemma: str, suffix: str, expected: str) -> None:
    assert restore(HungarianSuffixMatcher(), lemma, suffix, PERSON) == expected


@pytest.mark.parametrize(
    ("value", "text"),
    [
        # A held value followed by letters that are not an inflection stays apart.
        ("Kerekes", "Kerekes jött, egy kerekesszék állt az ajtóban."),
        ("Bál", "Bál úr írt, Bálint is ott volt."),
        ("Kis", "Kis úr szerint a kisebb csomag jobb."),
        ("Fehér", "Fehér úr szerint a fehérje fontos."),
        ("Minta", "Minta úr a mintaképe volt mindenkinek."),
        ("Teszt Ottó", "Teszt Ottó írt; Teszt Ottóékszer nem szó."),
        ("Teszt Hajna", "Teszt Hajna írt; Teszt Hajnáékszám nem szó."),
        ("Teszt Ottó", "Teszt Ottó írt; Teszt Ottóénekes nem szó."),
    ],
)
def test_stacked_suffixes_do_not_over_mask(vault: Vault, value: str, text: str) -> None:
    session = vault.session()
    masked = session.mask(text, [span_of(text, value, PERSON)])
    assert len(placeholders(masked)) == 1
    assert session.unmask(masked) == text


# The LAB-1337 probe: 10 fictional given names x 13 chains x 5 surnames (650 cases), forms
# written out from the grammar here, not from the matcher. (lemma, possessive stem, back?)
_STACKED_NAMES = [
    ("Ottó", "Ottó", True), ("Hajna", "Hajná", True), ("Tihamér", "Tihamér", False),
    ("Kende", "Kendé", False), ("Csongor", "Csongor", True), ("Emese", "Emesé", False),
    ("Bendegúz", "Bendegúz", True), ("Gyöngyi", "Gyöngyi", False), ("Huba", "Hubá", True),
    ("Ildikó", "Ildikó", True),
]  # fmt: skip
_STACKED_CHAINS = [
    ("éknál", "éknél"), ("éknak", "éknek"), ("ékhoz", "ékhez"), ("éktól", "éktől"),
    ("ékkal", "ékkel"), ("ékat", "éket"), ("ékban", "ékben"), ("éké", "éké"), ("ét", "ét"),
    ("éval", "ével"), ("énál", "énél"), ("éit", "éit"), ("éinak", "éinek"),
]  # fmt: skip


@pytest.mark.parametrize("surname", ["Kerekes", "Teszt", "Gyakorló", "Minta", "Próba"])
def test_stacked_suffix_probe(vault: Vault, surname: str) -> None:
    for lemma, stem, back in _STACKED_NAMES:
        for chains in _STACKED_CHAINS:
            chain = chains[0] if back else chains[1]
            value = f"{surname} {lemma}"
            text = f"{value} írt nekünk. Tegnap {surname} {stem}{chain} voltunk."
            session = vault.session()
            masked = session.mask(text, [span_of(text, value, PERSON)])
            (placeholder,) = set(placeholders(masked))
            assert masked.count(placeholder) == 2, text
            assert stem.casefold() not in PLACEHOLDER_RE.sub(" ", masked).casefold(), text
            assert session.unmask(masked) == text
