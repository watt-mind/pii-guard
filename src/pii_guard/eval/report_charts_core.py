"""SVG primitives, dark-theme conversion, and snapshot helpers for benchmark charts."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from html import escape
from typing import Any

from pii_guard.eval.report_index import display_mode
from pii_guard.eval.stats import fmt_duration, fmt_pct

W, H = 1600, 900
FONT = "Inter, 'Helvetica Neue', Helvetica, Arial, sans-serif"
INK = "#1B1B1F"
MUTED = "#4A4A52"
GRID = "#E3E3E8"
AXIS = "#8A8A93"
BG = "#FFFFFF"
#: Dark-canvas counterparts of the light card, for the `*-dark.svg` variants (LAB-1238).
DARK_BG = "#111318"
DARK_INK = "#F2F2F5"
DARK_MUTED = "#B8B8C0"
DARK_GRID = "#33333A"
#: Language colors (Paul Tol bright/muted, colour-blind safe), assigned in index order.
LANG_COLORS = ["#332288", "#44AA99", "#DDCC77", "#CC6677", "#88CCEE", "#AA4499", "#117733"]


# --- SVG primitives -----------------------------------------------------------------------


def _n(x: float) -> str:
    """A coordinate with at most one decimal, no trailing zeros (stable text)."""
    s = f"{x:.1f}"
    return s[:-2] if s.endswith(".0") else s


def text_width(text: str, size: float, *, bold: bool = False) -> float:
    """Approximate rendered width of ``text`` in a Helvetica-like font."""
    narrow = sum(text.count(c) for c in "il.,:;|!'()[] 1tfjr")
    wide = sum(text.count(c) for c in "MW@%mw")
    caps = sum(1 for c in text if c.isupper()) - wide
    rest = len(text) - narrow - wide - max(caps, 0)
    em = narrow * 0.3 + wide * 0.85 + max(caps, 0) * 0.66 + rest * 0.55
    return em * size * (1.06 if bold else 1.0)


def _text(
    x: float,
    y: float,
    content: str,
    *,
    size: float = 22,
    fill: str = INK,
    anchor: str = "start",
    weight: str | None = None,
    extra: str = "",
) -> str:
    attrs = f'x="{_n(x)}" y="{_n(y)}" font-size="{_n(size)}" fill="{fill}"'
    if anchor != "start":
        attrs += f' text-anchor="{anchor}"'
    if weight:
        attrs += f' font-weight="{weight}"'
    return f"<text {attrs}{extra}>{escape(content)}</text>"


def _marker(shape: str, x: float, y: float, r: float, color: str, *, hollow: bool = False) -> str:
    fill = BG if hollow else color
    stroke = f'stroke="{color if hollow else BG}" stroke-width="{4 if hollow else 3}"'
    if shape == "square":
        s = r * 1.7
        return (
            f'<rect x="{_n(x - s / 2)}" y="{_n(y - s / 2)}" width="{_n(s)}" height="{_n(s)}" '
            f'fill="{fill}" {stroke}/>'
        )
    if shape == "triangle":
        pts = [(x, y - r * 1.15), (x + r * 1.1, y + r * 0.8), (x - r * 1.1, y + r * 0.8)]
        return (
            f'<polygon points="{" ".join(f"{_n(a)},{_n(b)}" for a, b in pts)}" fill="{fill}" '
            f"{stroke}/>"
        )
    if shape == "diamond":
        pts = [(x, y - r * 1.25), (x + r * 1.25, y), (x, y + r * 1.25), (x - r * 1.25, y)]
        return (
            f'<polygon points="{" ".join(f"{_n(a)},{_n(b)}" for a, b in pts)}" fill="{fill}" '
            f"{stroke}/>"
        )
    if shape == "cross":
        d = r * 0.9
        a, b, c, e = _n(x - d), _n(y - d), _n(x + d), _n(y + d)
        return (
            f'<path d="M{a},{b}L{c},{e}M{a},{e}L{c},{b}" '
            f'stroke="{color}" stroke-width="5" fill="none"/>'
        )
    return f'<circle cx="{_n(x)}" cy="{_n(y)}" r="{_n(r)}" fill="{fill}" {stroke}/>'


def _svg(title: str, desc: str, body: Sequence[str], caption: Sequence[str]) -> str:
    """The SVG document: background, title block, ``body``, and the caption lines at the bottom."""
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" '
        f'role="img" aria-labelledby="t d" font-family="{escape(FONT, quote=True)}">',
        f'<title id="t">{escape(title)}</title>',
        f'<desc id="d">{escape(desc)}</desc>',
        f'<rect width="{W}" height="{H}" fill="{BG}"/>',
        _text(56, 70, title, size=40, weight="700"),
    ]
    out.extend(body)
    y = H - 30 - 30 * (len(caption) - 1)
    for line in caption:
        out.append(_text(56, y, line, size=20, fill=MUTED))
        y += 30
    out.append("</svg>")
    return "\n".join(out) + "\n"


def dark_variant(svg: str) -> str:
    """The `*-dark.svg` twin of a chart: the same drawing on a dark card (LAB-1238).

    Only the card chrome is swapped (background, ink, muted caption/axis text, grid);
    data colors stay as-is so a series keeps its color across themes.
    """
    return (
        svg.replace(BG, DARK_BG)
        .replace(INK, DARK_INK)
        .replace(MUTED, DARK_MUTED)
        .replace(GRID, DARK_GRID)
    )


def _short(commit: str) -> str:
    return commit[:7]


def _span(dates: Sequence[str]) -> str:
    ds = sorted(set(dates))
    if not ds:
        return "no runs"
    return ds[0] if len(ds) == 1 else f"{ds[0]} to {ds[-1]}"


def set_caption(index: Mapping[str, Any], fixture_set: str) -> str:
    """``smoke: hand-written, hu 28 docs + en 10 docs`` (the n always goes with the set)."""
    info = index["fixture_sets"].get(fixture_set, {})
    docs = info.get("documents", {})
    parts = " + ".join(f"{lang} {n} docs" for lang, n in docs.items())
    origin = info.get("origin", "unknown")
    if origin == "generated":
        origin = "generated by " + (", ".join(info.get("generators") or []) or "a model")
    return f"Fixture set '{fixture_set}' ({origin}; {parts})"


def _snapshots(
    index: Mapping[str, Any],
    fixture_set: str,
    systems: Sequence[str],
    *,
    complete: bool = False,
) -> list[dict[str, Any]]:
    """Snapshots of ``systems`` on the set's current fixture files; with ``complete``, only
    those covering every current language (the only ones whose pooled numbers compare)."""
    by_key = {s["system"]: s for s in index["snapshots"] if s["fixture_set"] == fixture_set}
    snaps = [by_key[k] for k in systems if k in by_key]
    return [s for s in snaps if s.get("complete", True)] if complete else snaps


def pooled_languages(index: Mapping[str, Any], fixture_set: str) -> str:
    """``de + en + hu pooled (micro-averaged)``, from the set's current languages."""
    langs = list(index["fixture_sets"].get(fixture_set, {}).get("fixtures") or {})
    if not langs:
        langs = index["fixture_sets"].get(fixture_set, {}).get("languages") or []
    if len(langs) <= 1:
        return f"{langs[0] if langs else 'one language'} only"
    return " + ".join(langs) + " pooled (micro-averaged)"


