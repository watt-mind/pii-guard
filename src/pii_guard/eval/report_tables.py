"""Markdown table builders for visual, segmenter, latency, and run-log sections."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from pii_guard.eval import report_charts as charts
from pii_guard.eval.stats import fmt_duration, fmt_pct


def _cell(text: object) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


def _table(header: Sequence[str], align: Sequence[str], rows: Sequence[Sequence[object]]) -> str:
    out = ["| " + " | ".join(header) + " |", "|" + "|".join(align) + "|"]
    out += ["| " + " | ".join(_cell(c) for c in row) + " |" for row in rows]
    return "\n".join(out) + "\n"


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
