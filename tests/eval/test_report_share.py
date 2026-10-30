"""Shareable benchmark images, their PNG copies and the compact README blocks (LAB-1663)."""

from __future__ import annotations

import json
import re
import struct
from pathlib import Path
from typing import Any

import pytest

from pii_guard.eval.record import RecordError
from pii_guard.eval.report_cli import _current
from pii_guard.eval.report_raster import STAMP_KEY, Raster, read_stamp
from pii_guard.eval.report_readme import (
    INTRO_END,
    INTRO_START,
    fill,
    parse_spec,
    render_compact,
    render_intro,
    splice,
)
from pii_guard.eval.report_share import (
    DARK,
    IMAGES,
    LIGHT,
    SIZES,
    STEPS,
    card,
    file_stem,
    hero,
    how_it_works,
    render_all,
    results_table,
    text_width,
)
from pii_guard.eval.report_share import parse_spec as parse_share

ROOT = Path(__file__).resolve().parents[2]
FONTS = ROOT / "docs" / "benchmarks" / "fonts"

OWN, TOOL, RULES = "rules+ner:own-v1", "tool", "rules"


def _snap(fixture_set: str, system: str, leak: float, over: float) -> dict[str, Any]:
    return {
        "fixture_set": fixture_set,
        "system": system,
        "run_ids": [f"run-{fixture_set}-{system}"],
        "dates": ["2026-10-30"],
        "complete": True,
        "all": {
            "leak": leak,
            "over_masking": over,
            "partial_leak": leak / 2,
            "f1": 0.9,
            "documents": 10,
        },
    }


def _index() -> dict[str, Any]:
    snaps = [
        _snap("a", OWN, 0.002, 0.007),
        _snap("a", TOOL, 0.166, 0.334),
        _snap("a", RULES, 0.388, 0.0),
        _snap("b", OWN, 0.19, 0.24),
        _snap("b", TOOL, 0.188, 0.75),
    ]
    return {
        "fixture_sets": {
            "a": {"documents": {"de": 3, "en": 4}},
            "b": {"documents": {"en": 5}},
        },
        "systems": {TOOL: {"shape": "square"}},
        "snapshots": snaps,
    }


SHARE = {
    "own": OWN,
    "rules": RULES,
    "url": "github.com/example/repo",
    "claim": "Masks it, puts it back.",
    "names": {OWN: "Ours (internal-id-free)", TOOL: "Tool", RULES: "Rules only"},
    "short_names": {OWN: "Ours"},
    "headline": {"fixture_set": "a", "title": "agent-traffic", "systems": [OWN, TOOL, RULES]},
    "set_systems": [OWN, TOOL],
    "sets": [{"fixture_set": "a", "title": "Set A"}, {"fixture_set": "b", "title": "Set B"}],
    "open_ner": {"fixture_set": "a", "systems": {OWN: "our/ner", TOOL: "other/ner"}},
}


# --- Images ---------------------------------------------------------------------------------


def test_every_image_in_every_size_and_theme_and_byte_stable() -> None:
    spec = parse_share(SHARE, "cfg")
    first = render_all(_index(), spec)
    assert len(first) == 2 * sum(len(sizes) for _, sizes in IMAGES.values())
    assert {"results-table-1200x630-dark", "how-it-works", "how-it-works-dark"} <= set(first)
    assert render_all(_index(), spec) == first
    for stem, svg in first.items():
        size_key = next((k for k in SIZES if k and k in stem), "")
        w, h = SIZES[size_key]
        assert f'width="{w}" height="{h}"' in svg, stem
        assert (DARK.bg in svg) == stem.endswith("-dark"), stem
    assert file_stem("results-card", "1200x630", DARK) == "results-card-1200x630-dark"


def test_hero_says_lower_left_is_better_and_prints_every_number() -> None:
    svg = hero(_index(), parse_share(SHARE, "cfg"), (1600, 900), LIGHT)
    assert "lower-left is better" in svg
    for text in ("0.2 %", "0.7 %", "16.6 %", "33.4 %", "38.8 %", "Ours (internal-id-free)"):
        assert text in svg


def test_card_reads_without_context() -> None:
    svg = card(_index(), parse_share(SHARE, "cfg"), (1200, 630), DARK)
    for text in ("PII Guard", "0.2%", "Masks it, puts it back.", "github.com/example/repo", "Tool"):
        assert text in svg
    assert "Rules only" not in svg  # the card compares tools, not our own baseline


