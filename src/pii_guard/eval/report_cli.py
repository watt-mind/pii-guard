"""``pii-guard eval report``: build the benchmark index, charts and page from the run records.

```
pii-guard eval report             # rewrite whatever is stale
pii-guard eval report --journey   # ... and fold docs/journey/*.md into docs/journey.md
pii-guard eval report --check     # exit 1 if a committed output is stale
pii-guard eval report --validate  # build everything in memory, compare nothing (PR CI)
pii-guard eval report --print-index  # the compact index on stdout (the UI build reads it)
```

Inputs: every run record in ``eval/results/runs/`` (validated against the schema),
``docs/benchmarks/config.json`` (headline fixture set and featured systems) and the journey
entries in ``docs/journey/`` (:mod:`pii_guard.eval.report_journey`). Outputs, all a pure
function of the inputs so ``--check`` compares them byte for byte:

- ``docs/benchmarks/*.svg``: the charts (:mod:`pii_guard.eval.report_charts`), plus
  ``validity-<set>.svg`` for each set with a number-validity breakdown;
- ``docs/benchmarks.md``: tables, embedded charts and method notes;
- the results and intro blocks of ``README.md`` (:mod:`pii_guard.eval.report_readme`), when
  the config has a ``readme`` section;
- the shareable images (:mod:`pii_guard.eval.report_share`), when the config has a ``share``
  section: ``docs/benchmarks/<name>[-<size>][-dark].svg`` and a ``.png`` of each, rasterized
  without a browser (:mod:`pii_guard.eval.report_raster`). A PNG is compared by the stamp it
  carries (the SHA-256 of its SVG, of the fonts and the renderer), so ``--check`` needs no
  rasterizer;
- ``docs/benchmarks/colours.json``: the append-only color registry
  (:mod:`pii_guard.eval.report_colours`), read first and rewritten only when a new system
  needs a color;
- with ``--journey``, the generated block of ``docs/journey.md``.

The index (:mod:`pii_guard.eval.report_index`) is a build output, never committed: the report
writes ``eval/results/index.json`` for local use, and the UI build gets the compact form from
``--print-index`` (``ui/vite.config.ts``). Committed copies used to make every pair of pull
requests that added a run record conflict (LAB-1269).

Who renders the committed outputs: see CONTRIBUTING.md, "Generated files". When the
``render-docs`` workflow is on, it renders them on ``develop`` after each merge and pull
requests run ``--validate``; otherwise pull requests commit them and run ``--check``.

Exit codes: 0 up to date (or written, or valid), 1 stale under ``--check``, 2 bad input (an
invalid run record or journey entry, an unreadable config).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from pii_guard.eval import report_charts as charts
from pii_guard.eval.fixtures import file_sha256
from pii_guard.eval.record import DEFAULT_RUNS_DIR, RecordError, load_records
from pii_guard.eval.report_colours import DEFAULT_REGISTRY, dumps_registry, load_registry
from pii_guard.eval.report_index import build_index
from pii_guard.eval.report_journey import (
    DEFAULT_ENTRIES_DIR,
    DEFAULT_JOURNEY,
    JourneyError,
    load_entries,
)
from pii_guard.eval.report_journey import render as render_journey
from pii_guard.eval.report_raster import Raster
from pii_guard.eval.report_readme import parse_spec as parse_readme_spec
from pii_guard.eval.report_readme import render_readme
from pii_guard.eval.report_share import parse_spec as parse_share_spec
from pii_guard.eval.report_share import render_all as render_share
from pii_guard.eval.stats import fmt_duration, fmt_pct

__all__ = [
    "CHARTS",
    "build_outputs",
    "build_parser",
    "compact_index",
    "current_index",
    "journey_output",
    "main",
    "render_page",
]

#: Written by ``pii-guard eval report`` for local use; ignored by git and by ``--check``.
DEFAULT_INDEX = Path("eval/results/index.json")
DEFAULT_DOCS_DIR = Path("docs")
DEFAULT_CONFIG = Path("docs/benchmarks/config.json")
#: Its results block is generated when the config has a ``readme`` section (LAB-1239).
DEFAULT_README = Path("README.md")

Chart = Callable[[Mapping[str, Any], str, Sequence[str]], str]

#: ``(file name, title, renderer)``; a renderer gets the index, the headline set and the
#: featured systems.
CHARTS: list[tuple[str, str, Chart]] = [
    (
        "leak-vs-latency.svg",
        "Leak rate vs latency",
        lambda i, s, f: charts.leak_vs_latency(i, fixture_set=s, systems=f),
    ),
    (
        "by-language.svg",
        "F1 and leak rate by language",
        lambda i, s, f: charts.by_language(i, fixture_set=s, systems=f),
    ),
    (
        "progress.svg",
        "Leak rate over time",
        lambda i, s, f: charts.progress(i, fixture_set=s, systems=f),
    ),
    (
        "type-recall.svg",
        "Recall by entity type",
        lambda i, s, f: charts.type_recall_heatmap(i, fixture_set=s, systems=f),
    ),
    (
        "visual-recall.svg",
        "Visual recall on image documents",
        lambda i, s, f: charts.visual_recall(i),
    ),
    (
        "segmenter-recall.svg",
        "Segmenters: SAM 3.1 API vs on-device",
        lambda i, s, f: charts.visual_recall(i, segmenters=True),
    ),
    (
        "latency.svg",
        "Gateway overhead",
        lambda i, s, f: charts.latency(i),
    ),
]
#: Charts drawn only when the index has the data they need.
_OPTIONAL = {"visual-recall.svg": "visual", "latency.svg": "latency"}


def _drawn(index: Mapping[str, Any], name: str) -> bool:
    if name == "segmenter-recall.svg":
        return any(charts.is_segment_run(r) for r in index.get("visual") or [])
    if name == "visual-recall.svg":
        return any(not charts.is_segment_run(r) for r in index.get("visual") or [])
    key = _OPTIONAL.get(name)
    return key is None or bool(index.get(key))


def validity_sets(index: Mapping[str, Any]) -> list[str]:
    """Fixture sets with a number-validity breakdown in some current snapshot."""
    return sorted({s["fixture_set"] for s in index["snapshots"] if s["all"].get("validity")})


def validity_chart(fixture_set: str) -> str:
    """File name of a set's number-validity chart under ``docs/benchmarks/``."""
    return f"validity-{fixture_set}.svg"


