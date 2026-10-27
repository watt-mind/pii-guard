"""``pii-guard eval report``: build the benchmark index, charts and page from the run records.

```
pii-guard eval report            # rewrite whatever is stale
pii-guard eval report --check    # exit 1 if anything committed is stale (CI)
```

Inputs: every run record in ``eval/results/runs/`` (validated against the schema) and
``docs/benchmarks/config.json`` (headline fixture set and featured systems). Outputs, all a
pure function of the inputs so ``--check`` compares them byte for byte:

- ``eval/results/index.json``: the index (:mod:`pii_guard.eval.report_index`);
- ``ui/src/api/benchmarks.index.json``: the same index, compact, bundled into the UI;
- ``docs/benchmarks/*.svg``: the charts (:mod:`pii_guard.eval.report_charts`);
- ``docs/benchmarks.md``: tables, embedded charts and method notes.

Exit codes: 0 up to date (or written), 1 stale under ``--check``, 2 bad input (an invalid
run record, an unreadable config).
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
from pii_guard.eval.report_index import build_index

__all__ = ["CHARTS", "build_outputs", "build_parser", "main", "render_page"]

DEFAULT_INDEX = Path("eval/results/index.json")
DEFAULT_UI_INDEX = Path("ui/src/api/benchmarks.index.json")
DEFAULT_DOCS_DIR = Path("docs")
DEFAULT_CONFIG = Path("docs/benchmarks/config.json")

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
        "Visual recall on specimen documents",
        lambda i, s, f: charts.visual_recall(i),
    ),
]


# --- Page ---------------------------------------------------------------------------------


def _pct(v: float | None) -> str:
    return "—" if v is None else f"{v * 100:.1f}%"


def _ms(v: float | None) -> str:
    return "—" if v is None else charts._ms(v)


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


def _set_table(index: Mapping[str, Any], fixture_set: str) -> str:
    rows = []
    for s in _ordered_snapshots(index, fixture_set):
        m = s["all"]
        rows.append(
            [
                _label(index, s["system"]),
                m["documents"],
                _pct(m["precision"]),
                _pct(m["recall"]),
                _pct(m["f1"]),
                _pct(m["leak"]),
                _pct(m["partial_leak"]),
                _pct(m["over_masking"]),
                _pct(m["roundtrip"]),
                _ms(m["detect_p50_ms"]) + ("*" if m["latency_pooled"] else ""),
                ", ".join(s["dates"]),
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
            "Run",
        ],
        ["---", "---:", "---:", "---:", "---:", "---:", "---:", "---:", "---:", "---:", "---"],
        rows,
    )


def _language_table(index: Mapping[str, Any], fixture_set: str) -> str:
    snaps = _ordered_snapshots(index, fixture_set)
    langs = [lang for lang in index["languages"] if any(lang in s["languages"] for s in snaps)]
    header = ["System"] + [f"{lang} F1" for lang in langs] + [f"{lang} leak" for lang in langs]
    rows = []
    for s in snaps:
        f1 = [_pct(s["languages"].get(lang, {}).get("f1")) for lang in langs]
        leak = [_pct(s["languages"].get(lang, {}).get("leak")) for lang in langs]
        rows.append([_label(index, s["system"]), *f1, *leak])
    return _table(header, ["---"] + ["---:"] * (2 * len(langs)), rows)


def _type_table(index: Mapping[str, Any], fixture_set: str, systems: Sequence[str]) -> str:
    snaps = [s for s in _ordered_snapshots(index, fixture_set) if s["system"] in systems]
    types = [t for t in index["entity_types"] if any(t in s["all"]["per_type"] for s in snaps)]
    header = ["Type", "Gold", *(index["systems"][s["system"]]["short_label"] for s in snaps)]
    rows = []
    for t in types:
        gold = max((s["all"]["per_type"].get(t, {}).get("gold") or 0) for s in snaps)
        rows.append(
            [f"`{t}`", gold, *(_pct(s["all"]["per_type"].get(t, {}).get("recall")) for s in snaps)]
        )
    return _table(header, ["---", "---:"] + ["---:"] * len(snaps), rows)


def _visual_table(index: Mapping[str, Any]) -> str:
    region_types: list[str] = []
    for r in index["visual"]:
        region_types += [k for k in r["by_region_type"] if k not in region_types]
    rows = []
    for r in index["visual"]:
        per = [_pct((r["by_region_type"].get(k) or {}).get("recall_iou50")) for k in region_types]
        rows.append(
            [
                f"`{r['run_id']}`",
                r["specimens"],
                r["countries"],
                *per,
                _pct(r["overall"]["recall_iou50"]),
                _pct(r["over_masking_mean"]),
            ]
        )
    return _table(
        ["Run", "Images", "Countries", *region_types, "All regions", "Over-masking (mean)"],
        ["---", "---:", "---:"] + ["---:"] * (len(region_types) + 2),
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
    for run in reversed(index["runs"]):
        style = index["systems"].get(run["system"], {})
        rows.append(
            [
                run["date"],
                f"`{run['run_id']}`",
                style.get("label", run["system"]),
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

- **Leak rate** is the share of labelled values that still appear, in any surface form, in
  the text the model would receive after masking (case- and whitespace-insensitive, through
  the language's inflected forms, structured identifiers by their letters and digits with any
  separators). Lower is safer; it is the number that matters most. **Partial leak** counts
  values not leaked whole but with an identifying token left (the street of an address whose
  postcode alone was masked). Details: [evaluation.md](evaluation.md#leak-rate-in-practice).
- **Precision, recall, F1** are span-level with overlap matching (a prediction counts if it
  overlaps a gold span of the same type); the run records also keep exact-match numbers.
  **Over-masking** is the share of masked characters outside any gold span. **Round trip** is
  the share of documents that unmask back to the original text exactly (comparison tools that
  can't unmask show —).
- **Hand-written vs generated sets.** `smoke` is written by hand with inline labels and has
  adversarial look-alikes; `synth-*` sets are written by a Meta Muse model around fictional
  identities and labelled automatically. **Generated sets flatter Muse-based detectors**: the
  same model family wrote the text and reads it, so its phrasing and its idea of what an
  entity is match. The headline charts use the hand-written set for that reason.
- **Small sets.** The sets have tens of documents per language: differences of a few points
  are noise. Every number below says which set, which run date and which commit it came from.
- **Latency** is detection time per document (p50) on the hardware in the run log; it is not
  comparable across machines. `*` marks a value averaged over several runs (percentiles
  can't be pooled exactly). Every count-based metric is pooled exactly over languages.
- `rules` is the rules-only pass with no name detection; names and addresses come from the
  NER and LLM passes. Compare it with the other tools on structured identifiers.
"""


