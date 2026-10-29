"""Fuzzy matching of OCR'd values to session values (LAB-1156). All names are fictional."""

from __future__ import annotations

import datetime as dt

import pytest

from pii_guard.types import EntityType
from pii_guard.visual.fuzzy import (
    ACCEPT,
    Candidate,
    fold,
    match_value,
    name_tokens,
    parse_date,
    similarity,
)

P = EntityType.PERSON
ID = EntityType.ID_DOCUMENT


def person(value: str, placeholder: str = "[[PERSON_aaaaaa]]") -> Candidate:
    return Candidate(placeholder, P, value)


@pytest.mark.parametrize(
    ("card", "text"),
    [
        ("FIKTÍV MÁRIA", "Fiktív Mária"),  # ALL CAPS
        ("FIKTIV MARIA", "Fiktív Mária"),  # accents lost
        ("FIKTIV<<MARIA", "Fiktív Mária"),  # MRZ notation
        ("MARIA FIKTIV", "Fiktív Mária"),  # given-name first
        ("MUSTERMANN ERIKA", "Erika Mustermann"),  # surname field first on the card
        ("F1KTIV MAR1A", "Fiktív Mária"),  # 1 / i
        ("P0LDA GAB0R", "Polda Gábor"),  # 0 / o
        ("llse Platzhalter", "Ilse Platzhalter"),  # l / I: one stroke in most fonts
        ("Ilse PlatzhaIter", "Ilse Platzhalter"),  # small l read as capital I
        ("Erika Mustcrmann", "Erika Mustermann"),  # small e / c
        ("Lvcas Bauer", "Lucas Bauer"),  # small u / v
        ("PÉLDA GÁBOR", "Példa Gábor István"),  # the card leaves out a middle name (partial)
    ],
)
def test_the_same_person_is_matched(card: str, text: str) -> None:
    found = match_value(card, P, [person(text)])
    assert found.accepted, (card, text, found)
    assert found.confidence >= ACCEPT


@pytest.mark.parametrize(
    ("card", "text"),
    [
        ("KOVÁCS HANNA", "Kovács Anna"),
        ("TESZT ELEMÉR", "Teszt Elek"),
        ("MINTA PETRA", "Minta Péter"),
        ("MUSTERMONN ERIKA", "Erika Mustermann"),  # one real letter in a long surname
        ("FIKTÍV MÁRTA", "Fiktív Mária"),
        ("PLACEHOLDAR JANE", "Jane Placeholder"),
        ("EDITH FICTIONOL", "Edith Fictional"),
    ],
)
def test_near_namesakes_are_never_accepted(card: str, text: str) -> None:
    found = match_value(card, P, [person(text)])
    assert not found.accepted, (card, text, found)


@pytest.mark.parametrize(
    ("card", "text"),
    [
        # LAB-1211: two letters OCR may read for one another are still two letters.
        ("KOVÁCS ELIA", "Kovács Ella"),  # capital I is not a capital L
        ("HEIL ANNA", "Hell Anna"),
        ("Delia Nagy", "Della Nagy"),  # a dotted i is not an l
        ("Kovács Elia", "Kovács Ella"),
        ("Heil Anna", "HELL ANNA"),  # the session's capitals are compared as printed
        ("ELLA KOVÁCS", "Kovács Elia"),
        # LAB-1211: tokens the session's name does not have, or one token of a longer name.
        ("KOVÁCS ANNA ZSÓFIA", "Kovács Anna"),  # maybe another Anna Kovács
        ("PÉLDA GÁBOR ISTVÁN", "Példa Gábor"),
        ("ANNA", "Kovács Anna"),
        ("KOVÁCS", "Kovács Anna"),
    ],
)
def test_confusable_letters_and_extra_tokens_are_uncertain(card: str, text: str) -> None:
    found = match_value(card, P, [person(text)])
    assert found.status == "uncertain", (card, text, found)
    assert found.confidence < ACCEPT


def test_close_but_not_accepted_is_uncertain_not_none() -> None:
    found = match_value("KOVÁCS HANNA", P, [person("Kovács Anna")])
    assert found.status == "uncertain"
    assert found.candidate is not None and 0.6 <= found.confidence < ACCEPT


def test_two_people_sharing_a_surname_make_a_surname_alone_ambiguous() -> None:
    candidates = [person("Kovács Anna", "[[PERSON_a]]"), person("Kovács Péter", "[[PERSON_b]]")]
    assert match_value("KOVÁCS", P, candidates).status == "uncertain"
    # One Kovács in the session is still not enough: a lone surname is never accepted (the
    # card's surname and given-name fields are read together before they are matched).
    assert match_value("KOVÁCS", P, candidates[:1]).status == "uncertain"
    assert match_value("KOVÁCS ANNA", P, candidates).accepted


def test_the_better_of_two_close_candidates_wins_when_clearly_better() -> None:
    candidates = [person("Fiktív Mária", "[[PERSON_a]]"), person("Fiktív Márta", "[[PERSON_b]]")]
    found = match_value("FIKTÍV MÁRIA", P, candidates)
    assert found.accepted and found.candidate is not None
    assert found.candidate.placeholder == "[[PERSON_a]]"