# --- Page ---------------------------------------------------------------------------------


def _cell(text: object) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


def _table(header: Sequence[str], align: Sequence[str], rows: Sequence[Sequence[object]]) -> str:
    out = ["| " + " | ".join(header) + " |", "|" + "|".join(align) + "|"]
    out += ["| " + " | ".join(_cell(c) for c in row) + " |" for row in rows]
    return "\n".join(out) + "\n"


def _set_line(index: Mapping[str, Any], name: str) -> str:
    info = index["fixture_sets"][name]
    docs = " + ".join(f"{lang} {n}" for lang, n in info["documents"].items())
    origin = info["origin"]
    if origin == "generated" and info["generators"]:
        origin += " by " + ", ".join(info["generators"])
    return f"{origin}; documents: {docs}"


def _ordered_snapshots(index: Mapping[str, Any], fixture_set: str) -> list[dict[str, Any]]:
    order = {key: i for i, key in enumerate(index["systems"])}
    snaps = [s for s in index["snapshots"] if s["fixture_set"] == fixture_set]
    return sorted(snaps, key=lambda s: order.get(s["system"], len(order)))


def _label(index: Mapping[str, Any], key: str) -> str:
    style = index["systems"].get(key, {})
    label = style.get("label", key)
    return f"**{label}**" if style.get("default") else label


def _commits(s: Mapping[str, Any]) -> str:
    return ", ".join(f"`{c[:7]}`" for c in s["commits"])


def _marks(s: Mapping[str, Any]) -> str:
    return ("" if s.get("complete", True) else " †") + (" ‡" if s.get("rescored") else "")


def _false_blocks(m: Mapping[str, Any]) -> str:
    """``0.0% (0/120)``: the outbound re-check's false blocks of a snapshot, else ``—``."""
    ob = m.get("outbound_check")
    if not ob:
        return "—"
    return f"{fmt_pct(ob['rate'], sign=True)} ({ob['blocked']}/{ob['checked']})"


def _set_table(index: Mapping[str, Any], fixture_set: str) -> str:
    snaps = _ordered_snapshots(index, fixture_set)
    # The outbound re-check column only once a run of the set measured it (LAB-1505).
    outbound = any(s["all"].get("outbound_check") for s in snaps)
    rows = []
    for s in snaps:
        m = s["all"]
        rows.append(
            [
                _label(index, s["system"]) + _marks(s),
                m["documents"],
                fmt_pct(m["precision"], sign=True),
                fmt_pct(m["recall"], sign=True),
                fmt_pct(m["f1"], sign=True),
                fmt_pct(m["leak"], sign=True),
                fmt_pct(m["partial_leak"], sign=True),
                fmt_pct(m["over_masking"], sign=True),
                fmt_pct(m["roundtrip"], sign=True),
                fmt_duration(m["detect_p50_ms"]) + ("*" if m["latency_pooled"] else ""),
                *([_false_blocks(m)] if outbound else []),
                ", ".join(s["dates"]),
                _commits(s),
            ]
        )
    return _table(
        [
            "System",
            "Docs",
            "Precision",
            "Recall",
            "F1",
            "Leak",
            "Partial leak",
            "Over-masking",
            "Round trip",
            "Detect p50",
            *(["False blocks"] if outbound else []),
            "Run",
            "Commit",
        ],
        [
            "---",
            "---:",
            "---:",
            "---:",
            "---:",
            "---:",
            "---:",
            "---:",
            "---:",
            "---:",
            *(["---:"] if outbound else []),
            "---",
            "---",
        ],
        rows,
    ) + _set_notes(index, fixture_set)


