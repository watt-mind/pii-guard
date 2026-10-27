"""The Ai4Privacy OpenPII loader: label mapping, merging, seeded sampling, the committed sample."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from pii_guard.eval.fixtures import load_fixtures
from pii_guard.eval.public import ai4privacy as a4p
from pii_guard.types import EntityType

ROOT = Path(__file__).resolve().parents[2]
PUBLIC = ROOT / "eval" / "fixtures" / "public"


def _row(text: str, spans: list[tuple[str, str]], *, uid: int = 1, language: str = "en"):
    """A dataset row; spans are (label, value), located left to right in ``text``."""
    mask, cursor = [], 0
    for label, value in spans:
        start = text.index(value, cursor)
        mask.append({"label": label, "start": start, "end": start + len(value), "value": value})
        cursor = start + len(value)
    return {
        "uid": uid,
        "language": language,
        "region": "XX",
        "source_text": text,
        "privacy_mask": mask,
    }


def _types(converted):
    doc = converted.document
    return [(s.entity_type, doc.text[s.start : s.end]) for s in doc.spans]


def test_names_and_address_parts_merge():
    row = _row(
        "Dear Ms Anna Fictional, we moved to 12 Example Road, Testville 99999 on 2020-01-01.",
        [
            ("TITLE", "Ms"),
            ("GIVENNAME", "Anna"),
            ("SURNAME", "Fictional"),
            ("BUILDINGNUM", "12"),
            ("STREET", "Example Road"),
            ("CITY", "Testville"),
            ("ZIPCODE", "99999"),
            ("DATE", "2020-01-01"),
        ],
    )
    converted = a4p.convert_row(row)
    assert _types(converted) == [
        (EntityType.PERSON, "Anna Fictional"),
        (EntityType.ADDRESS, "12 Example Road, Testville 99999"),
    ]
    assert converted.dropped == {"TITLE": 1, "DATE": 1}
    assert converted.document.id == "ai4privacy-1"
    assert converted.document.meta["source"] == a4p.DATASET


def test_bare_city_is_policy_excluded_but_zip_alone_is_scored():
    row = _row(
        "Flights to Testville; office at 99999.", [("CITY", "Testville"), ("ZIPCODE", "99999")]
    )
    converted = a4p.convert_row(row)
    assert _types(converted) == [(EntityType.ADDRESS, "99999")]
    assert converted.dropped == {"CITY (on its own)": 1}


def test_names_separated_by_words_stay_separate():
    row = _row("Anna and Bela met.", [("GIVENNAME", "Anna"), ("GIVENNAME", "Bela")])
    assert [t for t, _ in _types(a4p.convert_row(row))] == [EntityType.PERSON] * 2


def test_hungarian_tax_and_social_numbers_get_their_own_types():
    row = _row(
        "Adó 8123456789, TAJ 123 456 789.",
        [("TAXNUM", "8123456789"), ("SOCIALNUM", "123 456 789")],
        language="hu",
    )
    assert [t for t, _ in _types(a4p.convert_row(row))] == [
        EntityType.NATIONAL_ID_HU_TAX,
        EntityType.NATIONAL_ID_HU_TAJ,
    ]
    en = _row("Tax 8123456789.", [("TAXNUM", "8123456789")])
    assert _types(a4p.convert_row(en)) == [(EntityType.ID_DOCUMENT, "8123456789")]


def test_whitespace_is_trimmed_and_unknown_labels_counted():
    row = _row("Call  +1 555 0100 now", [("TELEPHONENUM", " +1 555 0100"), ("URLX", "now")])
    converted = a4p.convert_row(row)
    assert _types(converted) == [(EntityType.PHONE, "+1 555 0100")]
    assert converted.unknown == {"URLX": 1}


def test_bad_offsets_raise_without_the_value():
    row = _row("Anna Fictional", [("GIVENNAME", "Anna")])
    row["privacy_mask"][0]["value"] = "Secretvalue"
    with pytest.raises(a4p.ConversionError) as exc:
        a4p.convert_row(row)
    assert "Secretvalue" not in str(exc.value)


def test_overlap_of_different_types_raises():
    row = _row("Anna Fictional", [("GIVENNAME", "Anna")])
    row["privacy_mask"].append({"label": "EMAIL", "start": 2, "end": 8, "value": "na Fic"})
    with pytest.raises(a4p.ConversionError):
        a4p.convert_row(row)


def test_sampling_is_seeded_and_independent_of_file_order():
    rows = [
        _row(f"Hello Name{i}", [("GIVENNAME", f"Name{i}")], uid=i, language=lang)
        for i, lang in enumerate(["en", "hu", "de", "fr"] * 25)
    ]
    sample = {"en": 5, "hu": 3}
    first, seen = a4p.sample_rows(rows, sample, seed=7)
    shuffled = rows[::-1]
    second, _ = a4p.sample_rows(shuffled, sample, seed=7)
    ids = {lang: [c.document.id for c in items] for lang, items in first.items()}
    assert ids == {lang: [c.document.id for c in items] for lang, items in second.items()}
    assert [len(ids["en"]), len(ids["hu"])] == [5, 3]
    assert seen["rows_en"] == 25
    # The order is sha256("<seed>:<uid>"), smallest first.
    en_uids = [r["uid"] for r in rows if r["language"] == "en"]
    expected = sorted(en_uids, key=lambda u: hashlib.sha256(f"7:{u}".encode()).hexdigest())[:5]
    assert [c.document.meta["uid"] for c in first["en"]] == expected
    other, _ = a4p.sample_rows(rows, sample, seed=8)
    assert [c.document.id for c in other["en"]] != ids["en"]


def test_unconvertible_rows_are_replaced():
    rows = [_row(f"Hello Name{i}", [("GIVENNAME", f"Name{i}")], uid=i) for i in range(10)]
    for r in rows:
        r["privacy_mask"][0]["value"] = "wrong"
    rows += [_row("Hello Okay", [("GIVENNAME", "Okay")], uid=99)]
    chosen, seen = a4p.sample_rows(rows, {"en": 1}, seed=1)
    assert [c.document.meta["uid"] for c in chosen["en"]] == [99]
    order = sorted(range(10), key=lambda u: hashlib.sha256(f"1:{u}".encode()).hexdigest())
    key_99 = hashlib.sha256(b"1:99").hexdigest()
    before = [u for u in order if hashlib.sha256(f"1:{u}".encode()).hexdigest() < key_99]
    assert seen["skipped_en"] == len(before)


def test_main_from_local_file_and_check(tmp_path, monkeypatch):
    rows = [
        _row(
            f"Hi Name{i} at n{i}@example.com",
            [("GIVENNAME", f"Name{i}"), ("EMAIL", f"n{i}@example.com")],
            uid=i,
            language=lang,
        )
        for i, lang in enumerate(["en", "hu"] * 6)
    ]
    source = tmp_path / "validation.jsonl"
    source.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    monkeypatch.setattr(a4p, "FILE_SHA256", hashlib.sha256(source.read_bytes()).hexdigest())
    out, manifest = tmp_path / "out", tmp_path / "manifest.json"
    args = [
        "fetch",
        "--source-file",
        str(source),
        "--sample",
        "en=2,hu=3",
        "--seed",
        "3",
        "--out",
        str(out),
        "--manifest",
        str(manifest),
    ]
    assert a4p.main(args) == 0
    data = json.loads(manifest.read_text(encoding="utf-8"))
    assert data["languages"]["hu"]["documents"] == 3
    assert data["languages"]["en"]["gold_spans"] == {"EMAIL": 2, "PERSON": 2}
    assert len(load_fixtures(out / "en-ai4privacy.jsonl")) == 2
    assert a4p.main([*args, "--check"]) == 0
    data["languages"]["en"]["uids"].reverse()
    manifest.write_text(json.dumps(data), encoding="utf-8")
    assert a4p.main([*args, "--check"]) == 1


def test_main_rejects_a_file_with_the_wrong_hash(tmp_path):
    source = tmp_path / "validation.jsonl"
    source.write_text(json.dumps(_row("Hi Anna", [("GIVENNAME", "Anna")])) + "\n", "utf-8")
    with pytest.raises(RuntimeError, match="SHA-256"):
        a4p.main(
            [
                "fetch",
                "--source-file",
                str(source),
                "--out",
                str(tmp_path),
                "--manifest",
                str(tmp_path / "m.json"),
            ]
        )


def test_committed_sample_matches_its_manifest():
    manifest = json.loads((PUBLIC / "ai4privacy-openpii-1m.json").read_text(encoding="utf-8"))
    assert manifest["revision"] == a4p.REVISION
    assert manifest["file_sha256"] == a4p.FILE_SHA256
    assert manifest["license"] == "CC-BY-4.0"
    assert manifest["label_mapping"] == a4p.mapping_table()
    for lang, block in manifest["languages"].items():
        docs = load_fixtures(PUBLIC / f"{lang}-ai4privacy.jsonl")
        assert [d.meta["uid"] for d in docs] == block["uids"]
        assert {d.language for d in docs} == {lang}
    notice = (PUBLIC / "README.md").read_text(encoding="utf-8")
    assert "Ai4Privacy / Ai Suisse SA" in notice
    assert "CC-BY-4.0" in notice
