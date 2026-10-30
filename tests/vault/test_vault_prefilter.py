"""The occurrence prefilter and the fold memo change no output, only the cost (LAB-1277).

A gateway request re-masks the whole history against every value of the session, so the
vault skips an entry's regex scan when none of its literal needles is in the text, and
memoises each text's folded views per session. All values are fictional (ADR 0005).
"""

from __future__ import annotations

import json
import re
import sys
import unicodedata
from collections.abc import Iterator
from pathlib import Path

import pytest
from vault_helpers import TEST_KEY, span_of

import pii_guard.vault.entry as entry_module
import pii_guard.vault.session as session_module
import pii_guard.vault.vault as vault_module
from pii_guard.types import EntityType, Span
from pii_guard.vault import PLACEHOLDER_RE, Vault, VaultSession
from pii_guard.vault.fold import fold_views

FIXTURES = Path(__file__).resolve().parents[2] / "eval" / "fixtures"
ZWSP = "\u200b"
DOTLESS_I = "\u0131"  # matches "i" under re.IGNORECASE


def _fixture(name: str) -> list[tuple[str, list[Span], str]]:
    docs = []
    for line in (FIXTURES / name).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        doc = json.loads(line)
        spans: list[Span] = []
        for gold in sorted(doc["spans"], key=lambda s: (s["start"], s["end"])):
            entity_type = EntityType(gold["entity_type"])
            if entity_type.is_visual or (spans and gold["start"] < spans[-1].end):
                continue
            value = doc["text"][gold["start"] : gold["end"]]
            spans.append(Span(gold["start"], gold["end"], entity_type, value, 1.0, "gold"))
        docs.append((doc["text"], spans, doc.get("language", "hu")))
    return docs


