"""Fixture format: markup, validation, loading and writing. All values are fictional."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pii_guard.eval import (
    Document,
    FixtureError,
    from_markup,
    label,
    load_fixtures,
    parse_document,
    write_fixtures,
)
from pii_guard.types import EntityType

NAME = "Teszt Elek"


def _record(**overrides: object) -> dict[str, object]:
    record: dict[str, object] = {
        "id": "t-1",
        "language": "hu",
        "text": f"{NAME} írt.",
        "spans": [{"start": 0, "end": 10, "entity_type": "PERSON", "text": NAME}],
    }
    record.update(overrides)
    return record


def test_from_markup_computes_offsets() -> None:
    doc = from_markup(
        "m-1",
        f"Kedves {label('PERSON', NAME)}nek, {label('EMAIL', 'a@example.com')}!",
        language="hu",
    )
    assert doc.text == f"Kedves {NAME}nek, a@example.com!"
    assert [(s.start, s.end, s.entity_type) for s in doc.spans] == [
        (7, 17, EntityType.PERSON),
        (22, 35, EntityType.EMAIL),
    ]
    assert all(doc.text[s.start : s.end] == s.text for s in doc.spans)


def test_parse_valid_record_sorts_spans() -> None:
    record = _record(
        text="a@example.com és Teszt Elek",
        spans=[
            {"start": 17, "end": 27, "entity_type": "PERSON"},
            {"start": 0, "end": 13, "entity_type": "EMAIL"},
        ],
        meta={"kind": "email"},
    )
    doc = parse_document(record)
    assert [s.entity_type for s in doc.spans] == [EntityType.EMAIL, EntityType.PERSON]
    assert doc.meta == {"kind": "email"}


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"spans": [{"start": 0, "end": 99, "entity_type": "PERSON"}]}, "out of range"),
        ({"spans": [{"start": 0, "end": 5, "entity_type": "PERSON", "text": "Other"}]}, "match"),
        ({"spans": [{"start": 0, "end": 10, "entity_type": "NOPE"}]}, "unknown entity_type"),
        ({"spans": [{"start": 0, "end": 10, "entity_type": "FACE"}]}, "visual"),
        ({"spans": [{"start": 0, "end": 6, "entity_type": "PERSON"}]}, "whitespace"),
        (
            {
                "spans": [
                    {"start": 0, "end": 10, "entity_type": "PERSON"},
                    {"start": 6, "end": 10, "entity_type": "PERSON"},
                ]
            },
            "overlap",
        ),
        ({"spans": [{"start": "0", "end": 10, "entity_type": "PERSON"}]}, "integers"),
        ({"spans": [{"start": 0, "end": 10, "entity_type": "PERSON", "x": 1}]}, "unknown fields"),
        ({"language": "Hungarian"}, "language"),
        ({"id": ""}, "'id'"),
        ({"text": ""}, "'text'"),
        ({"spans": "none"}, "'spans'"),
        ({"meta": []}, "'meta'"),
        ({"extra": True}, "unknown fields"),
    ],
)
def test_parse_rejects_invalid_records(overrides: dict[str, object], message: str) -> None:
    with pytest.raises(FixtureError, match=message) as exc:
        parse_document(_record(**overrides))
    assert NAME not in str(exc.value)


def test_parse_rejects_non_objects() -> None:
    with pytest.raises(FixtureError, match="JSON object"):
        parse_document([1, 2])
    with pytest.raises(FixtureError, match="expected an object"):
        parse_document(_record(spans=[1]))


def test_language_tags_accepted() -> None:
    assert parse_document(_record(language="en-GB")).primary_language == "en"


def test_write_and_load_round_trip(tmp_path: Path) -> None:
    docs = [
        from_markup("a", f"{label('PERSON', NAME)} ír.", language="hu"),
        from_markup("b", "Nothing here.", language="en", meta={"tags": ["hard-negative"]}),
    ]
    path = tmp_path / "x.jsonl"
    write_fixtures(path, docs)
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert "Teszt Elek" in lines[0]  # non-ASCII kept as is, no escapes
    assert load_fixtures(path) == docs
    # A directory loads every *.jsonl in it.
    assert load_fixtures(tmp_path) == docs


def test_load_reports_line_numbers_and_duplicates(tmp_path: Path) -> None:
    good = json.dumps(_record(), ensure_ascii=False)
    (tmp_path / "bad.jsonl").write_text(good + "\n\n{not json\n", encoding="utf-8")
    with pytest.raises(FixtureError, match=r"bad\.jsonl:3: invalid JSON"):
        load_fixtures(tmp_path / "bad.jsonl")

    (tmp_path / "one.jsonl").write_text(good + "\n", encoding="utf-8")
    (tmp_path / "two.jsonl").write_text(good + "\n", encoding="utf-8")
    with pytest.raises(FixtureError, match="duplicate id"):
        load_fixtures([tmp_path / "one.jsonl", tmp_path / "two.jsonl"])
    with pytest.raises(FixtureError, match="no such file"):
        load_fixtures(tmp_path / "missing.jsonl")


def test_write_rejects_duplicate_ids(tmp_path: Path) -> None:
    doc = from_markup("a", "x", language="hu")
    with pytest.raises(FixtureError, match="duplicate"):
        write_fixtures(tmp_path / "x.jsonl", [doc, doc])


def test_reprs_never_contain_values() -> None:
    doc = parse_document(_record())
    assert NAME not in repr(doc)
    assert NAME not in repr(doc.spans[0])
    assert NAME not in str(doc.spans[0])
    assert isinstance(doc, Document)