def _left_out(
    index: Mapping[str, Any], fixture_set: str, systems: Sequence[str], shown: Sequence[Any]
) -> str | None:
    """A caption line naming featured systems a pooled chart leaves out, or ``None``."""
    keys = {s["system"] for s in shown}
    out = [k for k in systems if k in index["systems"] and k not in keys]
    if not out:
        return None
    langs = " + ".join(index["fixture_sets"].get(fixture_set, {}).get("fixtures") or {})
    names = ", ".join(index["systems"][k]["short_label"] for k in out)
    return f"Not shown, not run on every current fixture file ({langs}): {names}."


def _provenance(snaps: Sequence[Mapping[str, Any]]) -> str:
    dates = [d for s in snaps for d in s["dates"]]
    commits = sorted({_short(c) for s in snaps for c in s["commits"]})
    line = (
        f"Runs {_span(dates)} · commits {', '.join(commits)} · generated by `pii-guard eval "
        "report` from eval/results/runs/"
    )
    if text_width(line, 20) > W - 112:  # too many to list: the run log has them
        line = (
            f"Runs {_span(dates)} · {len(commits)} commits (run log in docs/benchmarks.md) · "
            "generated by `pii-guard eval report` from eval/results/runs/"
        )
    return line


_VISUAL_SETS = {
    "specimens": "official specimen ID documents",
    "fictional-specimens": "fictional, Muse Image",
}


#: System-key prefix of segmenter-only runs (``pii_guard.visual.segment_eval``, LAB-1229).
SEGMENT_PREFIX = "visual-segment:"


def is_segment_run(run: Mapping[str, Any]) -> bool:
    return str(run["system"]).startswith(SEGMENT_PREFIX)