def _set_notes(index: Mapping[str, Any], fixture_set: str) -> str:
    """Footnotes for the marks in :func:`_set_table` (only those that occur)."""
    snaps = _ordered_snapshots(index, fixture_set)
    langs = index["fixture_sets"][fixture_set]["languages"]
    notes = []
    partial = [s for s in snaps if not s.get("complete", True)]
    if partial:
        names = "; ".join(
            index["systems"][s["system"]]["short_label"]
            + f" (no {', '.join(s['missing_languages'])})"
            for s in partial
        )
        notes.append(
            f"† Not run on every language of the current fixture files ({' + '.join(langs)}): "
            f"its `all` pools fewer documents, so compare it by language, not with the other "
            f"rows. {names}."
        )
    if any(s.get("rescored") for s in snaps):
        run_ids = {r for s in snaps if s.get("rescored") for r in s["run_ids"]}
        methods = {
            m
            for run in index["runs"]
            if run["run_id"] in run_ids and run.get("rescored")
            for m in run["rescored"]["method"].split("+")
        }
        what = []
        if "unscored-types" in methods:
            what.append(
                "`DATE_OF_BIRTH` predictions are left out of precision and over-masking, since "
                "the set labels every date `DATE`, which pii-guard's policy excludes; a masked "
                "title or bare town still counts against precision and over-masking, because "
                "these runs kept no per-document predictions to apply ignore regions to"
            )
        if "no-consistency" in methods:
            what.append(
                "the comparison tools' placeholder consistency is null (they don't report their "
                "replacements; it was a placeholder 0.0)"
            )
        notes.append(
            "‡ Re-scored from the record's own counts after the run (LAB-1213): a change of "
            "scoring method, not a new run and not a better model. "
            + "; ".join(what)[:1].upper()
            + "; ".join(what)[1:]
            + "."
        )
    return "".join(f"\n{n}\n" for n in notes)


def _stale_table(index: Mapping[str, Any], fixture_set: str) -> str:
    """Results on an earlier version of a fixture file: kept for reference, not compared."""
    order = {key: i for i, key in enumerate(index["systems"])}
    snaps = sorted(
        (s for s in index.get("stale_snapshots", []) if s["fixture_set"] == fixture_set),
        key=lambda s: order.get(s["system"], len(order)),
    )
    if not snaps:
        return ""
    rows = []
    for s in snaps:
        for lang, m in s["languages"].items():
            rows.append(
                [
                    _label(index, s["system"]),
                    lang,
                    f"`{s['superseded'][lang] or '?'}`",
                    m["documents"],
                    fmt_pct(m["f1"], sign=True),
                    fmt_pct(m["leak"], sign=True),
                    ", ".join(s["dates"]),
                ]
            )
    current = ", ".join(
        f"{lang} `{sha}`" for lang, sha in index["fixture_sets"][fixture_set]["fixtures"].items()
    )
    return (
        "\nOn an earlier version of a fixture file (current: "
        + current
        + "). These ran on other documents, so they stay out of the table above and the "
        "charts:\n\n"
        + _table(
            ["System", "Lang", "Fixture", "Docs", "F1", "Leak", "Run"],
            ["---", "---", "---", "---:", "---:", "---:", "---"],
            rows,
        )
    )


def _share(c: Mapping[str, Any], num: str, den: str) -> str:
    return f"{fmt_pct(c[num] / c[den] if c[den] else None, sign=True)} ({c[num]}/{c[den]})"


def _validity_section(index: Mapping[str, Any], fixture_set: str) -> str:
    """Number-validity breakdown of the set (LAB-1201), or "" when no run has one."""
    snaps = [s for s in _ordered_snapshots(index, fixture_set) if s["all"].get("validity")]
    if not snaps:
        return ""
    rows = []
    for s in snaps:
        m, v = s["all"], s["all"]["validity"]
        mark = "" if v["matches_headline"] else " §"
        rows.append(
            [
                _label(index, s["system"]) + mark,
                fmt_pct(m["leak"], sign=True),
                _share(v["valid"], "found", "gold"),
                _share(v["valid"], "leaked", "values"),
                _share(v["invalid"], "found", "gold"),
                _share(v["invalid"], "leaked", "values"),
                _share(v["excluding_number_types"], "leaked", "values"),
            ]
        )
    first = snaps[0]["all"]["validity"]["per_type"]
    shares = ", ".join(
        f"`{name}` {row['valid']['gold']}/{row['valid']['gold'] + row['invalid']['gold']}"
        for name, row in first.items()
    )
    out = [
        "\n**Number validity.** The headline leak above, split by whether a structured identifier "
        "passes the language packs' own validators (card Luhn, IBAN, TAJ and tax-ID check "
        "digits, phone numbering plans, ID-document checksums and formats). Invalid numbers "
        "stay in the headline: a mistyped real identifier is still personal data "
        "([evaluation.md](evaluation.md#number-validity)). Valid values per type: "
        f"{shares}.\n",
        f"\n![Leak rate by number validity](benchmarks/{validity_chart(fixture_set)})\n\n",
        _table(
            [
                "System",
                "Leak",
                "Recall, valid numbers",
                "Leak, valid numbers",
                "Recall, invalid numbers",
                "Leak, invalid numbers",
                "Leak, other values",
            ],
            ["---", "---:", "---:", "---:", "---:", "---:", "---:"],
            rows,
        ),
    ]
    reruns = sorted({v["by"] for s in snaps if (v := s["all"]["validity"])["rerun"]})
    if reruns:
        out.append(
            f"\nThese runs kept no per-document predictions, so each system was run again to "
            f"classify them ({', '.join(reruns)}); the Leak column is the original records', "
            'unchanged. "Other values" are every value that is not a number type (names, '
            "addresses, e-mail).\n"
        )
    off = [s for s in snaps if not s["all"]["validity"]["matches_headline"]]
    if off:
        names = "; ".join(
            f"{index['systems'][s['system']]['short_label']} "
            f"(re-run leak {fmt_pct(s['all']['validity']['rerun_leak'], sign=True)}, "
            f"headline {fmt_pct(s['all']['leak'], sign=True)})"
            for s in off
        )
        out.append(
            "\n§ The re-run did not reproduce the headline counts exactly (an LLM detector "
            "doesn't answer the same way twice): the breakdown adds up to the re-run's own "
            f"totals. {names}.\n"
        )
    return "".join(out)