def test_results_table_prints_every_cell_and_bolds_the_lowest_per_metric() -> None:
    spec = parse_share({**SHARE, "table_names": {OWN: "Ours fast"}}, "cfg")
    svg = results_table(_index(), spec, (1600, 900), LIGHT)
    assert "Ours fast" in svg and "lower is better" in svg
    assert LIGHT.own_tint in svg  # the own column is highlighted
    bold = re.findall(r'<tspan fill="[^"]+" font-weight="700">([^<]+)</tspan>', svg)
    # Set A: ours lowest on both; set B: the tool on leak (18.8 < 19.0), ours on over-masking.
    assert bold == ["0.2%", "0.7%", "24.0%", "18.8%"]
    assert "Set B (5 docs · en): Ours fast leak 19.0 %, over-masking 24.0 %" in svg


def test_how_it_works_shows_all_steps_and_only_placeholders_cross() -> None:
    svg = how_it_works(_index(), parse_share(SHARE, "cfg"), (1600, 900), DARK)
    for step in STEPS:
        assert step in svg
    assert "PROVIDER SIDE" in svg and "[[PERSON_968e29]]" in svg
    assert DARK.bg in svg
    with pytest.raises(RecordError, match="1600 x 900"):
        how_it_works(_index(), parse_share(SHARE, "cfg"), (1200, 630), LIGHT)


def test_committed_table_image_and_text_table_show_the_same_cells() -> None:
    config = json.loads((ROOT / "docs" / "benchmarks" / "config.json").read_text())
    share, readme = config["share"], config["readme"]
    assert [s["fixture_set"] for s in share["sets"]] == [
        c["fixture_set"] for c in readme["columns"]
    ]
    assert share["set_systems"] == [r["system"] for r in readme["rows"]]
    assert readme["table_image"]["image"] == "results-table"


def test_committed_images_carry_no_internal_ids() -> None:
    for svg in (ROOT / "docs" / "benchmarks").glob("*.svg"):
        if svg.stem.startswith(
            ("leak-vs-overmasking", "results-", "open-ner-models", "how-it-works")
        ):
            text = re.sub(r"<desc[^>]*>.*?</desc>", "", svg.read_text(), flags=re.S)
            assert not re.search(r"LAB-\d+|v42-b3", text), svg.name


def test_missing_snapshot_or_name_is_an_error() -> None:
    bad = {**SHARE, "names": {OWN: "Ours"}}
    with pytest.raises(RecordError, match="display name"):
        parse_share(bad, "cfg")
    index = _index()
    index["snapshots"] = index["snapshots"][1:]
    with pytest.raises(RecordError, match="no snapshot"):
        hero(index, parse_share(SHARE, "cfg"), (1600, 900), LIGHT)


def test_text_width_grows_with_weight_and_length() -> None:
    assert text_width("Presidio", 20, weight=700) > text_width("Presidio", 20)
    assert text_width("Próba", 20) == pytest.approx(text_width("Proba", 20))


# --- PNG ------------------------------------------------------------------------------------


def _size(png: bytes) -> tuple[int, int]:
    w, h = struct.unpack(">II", png[16:24])
    return w, h


def test_raster_is_stamped_sized_and_deterministic(tmp_path: Path) -> None:
    pytest.importorskip("resvg_py")
    svg = render_all(_index(), parse_share(SHARE, "cfg"))["results-card-1080x1080"]
    raster = Raster(svg, FONTS)
    png = raster.render()
    assert png == raster.render()
    assert _size(png) == (1080, 1080)
    assert read_stamp(png) == raster.stamp()
    out = tmp_path / "card.png"
    assert not _current(out, raster)
    out.write_bytes(png)
    assert _current(out, raster)
    assert not Raster(svg.replace("Tool", "Tool2"), FONTS).is_current(out)


def test_read_stamp_ignores_other_files() -> None:
    assert read_stamp(b"not a png") is None
    assert STAMP_KEY == "pii-guard-source"


def test_committed_pngs_match_their_svgs() -> None:
    bench = ROOT / "docs" / "benchmarks"
    pngs = sorted(bench.glob("*.png"))
    assert pngs
    for png in pngs:
        svg = (bench / f"{png.stem}.svg").read_text(encoding="utf-8")
        assert Raster(svg, bench / "fonts").is_current(png), png.name


# --- README blocks --------------------------------------------------------------------------