def _visual_group_bars(
    g: int,
    name: str,
    runs: Sequence[Mapping[str, Any]],
    set_order: Sequence[str],
    color: Mapping[str, str],
    layout: tuple[float, float, float, float, float, Callable[[float], float]],
) -> list[str]:
    px0, py1, gw, bw, slots, sy = layout
    gap = 0.4
    gx = px0 + g * gw + (gw - bw * slots) / 2
    cand: list[tuple[float, float]] = []
    for k, r in enumerate(runs):
        block = r["overall"] if name == "all" else r["by_region_type"].get(name)
        if block:
            v = block["recall_iou50"] or 0
            set_index = set_order.index(str(r.get("fixture_set") or "specimens"))
            cand.append((gx + (k + gap * set_index) * bw, v))
    label_all = bw >= 30 or not cand
    best_x = max(cand, key=lambda t: t[1])[0] if cand else 0.0
    ns: list[int] = []
    out: list[str] = []
    for k, r in enumerate(runs):
        block = r["overall"] if name == "all" else r["by_region_type"].get(name)
        if not block:
            continue
        if block["regions"] not in ns:
            ns.append(block["regions"])
        v = block["recall_iou50"] or 0
        set_index = set_order.index(str(r.get("fixture_set") or "specimens"))
        x = gx + (k + gap * set_index) * bw
        out.append(
            f'<rect x="{_n(x + 3)}" y="{_n(sy(v))}" width="{_n(bw - 6)}" '
            f'height="{_n(max(py1 - sy(v), 1))}" fill="{color[str(r["system"])]}"/>'
        )
        if label_all or x == best_x:
            out.append(
                _text(
                    x + bw / 2,
                    sy(v) - 10,
                    fmt_pct(v, 0),
                    size=19 if bw >= 34 else 18,
                    anchor="middle",
                )
            )
    out.append(_text(px0 + (g + 0.5) * gw, py1 + 34, name, size=21, anchor="middle", weight="600"))
    out.append(
        _text(
            px0 + (g + 0.5) * gw,
            py1 + 60,
            "n=" + " / ".join(map(str, ns)),
            size=19,
            fill=MUTED,
            anchor="middle",
        )
    )
    return out


# --- Gateway latency ----------------------------------------------------------------------

#: Stage colors (Okabe-Ito), in pipeline order; ``other`` is untimed glue (HTTP, scheduling).
STAGE_COLORS = {
    "parse": "#56B4E9",
    "detect": "#0072B2",
    "image": "#CC79A7",
    "mask": "#009E73",
    "forward": "#E69F00",
    "unmask": "#D55E00",
    "response": "#F0E442",
    "other": "#BBBBBB",
}


def latest_latency(index: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """The newest latency run of each system, in first-seen order."""
    latest: dict[str, Mapping[str, Any]] = {}
    for run in index.get("latency", []):
        latest[run["system"]] = run
    return list(latest.values())


def latency_label(run: Mapping[str, Any]) -> str:
    """``fast: rules + ner (mps)`` from a latency run's system; no device, no suffix."""
    mode = str(run["system"]).split(":")[1] if ":" in str(run["system"]) else "?"
    mode = display_mode(mode)  # the key keeps a record's old mode name
    names = [d for d in run["detectors"] if d not in ("known", "visual")]
    devices = list(dict.fromkeys(run.get("devices") or []))
    suffix = f" ({', '.join(devices)})" if devices else ""
    return f"{mode}: " + (" + ".join(names) or "none") + suffix


def stage_shares(cell: Mapping[str, Any]) -> list[tuple[str, float]]:
    """p50 of each own stage, plus ``other`` = overhead p50 minus their sum (>= 0)."""
    stages = cell["stages_ms"]
    out = [
        (name, float((stages.get(name) or {}).get("p50") or 0.0))
        for name in STAGE_COLORS
        if name != "other"
    ]
    overhead = float((cell["overhead_ms"] or {}).get("p50") or 0.0)
    out.append(("other", max(overhead - sum(v for _, v in out), 0.0)))
    return out


def _latency_stage_panel(runs: Sequence[Mapping[str, Any]]) -> list[str]:
    rx0, rx1 = 1080, 1544
    out = [_text(rx0 - 20, 165, "Where it goes (p50, c=1, not streamed)", size=24, weight="700")]
    ry = 210
    step = min(110, 610 // max(len(runs), 1))  # keep the stage legend inside the canvas
    for run in runs:
        cell = next(
            (c for c in run["cells"] if c["concurrency"] == 1 and not c["stream"]),
            run["cells"][0] if run["cells"] else None,
        )
        if cell is None:
            continue
        shares = stage_shares(cell)
        total = sum(v for _, v in shares) or 1.0
        out.append(_text(rx0 - 20, ry, latency_label(run), size=20, weight="600"))
        x = float(rx0 - 20)
        width = rx1 - (rx0 - 20)
        for name, v in shares:
            w = v / total * width
            if w <= 0:
                continue
            out.append(
                f'<rect x="{_n(x)}" y="{ry + 12}" width="{_n(w)}" height="40" '
                f'fill="{STAGE_COLORS[name]}"/>'
            )
            if w >= 70:
                ink = BG if name in ("detect", "unmask") else INK
                out.append(
                    _text(x + w / 2, ry + 40, fmt_duration(v), size=18, fill=ink, anchor="middle")
                )
            x += w
        ry += step
    lx, ly = float(rx0 - 20), float(max(ry, 560))
    for name, color in STAGE_COLORS.items():
        tw = text_width(name, 19) + 46
        if lx + tw > rx1 + 10:
            lx, ly = float(rx0 - 20), ly + 34
        out.append(f'<rect x="{_n(lx)}" y="{_n(ly - 18)}" width="20" height="20" fill="{color}"/>')
        out.append(_text(lx + 28, ly, name, size=19))
        lx += tw
    return out