def _language_table(index: Mapping[str, Any], fixture_set: str) -> str:
    snaps = _ordered_snapshots(index, fixture_set)
    langs = [lang for lang in index["languages"] if any(lang in s["languages"] for s in snaps)]
    header = ["System"] + [f"{lang} F1" for lang in langs] + [f"{lang} leak" for lang in langs]
    rows = []
    for s in snaps:
        f1 = [fmt_pct(s["languages"].get(lang, {}).get("f1"), sign=True) for lang in langs]
        leak = [fmt_pct(s["languages"].get(lang, {}).get("leak"), sign=True) for lang in langs]
        rows.append([_label(index, s["system"]), *f1, *leak])
    return _table(header, ["---"] + ["---:"] * (2 * len(langs)), rows)


def _type_table(index: Mapping[str, Any], fixture_set: str, systems: Sequence[str]) -> str:
    snaps = [
        s
        for s in _ordered_snapshots(index, fixture_set)
        if s["system"] in systems and s.get("complete", True)
    ]
    types = [t for t in index["entity_types"] if any(t in s["all"]["per_type"] for s in snaps)]
    header = ["Type", "Gold", *(index["systems"][s["system"]]["short_label"] for s in snaps)]
    rows = []
    for t in types:
        gold = max((s["all"]["per_type"].get(t, {}).get("gold") or 0) for s in snaps)
        rows.append(
            [
                f"`{t}`",
                gold,
                *(fmt_pct(s["all"]["per_type"].get(t, {}).get("recall"), sign=True) for s in snaps),
            ]
        )
    return _table(header, ["---", "---:"] + ["---:"] * len(snaps), rows)


def _visual_table(index: Mapping[str, Any]) -> str:
    runs = [r for r in index["visual"] if not charts.is_segment_run(r)]
    region_types: list[str] = []
    for r in runs:
        region_types += [k for k in r["by_region_type"] if k not in region_types]
    rows = []
    for r in runs:
        per = [
            fmt_pct((r["by_region_type"].get(k) or {}).get("recall_iou50"), sign=True)
            for k in region_types
        ]
        rows.append(
            [
                f"`{r['run_id']}`",
                f"`{r.get('fixture_set') or 'specimens'}`",
                r["specimens"],
                r["countries"],
                *per,
                fmt_pct(r["overall"]["recall_iou50"], sign=True),
                fmt_pct(r["over_masking_mean"], sign=True),
            ]
        )
    return _table(
        ["Run", "Set", "Images", "Countries", *region_types, "All regions", "Over-masking (mean)"],
        ["---", "---", "---:", "---:"] + ["---:"] * (len(region_types) + 2),
        rows,
    )


def _segmenter_table(index: Mapping[str, Any]) -> str:
    rows = []
    for r in index["visual"]:
        if not charts.is_segment_run(r):
            continue
        lat = r.get("latency_ms") or {}
        by = r["by_region_type"]
        rows.append(
            [
                f"`{r['run_id']}`",
                f"`{r.get('fixture_set') or 'specimens'}`",
                r["specimens"],
                fmt_pct((by.get("portrait") or {}).get("recall_iou50"), sign=True),
                fmt_pct((by.get("portrait") or {}).get("recall_cov90"), sign=True),
                fmt_pct((by.get("signature") or {}).get("recall_iou50"), sign=True),
                fmt_pct((by.get("signature") or {}).get("recall_cov90"), sign=True),
                fmt_pct(r["over_masking_mean"], sign=True),
                fmt_duration(lat.get("segment_per_image_p50")),
                fmt_duration(lat.get("segment_per_image_p95")),
            ]
        )
    return _table(
        [
            "Run", "Set", "Images", "Portrait (IoU)", "Portrait (cov ≥ 90%)", "Signature (IoU)",
            "Signature (cov ≥ 90%)", "Over-masking (mean)", "p50 / image", "p95 / image",
        ],
        ["---", "---", "---:"] + ["---:"] * 7,
        rows,
    )  # fmt: skip