def _turns() -> list[tuple[str, list[Span], str]]:
    """Fixture texts with gold spans, generated e-mail/phone turns, and later mentions of the
    same values in other forms (casing, NFD, zero-width, dotless i) without spans."""
    docs = _fixture("hu-smoke.jsonl") + _fixture("hu-inflection.jsonl")
    docs += _fixture("en-smoke.jsonl") + _fixture("de-smoke.jsonl")
    for i in range(12):
        email, phone = f"ugyfel{i}@example.com", f"+36 30 {100 + i:03d} {1000 + i:04d}"
        text = f"Szia! A {i}. ügyfél e-mail címe {email}, telefonja {phone}. Kérlek, válaszolj."
        spans = [span_of(text, email, "EMAIL"), span_of(text, phone, "PHONE")]
        docs.append((text, spans, "hu"))
    mentions = [(text, [], language) for text, _, language in docs[:: max(1, len(docs) // 8)]]
    mentions += [(text.upper(), [], language) for text, _, language in docs[1::9]]
    mentions += [
        (unicodedata.normalize("NFD", text), [], language) for text, _, language in docs[2::9]
    ]
    mentions += [
        (text.replace("a", f"a{ZWSP}", 3), [], language) for text, _, language in docs[3::9]
    ]
    mentions += [
        (f"K{DOTLESS_I}ss Elek és KISS ELEK írt, ugyfel3@EXAMPLE.com is.", [], "hu"),
        # Every token of the value has an i, and here a dotless one: matched all the same.
        ("Kiss Lili is.".replace("i", DOTLESS_I), [], "hu"),
        ("Visszahívás: +36301031003, illetve +36 30 104\n1004.", [], "hu"),
    ]
    kiss = "Kiss Elek és Kiss Lili levele."
    names = [span_of(kiss, "Kiss Elek", "PERSON"), span_of(kiss, "Kiss Lili", "PERSON")]
    return [(kiss, names, "hu"), *docs, *mentions]


def _canonical(texts: list[str]) -> list[str]:
    ids: dict[str, str] = {}
    return [
        PLACEHOLDER_RE.sub(lambda m: ids.setdefault(m.group(0), f"<{len(ids)}>"), text)
        for text in texts
    ]


def _session_output(*, case_sensitive: bool) -> tuple[list[str], list[str]]:
    """Three gateway-like requests over a growing history: mask, then remask, every text."""
    session = Vault(TEST_KEY, case_sensitive_placeholders=case_sensitive).session()
    turns = _turns()
    masked: list[str] = []
    for history in (turns[: len(turns) // 2], turns, turns):
        first = [session.mask(text, spans, language=lang) for text, spans, lang in history]
        masked += [
            session.mask(text, [], language=lang, remask=True)
            for text, (_, _, lang) in zip(first, history, strict=True)
        ]
    return _canonical(masked), [session.unmask(text) for text in masked]


# untraced: the whole corpus twice, 23-26 s each under the branch tracer on CI; the prefilter
# and fold memo are measured by the unit tests below (LAB-1447).
@pytest.mark.untraced
@pytest.mark.parametrize("case_sensitive", [False, True])
def test_prefilter_and_fold_memo_change_no_output(
    monkeypatch: pytest.MonkeyPatch, case_sensitive: bool
) -> None:
    with_prefilter = _session_output(case_sensitive=case_sensitive)
    monkeypatch.setattr(entry_module, "_PREFILTER", False)
    monkeypatch.setattr(session_module, "_FOLD_MEMO_CHARS", 0)
    without = _session_output(case_sensitive=case_sensitive)
    assert with_prefilter[0] == without[0]
    assert with_prefilter[1] == without[1]
    assert sum(text.count("<") for text in with_prefilter[0]) > 300  # the session masked a lot


def _scans(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    calls = [0]
    original = entry_module._occurrences

    def counting(pattern: re.Pattern[str], views: tuple) -> list[tuple[int, int]]:
        calls[0] += 1
        return original(pattern, views)

    monkeypatch.setattr(entry_module, "_occurrences", counting)
    return calls


def test_prefilter_skips_values_absent_from_the_text(monkeypatch: pytest.MonkeyPatch) -> None:
    session = Vault(TEST_KEY).session()
    texts = [
        f"Írj a ugyfel{i}@example.com címre, vagy hívd: +36 30 555 {1000 + i}." for i in range(20)
    ]
    for text in texts:
        session.mask(text, [span_of(text, f"ugyfel{texts.index(text)}@example.com", "EMAIL")])
    calls = _scans(monkeypatch)
    for text in texts:
        session.mask(text, [])
    assert calls[0] == len(texts)  # each text scanned for its own value only, not 20 x 20


def test_needles_are_in_every_match() -> None:
    from pii_guard.vault.inflection import inflection_for

    matcher = inflection_for("hu")
    for value in ("kiss elek", "ili", "próba zsuzsanna", "+36 30 123 4567", "a@b.hu", "i"):
        forms = vault_module._literal_forms(matcher, value, EntityType.PERSON)
        needles = vault_module._needles(literal for _, literal in forms)
        if value == "i":
            assert needles is None  # no needle without an ambiguous letter: always scanned
            continue
        assert needles
        for text in (value, value.replace("i", DOTLESS_I), f"x {value}nak y"):
            views = fold_views(text)
            pattern = vault_module._compile([alternative for alternative, _ in forms])
            if any(pattern.search(view.text) for view in views):
                assert not vault_module._absent(needles, views), text


def test_needle_alphabet_is_closed_under_ignorecase() -> None:
    """Under ``re.IGNORECASE`` two case-folded characters match each other only for i/dotless i.

    Needles are cut at those (:data:`_CASE_AMBIGUOUS`), so ``needle in text`` is exact for
    the rest. Checked over all of Unicode, so a Python upgrade that adds a case pair fails here.
    """
    from re import _casefix  # type: ignore[attr-defined]

    def is_folded(char: str) -> bool:
        return char.casefold() == char

    by_lower: dict[str, str] = {}
    for code in range(sys.maxunicode + 1):
        char = chr(code)
        if is_folded(char):
            assert by_lower.setdefault(char.lower(), char) == char
    extra = {
        (chr(a), chr(b))
        for a, others in _casefix._EXTRA_CASES.items()
        for b in others
        if is_folded(chr(a)) and is_folded(chr(b))
    }
    assert {a for pair in extra for a in pair} <= {"i", DOTLESS_I}
    assert all(vault_module._CASE_AMBIGUOUS.fullmatch(a) for pair in extra for a in pair)


def _memo(session: VaultSession) -> dict[str, object]:
    return session._folds  # type: ignore[return-value]


def test_fold_memo_is_bounded_and_forgotten_on_close(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(session_module, "_FOLD_MEMO_ENTRIES", 4)
    monkeypatch.setattr(session_module, "_FOLD_MEMO_CHARS", 200)
    session = Vault(TEST_KEY).session()

    def texts() -> Iterator[str]:
        for i in range(10):
            yield f"Teszt Elek {i}. levele: " + "szöveg " * i

    for text in texts():
        session.mask(text, [span_of(text, "Teszt Elek", "PERSON")])
        assert len(_memo(session)) <= 4
        assert sum(map(len, _memo(session))) <= 200
    session.mask("x" * 500, [])  # longer than the bound: not kept
    assert "x" * 500 not in _memo(session)
    assert _memo(session)
    session.close()
    assert not _memo(session)


def test_fork_does_not_share_the_fold_memo() -> None:
    session = Vault(TEST_KEY).session()
    text = "Teszt Elek írt."
    session.mask(text, [span_of(text, "Teszt Elek", "PERSON")])
    fork = session.fork()
    assert _memo(fork) is not _memo(session)
    assert not _memo(fork)


def test_prefilter_matches_unfiltered_output_for_overlapping_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LAB-1298: values that contain each other resolve identically with and without the
    occurrence prefilter (the scan path must not change first-match order). Pinned so the
    once-seen xdist failure reproduces without the full suite."""

    def run() -> list[str]:
        session = Vault(TEST_KEY).session()
        out = [
            session.mask("Kiss Elek ír.", [span_of("Kiss Elek ír.", "Kiss Elek", "PERSON")]),
            session.mask("Elek is ír.", [span_of("Elek is ír.", "Elek", "PERSON")]),
            session.mask("Kiss Elek és Elek.", []),
        ]
        session.close()
        return out

    with_prefilter = run()
    monkeypatch.setattr(entry_module, "_PREFILTER", False)
    without = run()
    assert _canonical(with_prefilter) == _canonical(without)