def render_page(index: Mapping[str, Any], *, headline_set: str, featured: Sequence[str]) -> str:
    """``docs/benchmarks.md``: a pure function of the index and the config."""
    out = [
        "<!-- Generated by `pii-guard eval report` from eval/results/runs/; do not edit. -->\n",
        "# Benchmarks\n",
        "Every evaluation run of pii-guard and of the open-source tools it is compared with, "
        "on fictional data only. Each run is one JSON record in "
        "[`eval/results/runs/`](../eval/results/runs/) (format: "
        "[evaluation.md](evaluation.md#run-records)); this page, the charts and "
        "[`eval/results/index.json`](../eval/results/index.json) are generated from them. "
        "The same data is browsable in the UI's **Benchmarks** tab.\n",
        f"Headline fixture set: **{headline_set}** ({_set_line(index, headline_set)}). "
        "Default pipeline in **bold**.\n",
    ]
    for name, title, _ in CHARTS:
        if name == "visual-recall.svg" and not index["visual"]:
            continue
        out.append(f"![{title}](benchmarks/{name})\n")
    out.append(_METHOD)
    text_sets = [n for n, v in index["fixture_sets"].items() if v["kind"] == "text"]
    text_sets.sort(key=lambda n: (n != headline_set, n))
    out.append("## Results by fixture set\n")
    out.append("Latest run of each system on each set; `all` pools every language exactly.\n")
    for name in text_sets:
        out.append(f"### `{name}`\n")
        out.append(f"{_set_line(index, name)}.\n")
        out.append(_set_table(index, name))
        out.append("\nBy language:\n")
        out.append(_language_table(index, name))
    out.append(f"## Recall per entity type (`{headline_set}`)\n")
    out.append(_type_table(index, headline_set, featured))
    if index["visual"]:
        out.append("## Image masking (specimen documents)\n")
        out.append(
            "Share of labelled regions masked with IoU >= 0.5, on official specimen ID "
            "documents published by their issuers.\n"
        )
        out.append(_visual_table(index))
    out.append("## Run log\n")
    out.append(
        "Newest first. `imported` runs were converted from earlier scorecards and Linear/PR "
        "notes; `recorded` ones were written by `pii-guard eval --record`.\n"
    )
    out.append(_run_log(index))
    out.append(
        "\nAdd a run: `uv run pii-guard eval --fixtures eval/fixtures/hu-smoke.jsonl "
        "--detectors rules --record my-change`. That writes the record and regenerates this "
        "page; commit both. Details: [evaluation.md](evaluation.md#run-records).\n"
    )
    return "\n".join(out)