def _latency_table(index: Mapping[str, Any]) -> str:
    runs = charts.latest_latency(index)
    # The re-check column only once a run recorded it (LAB-1505).
    outbound = any(c.get("outbound_check_ms") for r in runs for c in r["cells"])
    rows = []
    for run in runs:
        for c in run["cells"]:
            o, t = c["overhead_ms"] or {}, c.get("added_ttft_ms") or {}
            det = c.get("stages_ms", {}).get("detect") or {}
            rows.append(
                [
                    charts.latency_label(run),
                    c["concurrency"],
                    "yes" if c["stream"] else "no",
                    c["requests"],
                    fmt_duration(o.get("p50")),
                    fmt_duration(o.get("p95")),
                    fmt_duration(o.get("p99")),
                    fmt_duration(det.get("p50")),
                    fmt_duration(t.get("p50")) if c["stream"] else "—",
                    fmt_duration(t.get("p95")) if c["stream"] else "—",
                    *(
                        [fmt_duration((c.get("outbound_check_ms") or {}).get("p50"))]
                        if outbound
                        else []
                    ),
                    f"{run['upstream_delay_ms']:g}",
                    f"`{run['run_id']}`",
                ]
            )
    return _table(
        [
            "System",
            "Concurrency",
            "Stream",
            "n",
            "Overhead p50",
            "p95",
            "p99",
            "Detect p50",
            "Added TTFT p50",
            "p95",
            *(["Re-check p50"] if outbound else []),
            "Upstream delay ms",
            "Run",
        ],
        [
            "---",
            "---:",
            "---",
            "---:",
            "---:",
            "---:",
            "---:",
            "---:",
            "---:",
            "---:",
            *(["---:"] if outbound else []),
            "---:",
            "---",
        ],
        rows,
    )


def _cost(run: Mapping[str, Any]) -> str:
    cost = run.get("cost") or {}
    parts = []
    if cost.get("usd") is not None:
        parts.append(("≈ " if cost.get("estimated") else "") + f"${cost['usd']:.2f}")
    if cost.get("gpu_minutes") is not None:
        parts.append(f"{cost['gpu_minutes']:g} GPU-min")
    if cost.get("shared_with"):
        parts.append("shared")
    return ", ".join(parts) or "—"


def _run_log(index: Mapping[str, Any]) -> str:
    rows = []
    latency_labels = {r["run_id"]: r["label"] for r in index.get("latency", [])}
    for run in reversed(index["runs"]):
        style = index["systems"].get(run["system"], {})
        rows.append(
            [
                run["date"],
                f"`{run['run_id']}`",
                latency_labels.get(run["run_id"]) or style.get("label", run["system"]),
                run["fixture_set"],
                ", ".join(run["languages"]) or "—",
                run["source"],
                f"`{run['commit'][:7]}`" + (" (dirty)" if run["dirty"] else ""),
                run["hardware"] or "—",
                _cost(run),
            ]
        )
    return _table(
        ["Date", "Run", "System", "Set", "Lang", "Source", "Commit", "Hardware", "Cost"],
        ["---"] * 9,
        rows,
    )


_METHOD = """\
## How to read this

- **Leak rate** is the share of labeled values that still appear, in any surface form, in
  the text the model would receive after masking (case- and whitespace-insensitive, through
  the language's inflected forms, structured identifiers by their letters and digits with any
  separators). Lower is safer; it is the number that matters most. **Partial leak** counts
  values not leaked whole but with an identifying token left (the street of an address whose
  postcode alone was masked). Details: [evaluation.md](evaluation.md#leak-rate-in-practice).
- **Precision, recall, F1** are span-level with overlap matching (a prediction counts if it
  overlaps a gold span of the same type); the run records also keep exact-match numbers.
  **Over-masking** is the share of masked spans that overlap no gold span of any type (spans,
  not characters). A prediction on text the set labels but pii-guard's policy doesn't score
  (Ai4Privacy's dates, titles and bare towns) is left out of precision and over-masking.
  **Round trip** is the share of documents that unmask back to the original text exactly
  (comparison tools that can't unmask show —).
- **Hand-written vs generated sets.** `smoke` is written by hand with inline labels and has
  adversarial look-alikes; `synth-*` sets are written by a Meta Muse model around fictional
  identities and labeled automatically. **Muse-generated sets flatter Muse-based detectors**: the
  same model family wrote the text and reads it, so its phrasing and its idea of what an
  entity is match. Converted third-party (`public`) sets carry no such advantage.
  The headline charts use the hand-written set for that reason.
- **Small sets.** The sets have tens of documents per language: differences of a few points
  are noise. Every number below says which set, which run date and which commit it came from.
- **Latency** is detection time per document (p50) on the hardware in the run log; it is not
  comparable across machines. `*` marks a value averaged over several runs (percentiles
  can't be pooled exactly).
- **Pooling.** Every count-based metric is pooled exactly over languages by summing counts,
  so `all` is **micro-averaged**: each span or value weighs the same, and a language with
  more documents weighs more. Only runs on the current version of each fixture file are
  pooled or charted; results on an earlier version are listed separately under their set.
- `rules` is the rules-only pass with no name detection; names and addresses come from the
  NER and LLM passes. Compare it with the other tools on structured identifiers.
"""


