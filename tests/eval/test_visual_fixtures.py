"""The committed fictional specimen-style documents (LAB-1121): complete, labelled, fictional."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest
from PIL import Image

from pii_guard.detect.checksums import (
    is_valid_hu_personal_id,
    is_valid_hu_tax_id,
    is_valid_mrz_td1,
    is_valid_mrz_td3,
    is_valid_taj,
)
from pii_guard.eval.visual import REGION_TYPES, load_specimens
from pii_guard.languages.de.checksums import is_valid_steuer_id, is_valid_sv_number

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "eval" / "fixtures" / "visual"
MANIFEST = json.loads((FIXTURES / "manifest.json").read_text("utf-8"))
LABELS = json.loads((FIXTURES / "labels.json").read_text("utf-8"))["specimens"]
RECORD = json.loads((FIXTURES / "generation.json").read_text("utf-8"))
ENTRIES = MANIFEST["specimens"]


def _generator():
    path = ROOT / "eval" / "visual" / "generate_images.py"
    spec = importlib.util.spec_from_file_location("generate_images", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["generate_images"] = module
    spec.loader.exec_module(module)
    return module


def test_at_least_twenty_documents_in_three_languages() -> None:
    assert len(ENTRIES) >= 20
    assert {e["language"] for e in ENTRIES} == {"hu", "de", "en"}
    assert len({e["doc_type"] for e in ENTRIES}) >= 5


def test_files_match_manifest_and_stay_small() -> None:
    total = 0
    for entry in ENTRIES:
        data = (FIXTURES / "images" / entry["file"]).read_bytes()
        assert hashlib.sha256(data).hexdigest() == entry["sha256"], entry["id"]
        with Image.open(FIXTURES / "images" / entry["file"]) as image:
            assert image.format == "PNG"
            assert image.size == (entry["width"], entry["height"])
        total += len(data)
    assert total < 10_000_000
    files = {p.name for p in (FIXTURES / "images").iterdir()}
    assert files == {e["file"] for e in ENTRIES}  # nothing unlisted


def test_notice_says_ai_generated_and_fictional() -> None:
    notice = (FIXTURES / "NOTICE").read_text("utf-8")
    assert "AI-GENERATED FICTIONAL SPECIMENS" in notice
    assert "do not exist" in notice
    assert "MINTA / SPECIMEN" in notice


def test_every_document_is_labelled_and_overprinted() -> None:
    for entry in ENTRIES:
        label = LABELS[entry["sha256"]]
        assert label["id"] == entry["id"]
        assert label["regions"], entry["id"]
        for region in label["regions"]:
            assert region["type"] in REGION_TYPES
            x1, y1, x2, y2 = region["box"]
            assert 0 <= x1 < x2 <= 1 and 0 <= y1 < y2 <= 1
        assert any(r["type"] == "overprint" for r in label["unscored"]), entry["id"]
        types = {r["type"] for r in label["regions"]}
        if entry["doc_type"] in ("passport", "driving_licence", "badge", "member_card", "form"):
            assert "portrait" in types, entry["id"]
        if entry["side"] == "back" or entry["doc_type"] == "passport":
            assert "mrz" in types, entry["id"]


def test_harness_loads_every_document() -> None:
    specimens = load_specimens(
        FIXTURES / "manifest.json", FIXTURES / "labels.json", FIXTURES / "images"
    )
    assert len(specimens) == len(ENTRIES)
    assert {s.language for s in specimens} == {"hu", "de", "en"}


def test_generation_record_within_budget() -> None:
    assert RECORD["model"] == "muse-image-1.0"
    assert RECORD["spend"]["upper_bound_usd"] <= 2.0
    portraits = [c for c in RECORD["calls"] if c["kind"] == "portrait" and c["status"] == "ok"]
    assert len(portraits) >= 18
    for call in RECORD["calls"]:
        assert call["prompt"] and call["status"] in ("ok", "refused", "error")
        if call["status"] == "ok":
            assert len(call["sha256"]) == 64
    assert {d["id"] for d in RECORD["documents"]} == {e["id"] for e in ENTRIES}


def test_every_mrz_has_valid_check_digits() -> None:
    mrzs = [d["values"]["mrz"] for d in RECORD["documents"] if "mrz" in d["values"]]
    assert len(mrzs) == 6
    for mrz in mrzs:
        lines = mrz.split("\n")
        assert is_valid_mrz_td1(*lines) if len(lines) == 3 else is_valid_mrz_td3(*lines), mrz
        assert "UTO" in lines[0]  # ICAO's fictional state, never a real one


@pytest.mark.parametrize("index", range(8))
def test_generated_people_have_checksum_valid_ids(index: int) -> None:
    gen = _generator()
    hu = gen.make_person("hu", index, index % 2 == 0)
    assert is_valid_hu_personal_id(hu.ids["personal_id"])
    assert is_valid_taj(hu.ids["taj"])
    assert is_valid_hu_tax_id(hu.ids["tax_id"])
    de = gen.make_person("de", index, index % 2 == 1)
    assert is_valid_steuer_id(de.ids["steuer_id"])
    assert is_valid_sv_number(de.ids["sv_number"])
    en = gen.make_person("en", index, True)
    assert en.phone.startswith("07700 900")
    for person in (hu, de, en):
        assert person.email.split("@")[1].startswith("example.")
        assert is_valid_mrz_td3(*gen.mrz_td3(person, person.ids["passport"], gen._EXPIRY))
        assert is_valid_mrz_td1(*gen.mrz_td1(person, person.ids["id_card"], gen._EXPIRY))


def test_committed_results_cover_the_set() -> None:
    report = json.loads((ROOT / "eval" / "results" / "visual" / "fictional.json").read_text())
    assert report["specimens"] == len(ENTRIES)
    assert report["errors"] == {}
    assert report["by_region_type"]["portrait"]["regions"] > 0


def test_report_title_is_configurable() -> None:
    from pii_guard.eval.visual import render_markdown

    report = json.loads((ROOT / "eval" / "results" / "visual" / "fictional.json").read_text())
    assert render_markdown(report).startswith("# Visual recall on fictional")