README_SPEC = {
    "layout": "compact",
    "aliases": {"own": OWN},
    "columns": [{"title": "Set A", "fixture_set": "a"}, {"title": "Set B", "fixture_set": "b"}],
    "rows": [
        {"system": OWN, "label": "Ours", "short": "**Ours**"},
        {"system": TOOL, "label": "Tool", "short": "Tool"},
    ],
    "notes": ["Partial on a: {partial:a:own}."],
    "caveats": ["On b, {leak:b:own} against {leak:b:tool} ({docs:b} docs, {langs:a})."],
    "details": {"summary": "How", "lines": ["Pools {codes:a}."]},
    "intro": {
        "bullets": ["Leak {leak:a:own}, over-masking {over:a:own}."],
        "image": "hero",
        "alt": 'Ours {leak:a:own} "quoted"',
        "caption": "{docs:a} documents",
    },
}


def test_fill_reads_every_field_from_the_records() -> None:
    spec = parse_spec(README_SPEC, "cfg")
    text = "{leak:a:own} {over:a:tool} {partial:a:own} {docs:a} {langs:a} {codes:a}"
    assert fill(text, _index(), spec, "cfg") == "0.2 % 33.4 % 0.1 % 7 German and English de, en"
    with pytest.raises(RecordError, match="no leak"):
        fill("{leak:b:rules}", _index(), spec, "cfg")
    with pytest.raises(RecordError, match="no fixture set"):
        fill("{docs:zzz}", _index(), spec, "cfg")


def test_compact_block_bolds_the_lowest_per_row_and_metric() -> None:
    block = render_compact(_index(), parse_spec(README_SPEC, "cfg"))
    lines = block.splitlines()
    assert "| Leak · over-masking | **Ours** | Tool |" in lines
    assert (
        "| Set A · 7 docs (de+en) | **0.2%**&nbsp;·&nbsp;**0.7%** | 16.6%&nbsp;·&nbsp;33.4% |"
        in lines
    )
    assert (
        "| Set B · 5 docs (en) | 19.0%&nbsp;·&nbsp;**24.0%** | **18.8%**&nbsp;·&nbsp;75.0% |"
        in lines
    )
    assert "Partial on a: 0.1 %." in lines
    assert "- On b, 19.0 % against 18.8 % (5 docs, German and English)." in lines
    assert "<details><summary>How</summary>" in lines
    assert any(line.startswith("Records behind the Ours column:") for line in lines)


def test_table_image_puts_the_text_table_in_a_details_block() -> None:
    spec = parse_spec(
        {
            **README_SPEC,
            "table_image": {
                "image": "results-table",
                "alt": 'Ours {leak:a:own} "q"',
                "summary": "Table as text",
            },
        },
        "cfg",
    )
    block = render_compact(_index(), spec)
    assert 'srcset="docs/benchmarks/results-table-dark.svg"' in block
    assert 'alt="Ours 0.2 % &quot;q&quot;"' in block
    pic, details = block.index("<picture>"), block.index("<details><summary>Table as text")
    table, end = block.index("| Leak · over-masking |"), block.index("</details>")
    assert pic < details < table < end < block.index("Partial on a:")
    with pytest.raises(RecordError, match="table_image"):
        parse_spec({**README_SPEC, "table_image": {"image": "x"}}, "cfg")


def test_intro_block_embeds_the_hero_in_both_themes() -> None:
    block = render_intro(_index(), parse_spec(README_SPEC, "cfg"))
    assert "- Leak 0.2 %, over-masking 0.7 %." in block
    assert 'srcset="docs/benchmarks/hero-dark.svg"' in block
    assert 'alt="Ours 0.2 % &quot;quoted&quot;"' in block
    doc = f"a\n{INTRO_START}\nold\n{INTRO_END}\nb\n"
    out = splice(doc, block, "README.md", start_mark=INTRO_START, end_mark=INTRO_END)
    assert "old" not in out and out.endswith(f"{INTRO_END}\nb\n")


def test_committed_readme_has_no_internal_ids_in_its_text() -> None:
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    prose = re.sub(r"\]\([^)]*\)|(?:src|srcset|href)=\"[^\"]*\"", "", text)
    assert not re.search(r"LAB-\d+|v42-b3|#\d{3}\b", prose)
    assert "wattmind-pii-guard pii-guard" not in text  # no unreleased-PyPI commands
    config = json.loads((ROOT / "docs" / "benchmarks" / "config.json").read_text())
    assert config["readme"]["layout"] == "compact"