def render_page(
    index: Mapping[str, Any],
    *,
    headline_set: str,
    featured: Sequence[str],
    datasets_section: str = "",
) -> str:
    """``docs/benchmarks.md``: a pure function of the index, the config and the per-dataset
    section (:mod:`pii_guard.eval.datasets.ci`, computed from per-document counts)."""
    out = [
        "<!-- Generated by `pii-guard eval report` from eval/results/runs/; do not edit. -->\n",
        "# Benchmarks\n",
        "Every evaluation run of pii-guard and of the open-source tools it is compared with, "
        "on fictional data only. Each run is one JSON record in "
        "[`eval/results/runs/`](../eval/results/runs/) (format: "
        "[evaluation.md](evaluation.md#run-records)); this page, the charts and "
        "the index (`eval/results/index.json`, written locally) are generated from them. "
        "The same data is browsable in the UI's **Benchmarks** tab.\n",
        f"Headline fixture set: **{headline_set}** ({_set_line(index, headline_set)}). "
        "Default pipeline in **bold**.\n",
    ]
    for name, title, _ in CHARTS:
        if not _drawn(index, name):
            continue
        out.append(f"![{title}](benchmarks/{name})\n")
    out.append(_METHOD)
    text_sets = [n for n, v in index["fixture_sets"].items() if v["kind"] == "text"]
    text_sets.sort(key=lambda n: (n != headline_set, n))
    out.append("## Results by fixture set\n")
    out.append(
        "Latest run of each system on each set, on the current version of each fixture file; "
        "`all` pools the languages (micro-averaged).\n"
    )
    for name in text_sets:
        out.append(f"### `{name}`\n")
        out.append(f"{_set_line(index, name)}.\n")
        out.append(_set_table(index, name))
        out.append("\nBy language:\n")
        out.append(_language_table(index, name))
        out.append(_validity_section(index, name))
        stale = _stale_table(index, name)
        if stale:
            out.append(stale)
    if datasets_section:
        out.append(datasets_section)
    out.append(f"## Recall per entity type (`{headline_set}`)\n")
    out.append(
        "Featured systems run on every language of the current fixture files, pooled "
        "(micro-averaged).\n"
    )
    out.append(_type_table(index, headline_set, featured))
    if index["visual"]:
        out.append("## Image masking\n")
        out.append(
            "Share of labeled regions masked with IoU >= 0.5. `specimens` are official "
            "specimen ID documents published by their issuers; `fictional-specimens` are "
            "specimen-style documents built from Muse Image output (LAB-1121). The two sets "
            "hold different documents, so compare runs within a set.\n"
        )
        out.append(_visual_table(index))
    if any(charts.is_segment_run(r) for r in index["visual"]):
        out.append("## Segmenters: SAM 3.1 API vs on-device\n")
        out.append(
            "Portraits and signatures only, no OCR (`python -m pii_guard.visual.segment_eval`, "
            "LAB-1229): SAM 3.1 on the Meta API against on-device candidates. Latency is per "
            "image on the CPU of the machine in each run's hardware note (SAM: its API calls). "
            "Leak, precision, memory and model size are in each run's notes and in "
            "[models.md](models.md#local-segmentation).\n"
        )
        out.append(_segmenter_table(index))
    if index.get("latency"):
        out.append("## Gateway latency\n")
        out.append(
            "What the gateway adds to an LLM call, measured by `pii-guard bench latency` against "
            "the mock upstream with a fixed delay, so the upstream's own time is taken out: "
            "overhead = gateway total - time waiting on the upstream. Streams also report the "
            "added time to the first token. Each request is a new session (no cache hits). "
            "Stages and fields: [operations.md](operations.md#timing).\n"
        )
        out.append(_latency_table(index))
    out.append("## Run log\n")
    out.append(
        "Newest first. `imported` runs were converted from earlier scorecards and Linear/PR "
        "notes; `recorded` ones were written by `pii-guard eval --record`. Audit mode was "
        "called `strict` until LAB-1186: run IDs ending in `-strict` are audit-mode runs, "
        "kept under their original IDs.\n"
    )
    out.append(_run_log(index))
    out.append(
        "\nAdd a run: `uv run pii-guard eval --fixtures eval/fixtures/hu-smoke.jsonl "
        "--detectors rules --record my-change`. That writes the record and regenerates this "
        "page; commit both. Details: [evaluation.md](evaluation.md#run-records).\n"
    )
    return "\n".join(out)


# --- Outputs ------------------------------------------------------------------------------