def test_casing_variants_of_one_value_are_not_rivals() -> None:
    candidates = [person("Fiktív Mária", "[[PERSON_a]]"), person("FIKTÍV MÁRIA", "[[PERSON_b]]")]
    assert match_value("FIKTIV MARIA", P, candidates).accepted


def test_no_candidate_or_another_type_is_none() -> None:
    assert match_value("FIKTÍV MÁRIA", P, []).status == "none"
    other = Candidate("[[ADDRESS_a]]", EntityType.ADDRESS, "Fiktív Mária utca")
    assert match_value("FIKTÍV MÁRIA", P, [other]).status == "none"


def test_identifiers_allow_ocr_confusions_only() -> None:
    doc = Candidate("[[ID_DOCUMENT_a]]", ID, "ID8001464")
    assert match_value("1D8001464", ID, [doc]).accepted  # I read as 1
    assert match_value("ID 800 1464", ID, [doc]).accepted  # spaces
    assert not match_value("ID8004464", ID, [doc]).accepted  # another document
    assert not match_value("ID800146", ID, [doc]).accepted  # a digit lost: not a guess
    assert not match_value("LD8001464", ID, [doc]).accepted  # a capital L is not an I
    assert match_value(
        "1D8001464", ID, [doc, Candidate("[[ID_DOCUMENT_b]]", ID, "LD8001464")]
    ).accepted
    # Identifier types match each other (a TAJ number found as an ID_DOCUMENT on a card).
    taj = Candidate("[[NATIONAL_ID_HU_TAJ_a]]", EntityType.NATIONAL_ID_HU_TAJ, "123 456 788")
    assert match_value("123456788", ID, [taj]).accepted


@pytest.mark.parametrize(
    ("entity_type", "card", "text"),
    [
        # LAB-1211: one letter read for another is another document (letter <-> letter).
        (ID, "XJXK89KU4", "XJXK89KV4"),
        (ID, "EZW4P8T75", "CZW4P8T75"),
        (EntityType.VEHICLE_PLATE, "HU-ABE-123", "HU-ABC-123"),
        (ID, "LD8001464", "ID8001464"),
    ],
)
def test_identifiers_one_letter_apart_are_uncertain(
    entity_type: EntityType, card: str, text: str
) -> None:
    found = match_value(card, entity_type, [Candidate("[[X_a]]", entity_type, text)])
    assert found.status == "uncertain", (card, text, found)


def test_identifiers_keep_letter_digit_confusions() -> None:
    doc = Candidate("[[ID_DOCUMENT_a]]", ID, "AB123456")
    for card in ("AB1234S6", "ABI23456", "A8123456", "AB 12 34 56"):
        assert match_value(card, ID, [doc]).accepted, card


def test_emails_and_phones_ignore_ocr_spaces() -> None:
    mail = Candidate("[[EMAIL_a]]", EntityType.EMAIL, "marton.tesztes@example.net")
    assert match_value("marton .tesztes@example.net", EntityType.EMAIL, [mail]).accepted


def test_dates_match_whatever_their_format() -> None:
    born = Candidate("[[DATE_OF_BIRTH_a]]", EntityType.DATE_OF_BIRTH, "1959-01-02")
    for written in ("1959.01.02.", "02.01.1959", "02 JAN 1959", "1959. jan. 2."):
        assert similarity(written, EntityType.DATE_OF_BIRTH, born) == 1.0, written
    assert similarity("1959.01.05.", EntityType.DATE_OF_BIRTH, born) == 0.0


def test_parse_date_and_mrz_dates() -> None:
    assert parse_date("19 AUG 1995") == dt.date(1995, 8, 19)
    assert parse_date("31.03.2025") == dt.date(2025, 3, 31)
    assert parse_date("590102", yymmdd=True) == dt.date(1959, 1, 2)
    assert parse_date("310630", yymmdd=True) == dt.date(2031, 6, 30)
    assert parse_date("no date here") is None
    assert parse_date("31.02.2025") is None


def test_fold_and_tokens() -> None:
    assert fold("FIKTÍV  Mária") == "fiktiv maria"
    assert name_tokens("FIKTIV<<MARIA<<<") == ["fiktiv", "maria"]
    assert name_tokens("Fiktív, Mária") == ["fiktiv", "maria"]


def test_reprs_never_show_values() -> None:
    assert "Mária" not in repr(person("Fiktív Mária"))
    assert "Mária" not in repr(match_value("FIKTÍV MÁRIA", P, [person("Fiktív Mária")]))


def test_the_eval_keeps_its_ocr_confusable_namesakes() -> None:
    # LAB-1211: the LAB-1156 eval scores false merges against these; regenerating the file
    # with --write-namesakes alone would silently drop them.
    import json
    from pathlib import Path

    path = Path(__file__).parents[2] / "eval" / "fixtures" / "visual" / "near-namesakes.json"
    items = {
        (i["document"], i["key"]): i["namesakes"] for i in json.loads(path.read_text())["items"]
    }
    assert "Iise Platzhalter" in items[("de-member_card-front", "name")]
    assert "XJXK86KU4" in items[("de-id_card-front", "doc")]
    assert "LD8001464" in items[("en-id_card-front", "doc")]
    for (_doc, key), names in items.items():
        if key == "name":
            assert len(names) >= 2