# --- Outputs ------------------------------------------------------------------------------


def load_config(path: Path) -> tuple[str, list[str]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RecordError(f"{path}: {exc}") from exc
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
    ui_index_path: Path | None = DEFAULT_UI_INDEX,
    docs_dir: Path = DEFAULT_DOCS_DIR,
) -> dict[Path, str]:
    """Every generated file and its content, from the records in ``runs_dir``."""
    records = load_records(runs_dir)
    if not records:
        raise RecordError(f"no run records in {runs_dir}")
    headline, featured = load_config(config)
    digests = {p.name: file_sha256(p) for p in sorted(runs_dir.glob("*.json"))}
    index = build_index(records, featured=featured, digests=digests)
    if headline not in index["fixture_sets"]:
        raise RecordError(f"{config}: headline_set {headline!r} has no runs")
    index["headline_set"] = headline  # the UI opens on it
    systems = index["featured"]
    outputs = {index_path: json.dumps(index, indent=2, ensure_ascii=False) + "\n"}
    if ui_index_path is not None:
        compact = json.dumps(index, ensure_ascii=False, separators=(",", ":"))
        outputs[ui_index_path] = compact + "\n"
    for name, _, render in CHARTS:
        if name == "visual-recall.svg" and not index["visual"]:
            continue
        outputs[docs_dir / "benchmarks" / name] = render(index, headline, systems)
    outputs[docs_dir / "benchmarks.md"] = render_page(
        index, headline_set=headline, featured=systems
    )
    return outputs


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pii-guard eval report",
        description="Build eval/results/index.json, the charts and docs/benchmarks.md "
        "from the run records.",
    )
    parser.add_argument("--runs-dir", type=Path, default=DEFAULT_RUNS_DIR)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--index", type=Path, default=DEFAULT_INDEX, help="index.json path")
    parser.add_argument(
        "--ui-index",
        type=Path,
        default=DEFAULT_UI_INDEX,
        help="copy of the index bundled into the UI ('' to skip)",
    )
    parser.add_argument(
        "--docs-dir", type=Path, default=DEFAULT_DOCS_DIR, help="benchmarks.md + benchmarks/"
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="write nothing; exit 1 if any generated file is missing or stale",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    ui_index = args.ui_index if str(args.ui_index) not in ("", ".") else None
    try:
        outputs = build_outputs(
            args.runs_dir,
            config=args.config,
            index_path=args.index,
            ui_index_path=ui_index,
            docs_dir=args.docs_dir,
        )
    except (OSError, json.JSONDecodeError, RecordError) as exc:
        print(f"pii-guard eval report: {exc}", file=sys.stderr)
        return 2
    stale = [
        path
        for path, content in outputs.items()
        if not path.is_file() or path.read_text(encoding="utf-8") != content
    ]
    if args.check:
        if stale:
            print(
                "pii-guard eval report: stale or missing (run `uv run pii-guard eval report` "
                "and commit): " + ", ".join(str(p) for p in stale),
                file=sys.stderr,
            )
            return 1
        print(f"pii-guard eval report: {len(outputs)} generated files are up to date")
        return 0
    for path in stale:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(outputs[path], encoding="utf-8")
        print(f"wrote {path}")
    if not stale:
        print(f"pii-guard eval report: {len(outputs)} generated files already up to date")
    return 0