def _read_config(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RecordError(f"{path}: {exc}") from exc
    if not isinstance(data, dict):
        raise RecordError(f"{path}: must be a JSON object")
    return data


def load_config(path: Path) -> tuple[str, list[str]]:
    data = _read_config(path)
    headline = data.get("headline_set")
    featured = data.get("featured")
    if not isinstance(headline, str) or not isinstance(featured, list):
        raise RecordError(f"{path}: needs 'headline_set' (string) and 'featured' (list)")
    return headline, [str(k) for k in featured]


def build_outputs(
    runs_dir: Path = DEFAULT_RUNS_DIR,
    *,
    config: Path = DEFAULT_CONFIG,
    index_path: Path = DEFAULT_INDEX,
    ui_index_path: Path | None = None,
    docs_dir: Path = DEFAULT_DOCS_DIR,
    colours: Path = DEFAULT_REGISTRY,
    readme: Path = DEFAULT_README,
) -> dict[Path, str | Raster]:
    """Every generated file and its content, from the records in ``runs_dir``.

    ``colours`` is the append-only color registry; it is an output too, so a new system's
    color is committed with it and ``--check`` fails until it is. ``readme`` is an output
    only when the config has a ``readme`` section: its results block is rewritten.
    """
    records = load_records(runs_dir)
    if not records:
        raise RecordError(f"no run records in {runs_dir}")
    headline, featured = load_config(config)
    digests = {p.name: file_sha256(p) for p in sorted(runs_dir.glob("*.json"))}
    registry = load_registry(colours)
    index = build_index(records, featured=featured, digests=digests, colours=registry)
    if headline not in index["fixture_sets"]:
        raise RecordError(f"{config}: headline_set {headline!r} has no runs")
    index["headline_set"] = headline  # the UI opens on it
    systems = index["featured"]
    outputs: dict[Path, str | Raster] = {
        colours: dumps_registry(registry),
        index_path: json.dumps(index, indent=2, ensure_ascii=False) + "\n",
    }
    if ui_index_path is not None:
        outputs[ui_index_path] = compact_index(index) + "\n"
    for name, _, render in CHARTS:
        if not _drawn(index, name):
            continue
        svg = render(index, headline, systems)
        outputs[docs_dir / "benchmarks" / name] = svg
        outputs[docs_dir / "benchmarks" / name.replace(".svg", "-dark.svg")] = charts.dark_variant(
            svg
        )
    for name in validity_sets(index):
        svg = charts.number_validity(index, fixture_set=name)
        outputs[docs_dir / "benchmarks" / validity_chart(name)] = svg
        outputs[docs_dir / "benchmarks" / validity_chart(name).replace(".svg", "-dark.svg")] = (
            charts.dark_variant(svg)
        )
    counts = _dataset_counts(runs_dir)
    outputs[docs_dir / "benchmarks.md"] = render_page(
        index, headline_set=headline, featured=systems, datasets_section=_datasets_section(counts)
    )
    raw_share = _read_config(config).get("share")
    if raw_share is not None:
        share = parse_share_spec(raw_share, str(config))
        fonts = docs_dir / "benchmarks" / "fonts"
        for stem, svg in render_share(index, share).items():
            outputs[docs_dir / "benchmarks" / f"{stem}.svg"] = svg
            outputs[docs_dir / "benchmarks" / f"{stem}.png"] = Raster(svg, fonts)
    raw_readme = _read_config(config).get("readme")
    if raw_readme is not None:
        spec = parse_readme_spec(raw_readme, str(config))
        if "model_latency" in spec:
            ml = spec["model_latency"]
            path = Path(config).resolve().parents[2] / ml["file"]
            try:
                ml["data"] = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                raise RecordError(f"{config}: model_latency {ml['file']!r}: {exc}") from exc
        try:
            doc = readme.read_text(encoding="utf-8")
        except OSError as exc:
            raise RecordError(f"{readme}: {exc}") from exc
        outputs[readme] = render_readme(doc, index, counts, spec, str(readme))
    return outputs


def _dataset_counts(runs_dir: Path) -> list[dict[str, Any]]:
    """The per-dataset counts next to ``runs_dir`` (``eval/datasets/results``), oldest first."""
    from pii_guard.eval.datasets.ci import load_counts

    return load_counts(runs_dir.resolve().parent.parent / "datasets" / "results")


def _datasets_section(counts: Sequence[Mapping[str, Any]]) -> str:
    """Per-dataset CIs from the counts (:mod:`pii_guard.eval.datasets.ci`)."""
    from pii_guard.eval.datasets import REGISTRY
    from pii_guard.eval.datasets.ci import render_section

    order = [(d.name, d.title, d.split) for d in REGISTRY.values()]
    return render_section(counts, order)


def current_index(root: Path = Path()) -> dict[str, Any]:
    """The index of the repository at ``root``, as ``pii-guard eval report`` builds it."""
    index_path = root / DEFAULT_INDEX
    outputs = build_outputs(
        root / DEFAULT_RUNS_DIR,
        config=root / DEFAULT_CONFIG,
        index_path=index_path,
        docs_dir=root / DEFAULT_DOCS_DIR,
        colours=root / DEFAULT_REGISTRY,
        readme=root / DEFAULT_README,
    )
    index: dict[str, Any] = json.loads(str(outputs[index_path]))
    return index


def compact_index(index: Mapping[str, Any]) -> str:
    """The index on one line, as the UI bundles it."""
    return json.dumps(index, ensure_ascii=False, separators=(",", ":"))


def journey_output(
    journey: Path = DEFAULT_JOURNEY, entries_dir: Path = DEFAULT_ENTRIES_DIR
) -> tuple[Path, str] | None:
    """``docs/journey.md`` with its generated block rebuilt from ``entries_dir``.

    ``None`` when there is no journey at all (no document, no entries), as in a scratch copy
    of the run records.
    """
    try:
        entries = load_entries(entries_dir)
        if not journey.is_file() and not entries:
            return None
        doc = journey.read_text(encoding="utf-8")
        return journey, render_journey(doc, entries, journey_path=journey)
    except JourneyError as exc:
        raise RecordError(str(exc)) from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pii-guard eval report",
        description="Build eval/results/index.json, the charts and docs/benchmarks.md "
        "from the run records.",
    )
    parser.add_argument("--runs-dir", type=Path, default=DEFAULT_RUNS_DIR)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument(
        "--index",
        type=Path,
        default=DEFAULT_INDEX,
        help="where to write the index for local use (not committed, not checked)",
    )
    parser.add_argument(
        "--ui-index",
        type=Path,
        default=None,
        help="also write the compact index here (the UI build uses --print-index instead)",
    )
    parser.add_argument(
        "--docs-dir", type=Path, default=DEFAULT_DOCS_DIR, help="benchmarks.md + benchmarks/"
    )
    parser.add_argument(
        "--colours",
        type=Path,
        default=DEFAULT_REGISTRY,
        help="append-only system -> colour registry",
    )
    parser.add_argument(
        "--readme",
        type=Path,
        default=DEFAULT_README,
        help="its results block is rewritten when the config has a 'readme' section",
    )
    parser.add_argument(
        "--journey-dir",
        type=Path,
        default=DEFAULT_ENTRIES_DIR,
        help="one file per journey milestone",
    )
    parser.add_argument("--journey-doc", type=Path, default=DEFAULT_JOURNEY)
    parser.add_argument(
        "--journey",
        action="store_true",
        help="also fold the journey entries into docs/journey.md (written or, with --check, "
        "compared); without it they are only validated",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--check",
        action="store_true",
        help="write nothing; exit 1 if any committed output is missing or stale",
    )
    mode.add_argument(
        "--validate",
        action="store_true",
        help="write nothing, compare nothing: exit 0 if every input is valid and every output "
        "builds (pull requests, when the render-docs workflow renders after merge)",
    )
    mode.add_argument(
        "--print-index",
        action="store_true",
        help="write nothing; print the compact index on stdout",
    )
    return parser


def _current(path: Path, content: str | Raster) -> bool:
    """Whether the committed ``path`` matches: text byte for byte, a PNG by its stamp."""
    if isinstance(content, Raster):
        return content.is_current(path)
    return path.is_file() and path.read_text(encoding="utf-8") == content


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    ui_index = args.ui_index if args.ui_index is not None and str(args.ui_index) != "." else None
    try:
        outputs = build_outputs(
            args.runs_dir,
            config=args.config,
            index_path=args.index,
            ui_index_path=ui_index,
            docs_dir=args.docs_dir,
            colours=args.colours,
            readme=args.readme,
        )
        # Always rendered, so a broken entry fails every mode; written or compared only on
        # --journey, so pull requests that add an entry never touch docs/journey.md.
        if args.print_index:
            sys.stdout.write(compact_index(json.loads(str(outputs[args.index]))) + "\n")
            return 0
        journey = journey_output(args.journey_doc, args.journey_dir)
    except (OSError, json.JSONDecodeError, RecordError) as exc:
        print(f"pii-guard eval report: {exc}", file=sys.stderr)
        return 2
    local = {args.index} | ({ui_index} if ui_index is not None else set())
    if args.validate:
        print(
            f"pii-guard eval report: inputs valid; {len(outputs) - len(local)} outputs build"
            + (", and the journey" if journey else "")
        )
        return 0
    if args.journey and journey is not None:
        outputs[journey[0]] = journey[1]
    stale = [path for path, content in outputs.items() if not _current(path, content)]
    if args.check:
        stale = [p for p in stale if p not in local]
        if stale:
            print(
                "pii-guard eval report: stale or missing (run `uv run pii-guard eval report` "
                "and commit): " + ", ".join(str(p) for p in stale),
                file=sys.stderr,
            )
            return 1
        checked = len(outputs) - len(local)
        print(f"pii-guard eval report: {checked} generated files are up to date")
        return 0
    try:
        for path in stale:
            path.parent.mkdir(parents=True, exist_ok=True)
            content = outputs[path]
            if isinstance(content, Raster):
                path.write_bytes(content.render())
            else:
                path.write_text(content, encoding="utf-8")
            print(f"wrote {path}")
    except RecordError as exc:
        print(f"pii-guard eval report: {exc}", file=sys.stderr)
        return 2
    if not stale:
        print(f"pii-guard eval report: {len(outputs)} generated files already up to date")
    return 0


if __name__ == "__main__":  # ``python -m pii_guard.eval.report_cli``: the UI build calls it
    raise SystemExit(main())
