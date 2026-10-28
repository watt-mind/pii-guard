"""Static SVG charts from the benchmark index, hand-written (no plotting dependency).

Every chart is 1600 x 900 (16:9, slide-sized: at 1920 px wide the smallest text is >= 24 px),
on a white card with dark text, colour-blind-safe colours (Okabe-Ito / Paul Tol; comparison
tools grey with distinct marker shapes) and a caption naming the fixture set, its size,
the run dates and the commits. Output depends only on the index, so it is byte-stable.

- :func:`leak_vs_latency`: full leak rate vs detection latency (log x), one point per system;
- :func:`by_language`: overlap F1 and full leak per language, per system;
- :func:`progress`: leak rate of each pii-guard system over time, with the best so far;
- :func:`type_recall_heatmap`: overlap recall per entity type and system;
- :func:`visual_recall`: image-region recall per region type, per visual run;
- :func:`number_validity`: leak rate per system, split by whether a structured identifier
  passes the language packs' validators (LAB-1201);
- :func:`latency`: what the gateway adds per request (p50 / p95 per mode, concurrency and
  streaming) and the stage breakdown of the p50 overhead.
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Mapping, Sequence
from html import escape
from typing import Any

from pii_guard.eval.report_colours import PALETTE_LATENCY, PALETTE_VISUAL, assign
from pii_guard.eval.report_index import display_mode
from pii_guard.eval.stats import fmt_duration, fmt_pct

__all__ = [
    "by_language",
    "latency",
    "leak_vs_latency",
    "number_validity",
    "progress",
    "type_recall_heatmap",
    "visual_recall",
]

W, H = 1600, 900
FONT = "Inter, 'Helvetica Neue', Helvetica, Arial, sans-serif"
INK = "#1B1B1F"
MUTED = "#4A4A52"
GRID = "#E3E3E8"
AXIS = "#8A8A93"
BG = "#FFFFFF"
#: Language colours (Paul Tol bright/muted, colour-blind safe), assigned in index order.
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


# --- (a) leak vs latency --------------------------------------------------------------------


def _place_labels(
    points: list[dict[str, Any]], box: tuple[float, float, float, float], size: float
) -> None:
    """Greedy label placement, best (lowest) point first; avoids other labels and points."""
    x0, y0, x1, y1 = box
    taken: list[tuple[float, float, float, float]] = []
    for p in points:  # markers and their p95 whiskers are obstacles too
        taken.append(
            (p["x"] - 14, p["y"] - 14, max(p["x"], p.get("x95", p["x"])) + 14, p["y"] + 14)
        )
    for p in sorted(points, key=lambda q: (-q["y"], q["x"])):  # lowest leak (best) first
        w = text_width(p["label"], size, bold=True)
        h = size * 1.2
        candidates = []
        for dy in (-30, 30, 0, -62, 62, -94, 94):
            dx = 4 if dy else 22
            candidates.append((p["x"] + dx, p["y"] + dy, "start"))
            candidates.append((p["x"] - dx, p["y"] + dy, "end"))
        choice = candidates[0]
        for cx, cy, anchor in candidates:
            left = cx if anchor == "start" else cx - w
            rect = (left - 4, cy - h / 2 - 2, left + w + 4, cy + h / 2 + 2)
            if rect[0] < x0 or rect[2] > x1 or rect[1] < y0 or rect[3] > y1:
                continue
            if any(
                not (rect[2] < t[0] or rect[0] > t[2] or rect[3] < t[1] or rect[1] > t[3])
                for t in taken
            ):
                continue
            choice = (cx, cy, anchor)
            taken.append(rect)
            break
        p["lx"], p["ly"], p["anchor"] = choice


def leak_vs_latency(index: Mapping[str, Any], *, fixture_set: str, systems: Sequence[str]) -> str:
    complete = _snapshots(index, fixture_set, systems, complete=True)
    snaps = [s for s in complete if s["all"]["detect_p50_ms"]]
    left_out = _left_out(index, fixture_set, systems, complete)
    styles = index["systems"]
    px0, py0, px1, py1 = 150, 200, 1530, 670 if left_out else 700
    lat = [s["all"]["detect_p50_ms"] for s in snaps] + [
        s["all"]["detect_p95_ms"] or 0 for s in snaps
    ]
    lo = math.floor(math.log10(min(v for v in lat if v > 0))) if snaps else -1
    hi = math.ceil(math.log10(max(lat))) if snaps else 4
    leak_max = max([s["all"]["leak"] or 0 for s in snaps] + [0.1])
    ymax = min(1.0, math.ceil(leak_max * 10 + 0.5) / 10)

    def sx(ms: float) -> float:
        return px0 + (math.log10(ms) - lo) / (hi - lo) * (px1 - px0)

    pad = ymax * 0.05  # 0% sits a little above the axis so markers there stay visible

    def sy(rate: float) -> float:
        return py1 - (rate + pad) / (ymax + pad) * (py1 - py0)

    body = [
        _text(
            56,
            112,
            "Full leak rate (lower is safer) vs detection latency per document "
            "(log scale, faster is left)",
            size=24,
            fill=MUTED,
        )
    ]
    step = 0.1 if ymax <= 0.6 else 0.2
    ticks = [round(i * step, 2) for i in range(round(ymax / step) + 1)]
    for t in ticks:
        y = sy(t)
        body.append(
            f'<line x1="{px0}" y1="{_n(y)}" x2="{px1}" y2="{_n(y)}" stroke="{GRID}" '
            'stroke-width="2"/>'
        )
        body.append(_text(px0 - 16, y + 7, f"{t * 100:.0f}%", size=20, fill=MUTED, anchor="end"))
    for e in range(lo, hi + 1):
        x = sx(10**e)
        body.append(
            f'<line x1="{_n(x)}" y1="{py0}" x2="{_n(x)}" y2="{py1}" stroke="{GRID}" '
            'stroke-width="2"/>'
        )
        body.append(_text(x, py1 + 34, fmt_duration(10.0**e), size=20, fill=MUTED, anchor="middle"))
    body.append(
        f'<line x1="{px0}" y1="{py1}" x2="{px1}" y2="{py1}" stroke="{AXIS}" stroke-width="2"/>'
    )
    body.append(
        _text(
            (px0 + px1) / 2,
            py1 + 72,
            "Detection latency per document, p50 (line to p95)",
            size=22,
            anchor="middle",
        )
    )
    body.append(
        _text(
            48,
            (py0 + py1) / 2,
            "Full leak rate",
            size=22,
            anchor="middle",
            extra=f' transform="rotate(-90 48 {_n((py0 + py1) / 2)})"',
        )
    )
    body.append(_text(px0 + 16, py1 - 16, "better ↙", size=20, fill=MUTED))

    points = []
    for s in snaps:
        st = styles[s["system"]]
        m = s["all"]
        x, y = sx(m["detect_p50_ms"]), sy(m["leak"] or 0)
        if m["detect_p95_ms"] and m["detect_p95_ms"] > m["detect_p50_ms"]:
            x95 = sx(m["detect_p95_ms"])
            body.append(
                f'<line x1="{_n(x)}" y1="{_n(y)}" x2="{_n(x95)}" y2="{_n(y)}" '
                f'stroke="{st["color"]}" stroke-width="3" opacity="0.7"/>'
            )
            body.append(
                f'<line x1="{_n(x95)}" y1="{_n(y - 9)}" x2="{_n(x95)}" y2="{_n(y + 9)}" '
                f'stroke="{st["color"]}" stroke-width="3" opacity="0.7"/>'
            )
        label = f"{st['short_label']} {fmt_pct(m['leak'])}%"
        x95 = sx(m["detect_p95_ms"]) if m["detect_p95_ms"] else x
        points.append({"x": x, "x95": x95, "y": y, "label": label, "style": st})
    _place_labels(points, (px0 + 4, py0 - 20, W - 40, py1 - 4), 22)
    for p in points:
        st = p["style"]
        hollow = st["family"] == "comparison"
        body.append(_marker(st["shape"], p["x"], p["y"], 12, st["color"], hollow=hollow))
        if abs(p["ly"] - p["y"]) > 40:  # placed away from its marker: a leader line says whose
            ly = p["ly"] + (14 if p["ly"] < p["y"] else -14)
            body.append(
                f'<line x1="{_n(p["x"])}" y1="{_n(p["y"] + (-13 if p["ly"] < p["y"] else 13))}" '
                f'x2="{_n(p["lx"])}" y2="{_n(ly)}" stroke="{MUTED}" stroke-width="1.5"/>'
            )
        body.append(
            _text(p["lx"], p["ly"] + 8, p["label"], size=22, anchor=p["anchor"], weight="600")
        )
    # Legend: ours vs comparison tools, one row under the subtitle.
    legend_a = "pii-guard (filled, one colour per configuration)"
    body.append(_marker("circle", 66, 151, 10, "#0072B2"))
    body.append(_text(86, 158, legend_a, size=20, fill=MUTED))
    lx = 86 + text_width(legend_a, 20) + 48
    body.append(_marker("square", lx, 151, 10, "#595959", hollow=True))
    body.append(
        _text(lx + 20, 158, "open-source comparison tools (hollow, grey)", size=20, fill=MUTED)
    )
    caption = [
        set_caption(index, fixture_set)
        + f", {pooled_languages(index, fixture_set)}. Small sets: a few points of difference "
        "is noise.",
        *([left_out] if left_out else []),
        (
            "Latency measured where each system ran (remote API, H100, laptop CPU): see "
            "docs/benchmarks.md; not a like-for-like speed test."
        ),
        _provenance(snaps),
    ]
    return _svg(
        "Leak rate vs latency",
        "Scatter of full leak rate against detection latency for each system on the "
        + fixture_set
        + " fixtures: "
        + "; ".join(p["label"] for p in points),
        body,
        caption,
    )


# --- (b) by language ------------------------------------------------------------------------


def by_language(index: Mapping[str, Any], *, fixture_set: str, systems: Sequence[str]) -> str:
    snaps = _snapshots(index, fixture_set, systems)
    styles = index["systems"]
    langs = [lang for lang in index["languages"] if any(lang in s["languages"] for s in snaps)]
    colors = {lang: LANG_COLORS[i % len(LANG_COLORS)] for i, lang in enumerate(langs)}
    label_w = (
        max([text_width(styles[s["system"]]["short_label"], 21, bold=True) for s in snaps] + [100])
        + 28
        + 32
    )
    top, bottom = 210, 740
    row_h = (bottom - top) / max(len(snaps), 1)
    bar_h = min(26, (row_h - 14) / max(len(langs), 1))
    panels = [
        ("Overlap F1 (higher is better)", "f1", 56 + label_w),
        ("Full leak rate (lower is safer)", "leak", 0),
    ]
    gap = 110
    pw = (W - 56 - label_w - gap - 80) / 2
    panels[1] = (panels[1][0], panels[1][1], panels[0][2] + pw + gap)
    body = [
        _text(
            56,
            112,
            "Per language, per system: the same fixture set in each language",
            size=24,
            fill=MUTED,
        )
    ]
    # Legend for languages.
    lx = 56
    info = index["fixture_sets"].get(fixture_set, {})
    for lang in langs:
        body.append(f'<rect x="{lx}" y="140" width="22" height="22" fill="{colors[lang]}"/>')
        txt = f"{lang} ({info.get('documents', {}).get(lang, '?')} docs)"
        body.append(_text(lx + 30, 159, txt, size=21))
        lx += 30 + text_width(txt, 21) + 36
    for title, _key, x0 in panels:
        body.append(_text(x0, top - 14, title, size=22, weight="600"))
        for t in (0, 0.25, 0.5, 0.75, 1.0):
            x = x0 + t * pw
            body.append(
                f'<line x1="{_n(x)}" y1="{top}" x2="{_n(x)}" y2="{bottom}" stroke="{GRID}" '
                'stroke-width="2"/>'
            )
            body.append(
                _text(x, bottom + 30, f"{t * 100:.0f}%", size=20, fill=MUTED, anchor="middle")
            )
    for i, s in enumerate(snaps):
        st = styles[s["system"]]
        y = top + i * row_h + (row_h - bar_h * len(langs)) / 2
        body.append(
            _marker(
                st["shape"],
                56 + 10,
                y + bar_h * len(langs) / 2,
                9,
                st["color"],
                hollow=st["family"] == "comparison",
            )
        )
        body.append(
            _text(56 + 28, y + bar_h * len(langs) / 2 + 8, st["short_label"], size=21, weight="600")
        )
        for j, lang in enumerate(langs):
            m = s["languages"].get(lang)
            for _, key, x0 in panels:
                yy = y + j * bar_h
                v = None if m is None else m[key]
                if v is None:
                    body.append(
                        _text(x0 + 6, yy + bar_h - 5, "no current run", size=18, fill=MUTED)
                    )
                    continue
                w = max(v * pw, 2)
                body.append(
                    f'<rect x="{_n(x0)}" y="{_n(yy + 2)}" width="{_n(w)}" '
                    f'height="{_n(bar_h - 4)}" fill="{colors[lang]}"/>'
                )
                body.append(_text(x0 + w + 8, yy + bar_h - 6, fmt_pct(v), size=19, fill=INK))
    caption = [
        set_caption(index, fixture_set) + ". Bars: runs on the current fixture files only.",
        (
            "Full leak = labelled values of mask-policy types surviving masking in any surface "
            "form. F1 = span overlap match, micro."
        ),
        _provenance(snaps),
    ]
    return _svg(
        "F1 and leak rate by language",
        "Grouped bars of overlap F1 and full leak rate per language for each system on the "
        + fixture_set
        + " fixtures.",
        body,
        caption,
    )


# --- (b2) number validity ------------------------------------------------------------------

#: (key in the compact validity block or ``None`` for the headline, legend, colour)
VALIDITY_BARS: tuple[tuple[str | None, str, str], ...] = (
    (None, "All values (headline)", "#4A4A52"),
    ("valid", "Valid numbers", "#117733"),
    ("invalid", "Invalid numbers", "#CC6677"),
    ("excluding_number_types", "Other values (names, addresses, e-mail)", "#332288"),
)


def number_validity(index: Mapping[str, Any], *, fixture_set: str) -> str:
    """Leak rate per system: headline, valid numbers, invalid numbers, every other value."""
    order = {key: i for i, key in enumerate(index["systems"])}
    snaps = sorted(
        (
            s
            for s in index["snapshots"]
            if s["fixture_set"] == fixture_set and s["all"].get("validity")
        ),
        key=lambda s: order.get(s["system"], len(order)),
    )
    styles = index["systems"]
    label_w = (
        max([text_width(styles[s["system"]]["short_label"], 21, bold=True) for s in snaps] + [100])
        + 28
        + 32
    )
    top, bottom = 210, 730
    row_h = (bottom - top) / max(len(snaps), 1)
    bar_h = min(24, (row_h - 12) / len(VALIDITY_BARS))
    x0 = 56 + label_w
    pw = W - x0 - 140
    body = [
        _text(
            56,
            112,
            "Full leak rate per system, split by whether a number passes the language packs' "
            "validators",
            size=24,
            fill=MUTED,
        )
    ]
    lx = 56
    for _, name, color in VALIDITY_BARS:
        body.append(f'<rect x="{lx}" y="140" width="22" height="22" fill="{color}"/>')
        body.append(_text(lx + 30, 159, name, size=21))
        lx += 30 + text_width(name, 21) + 36
    for t in (0, 0.25, 0.5, 0.75, 1.0):
        x = x0 + t * pw
        body.append(
            f'<line x1="{_n(x)}" y1="{top}" x2="{_n(x)}" y2="{bottom}" stroke="{GRID}" '
            'stroke-width="2"/>'
        )
        body.append(_text(x, bottom + 30, f"{t * 100:.0f}%", size=20, fill=MUTED, anchor="middle"))
    off = []
    for i, s in enumerate(snaps):
        st, m, v = styles[s["system"]], s["all"], s["all"]["validity"]
        y = top + i * row_h + (row_h - bar_h * len(VALIDITY_BARS)) / 2
        mid = y + bar_h * len(VALIDITY_BARS) / 2
        body.append(
            _marker(st["shape"], 56 + 10, mid, 9, st["color"], hollow=st["family"] == "comparison")
        )
        label = st["short_label"] + ("" if v["matches_headline"] else " §")
        body.append(_text(56 + 28, mid + 8, label, size=21, weight="600"))
        if not v["matches_headline"]:
            off.append(f"{st['short_label']} re-run {fmt_pct(v['rerun_leak'])}%")
        for j, (key, _, color) in enumerate(VALIDITY_BARS):
            value = m["leak"] if key is None else v[key]["leak"]
            yy = y + j * bar_h
            if value is None:
                body.append(_text(x0 + 6, yy + bar_h - 5, "no values", size=18, fill=MUTED))
                continue
            w = max(value * pw, 2)
            body.append(
                f'<rect x="{_n(x0)}" y="{_n(yy + 2)}" width="{_n(w)}" '
                f'height="{_n(bar_h - 4)}" fill="{color}"/>'
            )
            body.append(_text(x0 + w + 8, yy + bar_h - 6, fmt_pct(value), size=19, fill=INK))
    caption = [
        set_caption(index, fixture_set) + ", " + pooled_languages(index, fixture_set) + ".",
        "Valid = a validated rule of the type recognises the value (checksum, numbering plan, "
        "format). Invalid numbers stay in the headline.",
    ]
    if off:
        caption.append(
            "§ Breakdown from a re-run that differs from the headline: " + "; ".join(off) + "."
        )
    caption.append(_provenance(snaps))
    return _svg(
        "Leak rate by number validity",
        "Grouped bars of the full leak rate per system on the "
        + fixture_set
        + " fixtures: all values, numbers that pass their validators, numbers that fail them, "
        "and every other value.",
        body,
        caption,
    )


# --- (c) progress over time -----------------------------------------------------------------


def progress(index: Mapping[str, Any], *, fixture_set: str, systems: Sequence[str]) -> str:
    styles = index["systems"]
    ours = [k for k in systems if styles.get(k, {}).get("family") == "pii-guard"]
    ours += [
        k for k, v in styles.items() if v.get("default") and k not in ours and v["kind"] == "text"
    ]
    hist = [h for h in index["history"] if h["fixture_set"] == fixture_set and h["system"] in ours]
    # Hollow points ran on other documents (an earlier fixture file, or fewer languages).
    comparable = [h for h in hist if h.get("comparable", True)]
    cats: list[tuple[str, str]] = []
    for h in hist:
        if (h["date"], h["commit"]) not in cats:
            cats.append((h["date"], h["commit"]))
    px0, py0, px1, py1 = 150, 170, 1180, 670
    leak_max = max([h["all"]["leak"] or 0 for h in hist] + [0.1])
    ymax = min(1.0, math.ceil(leak_max * 10 + 0.5) / 10)

    def sx(i: int) -> float:
        return px0 + (i + 0.5) * (px1 - px0) / max(len(cats), 1)

    def sy(v: float) -> float:
        return py1 - v / ymax * (py1 - py0)

    body = [
        _text(
            56,
            112,
            (
                "Full leak rate of each pii-guard configuration, run by run, oldest first (lower "
                "is safer)"
            ),
            size=24,
            fill=MUTED,
        )
    ]
    for t in [round(i * 0.1, 1) for i in range(round(ymax / 0.1) + 1)]:
        body.append(
            f'<line x1="{px0}" y1="{_n(sy(t))}" x2="{px1}" y2="{_n(sy(t))}" stroke="{GRID}" '
            'stroke-width="2"/>'
        )
        body.append(
            _text(px0 - 16, sy(t) + 7, f"{t * 100:.0f}%", size=20, fill=MUTED, anchor="end")
        )
    for i, (day, commit) in enumerate(cats):
        body.append(_text(sx(i), py1 + 34, day, size=20, fill=MUTED, anchor="middle"))
        body.append(_text(sx(i), py1 + 60, _short(commit), size=20, fill=MUTED, anchor="middle"))
    body.append(
        f'<line x1="{px0}" y1="{py1}" x2="{px1}" y2="{py1}" stroke="{AXIS}" stroke-width="2"/>'
    )
    # Best pii-guard result so far: a step line.
    best: list[tuple[float, float]] = []
    current = None
    for i, cat in enumerate(cats):
        vals = [
            h["all"]["leak"]
            for h in comparable
            if (h["date"], h["commit"]) == cat and h["all"]["leak"] is not None
        ]
        if vals:
            current = min(vals) if current is None else min(current, *vals)
        if current is not None:
            best.append((sx(i), sy(current)))
    if best:
        path = f"M{_n(best[0][0] - 40)},{_n(best[0][1])}"
        for i, (x, y) in enumerate(best):
            if i:
                path += f"H{_n(x - 40)}V{_n(y)}"
        path += f"H{_n(best[-1][0] + 40)}"
        body.append(
            f'<path d="{path}" fill="none" stroke="{INK}" stroke-width="3" '
            'stroke-dasharray="10 7"/>'
        )
    for key in ours:
        st = styles[key]
        pts = [
            (cats.index((h["date"], h["commit"])), h["all"]["leak"], h.get("comparable", True))
            for h in hist
            if h["system"] == key
        ]
        pts = [(i, v, c) for i, v, c in pts if v is not None]
        if len(pts) > 1:
            d = "M" + "L".join(f"{_n(sx(i))},{_n(sy(v))}" for i, v, _ in pts)
            body.append(f'<path d="{d}" fill="none" stroke="{st["color"]}" stroke-width="4"/>')
        for i, v, c in pts:
            body.append(_marker("circle", sx(i), sy(v), 11, st["color"], hollow=not c))
    # Legend (right).
    ly = py0 + 10
    for key in ours:
        st = styles[key]
        last = [h for h in hist if h["system"] == key]
        if not last:
            continue
        body.append(_marker("circle", 1230, ly, 10, st["color"]))
        name = st["short_label"] + (" (default)" if st.get("default") else "")
        body.append(_text(1250, ly + 7, name, size=20, weight="600"))
        body.append(
            _text(
                1250,
                ly + 33,
                f"latest {fmt_pct(last[-1]['all']['leak'])}% leak"
                + ("" if last[-1].get("comparable", True) else ", other documents"),
                size=19,
                fill=MUTED,
            )
        )
        ly += 70
    body.append(
        f'<line x1="1218" y1="{_n(ly)}" x2="1242" y2="{_n(ly)}" stroke="{INK}" '
        'stroke-width="3" stroke-dasharray="8 5"/>'
    )
    body.append(_text(1250, ly + 7, "best of any configuration so far", size=20, weight="600"))
    snaps = [{"dates": [h["date"]], "commits": [h["commit"]]} for h in hist]
    caption = [
        set_caption(index, fixture_set)
        + f", {pooled_languages(index, fixture_set)}; one configuration at one commit merged.",
        (
            "Hollow: run on an earlier fixture file or on fewer languages (other documents), not "
            "comparable with filled points or the best line."
        ),
        (
            "The default pipeline (rules only) finds no names by design; names come from the NER "
            "and LLM stages."
        ),
        _provenance(snaps),
    ]
    return _svg(
        "Leak rate over time",
        "Line chart of the full leak rate of pii-guard configurations across runs on the "
        + fixture_set
        + " fixtures.",
        body,
        caption,
    )


# --- (d) per-type recall heatmap ------------------------------------------------------------

_BLUES = [(0.0, (0xF3, 0xF6, 0xFB)), (0.5, (0x6B, 0xAE, 0xD6)), (1.0, (0x08, 0x30, 0x6B))]


def _blue(v: float) -> tuple[str, bool]:
    """A sequential single-hue colour for ``v`` in [0, 1], and whether text on it is white."""
    for (a, ca), (b, cb) in itertools.pairwise(_BLUES):
        if v <= b:
            t = (v - a) / (b - a)
            rgb = tuple(round(x + (y - x) * t) for x, y in zip(ca, cb, strict=True))
            break
    else:
        rgb = _BLUES[-1][1]
    lum = 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]
    return "#{:02X}{:02X}{:02X}".format(*rgb), lum < 140


def _wrap(text: str, size: float, width: float) -> list[str]:
    lines: list[str] = []
    for word in text.split():
        if lines and text_width(lines[-1] + " " + word, size, bold=True) <= width:
            lines[-1] += " " + word
        else:
            lines.append(word)
    return lines[:3]


def type_recall_heatmap(
    index: Mapping[str, Any], *, fixture_set: str, systems: Sequence[str]
) -> str:
    snaps = _snapshots(index, fixture_set, systems, complete=True)
    left_out = _left_out(index, fixture_set, systems, snaps)
    styles = index["systems"]
    types = [t for t in index["entity_types"] if any(t in s["all"]["per_type"] for s in snaps)]
    gold = {
        t: max((s["all"]["per_type"].get(t, {}).get("gold") or 0) for s in snaps) for t in types
    }
    x0, top = 420, 230
    cw = (W - 56 - x0) / max(len(snaps), 1)
    rh = min(44, ((740 if left_out else 770) - top) / max(len(types), 1))
    body = [
        _text(
            56,
            112,
            "Overlap recall per entity type (share of gold spans found), per system",
            size=24,
            fill=MUTED,
        )
    ]
    for j, s in enumerate(snaps):
        st = styles[s["system"]]
        lines = _wrap(st["short_label"], 20, cw - 12)
        for k, line in enumerate(lines):
            body.append(
                _text(
                    x0 + (j + 0.5) * cw,
                    top - 16 - (len(lines) - 1 - k) * 24,
                    line,
                    size=20,
                    anchor="middle",
                    weight="600",
                )
            )
    for i, t in enumerate(types):
        y = top + i * rh
        keep = all(s["all"]["per_type"].get(t, {}).get("leak") is None for s in snaps)
        name = f"{t}{' (kept)' if keep else ''}"
        body.append(_text(x0 - 14, y + rh / 2 + 7, name, size=19, anchor="end"))
        body.append(
            _text(
                x0 - 14 - text_width(name, 19) - 10,
                y + rh / 2 + 7,
                f"n={gold[t]}",
                size=18,
                fill=MUTED,
                anchor="end",
            )
        )
        for j, s in enumerate(snaps):
            cell = s["all"]["per_type"].get(t)
            x = x0 + j * cw
            if not cell or cell["recall"] is None:
                body.append(
                    f'<rect x="{_n(x + 2)}" y="{_n(y + 2)}" width="{_n(cw - 4)}" '
                    f'height="{_n(rh - 4)}" fill="#FAFAFB" stroke="{GRID}"/>'
                )
                body.append(
                    _text(x + cw / 2, y + rh / 2 + 7, "n/a", size=18, fill=MUTED, anchor="middle")
                )
                continue
            fill, white = _blue(cell["recall"])
            body.append(
                f'<rect x="{_n(x + 2)}" y="{_n(y + 2)}" width="{_n(cw - 4)}" '
                f'height="{_n(rh - 4)}" fill="{fill}"/>'
            )
            body.append(
                _text(
                    x + cw / 2,
                    y + rh / 2 + 7,
                    f"{cell['recall'] * 100:.0f}",
                    size=19,
                    fill="#FFFFFF" if white else INK,
                    anchor="middle",
                    weight="600",
                )
            )
    caption = [
        set_caption(index, fixture_set)
        + f", {pooled_languages(index, fixture_set)}. Cells are recall in %; n = gold spans of "
        "the type.",
        *([left_out] if left_out else []),
        (
            "(kept) types are not masked by policy, so they cannot leak. Comparison tools have no "
            "recognisers for Hungarian identifiers."
        ),
        _provenance(snaps),
    ]
    return _svg(
        "Recall by entity type",
        "Heatmap of overlap recall per entity type and system on the " + fixture_set + " fixtures.",
        body,
        caption,
    )


# --- (e) visual recall ----------------------------------------------------------------------


_VISUAL_SETS = {
    "specimens": "official specimen ID documents",
    "fictional-specimens": "fictional, Muse Image",
}


#: System-key prefix of segmenter-only runs (``pii_guard.visual.segment_eval``, LAB-1229).
SEGMENT_PREFIX = "visual-segment:"


def is_segment_run(run: Mapping[str, Any]) -> bool:
    return str(run["system"]).startswith(SEGMENT_PREFIX)


def visual_recall(index: Mapping[str, Any], *, segmenters: bool = False) -> str:
    # The latest run of each system on each set: bars grouped by set, coloured by system.
    # ``segmenters``: only the segmenter comparison runs (else: every other visual run).
    latest: dict[tuple[str, str], Mapping[str, Any]] = {}
    for r in index["visual"]:
        if is_segment_run(r) != segmenters:
            continue
        latest[(str(r.get("fixture_set") or "specimens"), str(r["system"]))] = r
    set_order = list(dict.fromkeys(key[0] for key in latest))
    systems = list(dict.fromkeys(key[1] for key in latest))
    runs = [latest[(fs, sk)] for fs in set_order for sk in systems if (fs, sk) in latest]
    region_types = []
    for r in runs:
        for k in r["by_region_type"]:
            if k not in region_types:
                region_types.append(k)
    groups = [*region_types, "all"]
    color = assign(dict(index.get("colours", {}).get("visual", {})), systems, PALETTE_VISUAL)
    px0, py0, px1, py1 = 150, 230, 1540, 680
    gw = (px1 - px0) / max(len(groups), 1)
    gap = 0.4  # bar widths between the sets inside a group
    slots = len(runs) + gap * (len(set_order) - 1)
    bw = min(90, (gw - 24) / max(slots, 1))

    def sy(v: float) -> float:
        return py1 - v * (py1 - py0)

    def short(system: str) -> str:
        system = system.removeprefix("visual:").removeprefix(SEGMENT_PREFIX)
        return system.replace("sam-3.1+tesseract+", "").replace("+", " + ")

    body = [
        _text(
            56,
            112,
            "Share of labelled image regions masked (IoU >= 0.5), by region type; in each group, "
            + " | ".join(set_order),
            size=24,
            fill=MUTED,
        )
    ]
    lx, ly = 56, 140
    for sk in systems:
        txt = short(sk)
        width = 30 + text_width(txt, 21) + 36
        if lx + width > px1 + 40 and lx > 56:
            lx, ly = 56, ly + 32
        body.append(f'<rect x="{lx}" y="{ly}" width="22" height="22" fill="{color[sk]}"/>')
        body.append(_text(lx + 30, ly + 19, txt, size=21))
        lx += width
    for t in (0, 0.25, 0.5, 0.75, 1.0):
        body.append(
            f'<line x1="{px0}" y1="{_n(sy(t))}" x2="{px1}" y2="{_n(sy(t))}" stroke="{GRID}" '
            'stroke-width="2"/>'
        )
        body.append(
            _text(px0 - 16, sy(t) + 7, f"{t * 100:.0f}%", size=20, fill=MUTED, anchor="end")
        )
    for g, name in enumerate(groups):
        gx = px0 + g * gw + (gw - bw * slots) / 2
        ns: list[int] = []
        for k, r in enumerate(runs):
            block = r["overall"] if name == "all" else r["by_region_type"].get(name)
            if not block:
                continue
            if block["regions"] not in ns:
                ns.append(block["regions"])
            v = block["recall_iou50"] or 0
            set_index = set_order.index(str(r.get("fixture_set") or "specimens"))
            x = gx + (k + gap * set_index) * bw
            body.append(
                f'<rect x="{_n(x + 3)}" y="{_n(sy(v))}" width="{_n(bw - 6)}" '
                f'height="{_n(max(py1 - sy(v), 1))}" fill="{color[str(r["system"])]}"/>'
            )
            body.append(
                _text(
                    x + bw / 2,
                    sy(v) - 10,
                    fmt_pct(v, 0),
                    size=19 if bw >= 34 else 18,
                    anchor="middle",
                )
            )
        body.append(
            _text(px0 + (g + 0.5) * gw, py1 + 34, name, size=21, anchor="middle", weight="600")
        )
        body.append(
            _text(
                px0 + (g + 0.5) * gw,
                py1 + 60,
                "n=" + " / ".join(map(str, ns)),
                size=19,
                fill=MUTED,
                anchor="middle",
            )
        )
    body.append(
        f'<line x1="{px0}" y1="{py1}" x2="{px1}" y2="{py1}" stroke="{AXIS}" stroke-width="2"/>'
    )
    sets: dict[str, tuple[int, int]] = {}
    for r in runs:
        sets[str(r.get("fixture_set") or "specimens")] = (r["specimens"], r["countries"])
    caption = [
        f"Fixture set '{name}': {_VISUAL_SETS.get(name, 'image documents')}, {n} images, "
        f"{c} countries."
        for name, (n, c) in sets.items()
    ]
    caption += [
        "Latest run of each segmenter per set, no OCR: SAM 3.1 on the Meta API vs on-device "
        "candidates (LAB-1229). n = regions per set."
        if segmenters
        else "Latest run of each system per set. Text and MRZ: OCR + text detectors; portraits "
        "and signatures: SAM 3.1. n = regions per set.",
        (
            f"Runs {_span([r['date'] for r in runs])} · commits "
            f"{', '.join(sorted({_short(r['commit']) for r in runs}))} · generated by `pii-guard "
            "eval report` from eval/results/runs/"
        ),
    ]
    if segmenters:
        return _svg(
            "Segmenters: SAM 3.1 API vs on-device",
            "Grouped bars of portrait and signature recall for each segmenter run.",
            body,
            caption,
        )
    return _svg(
        "Visual recall on image documents",
        "Grouped bars of region recall per region type for each visual run.",
        body,
        caption,
    )


# --- Gateway latency ----------------------------------------------------------------------

#: Stage colours (Okabe-Ito), in pipeline order; ``other`` is untimed glue (HTTP, scheduling).
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


def latency(index: Mapping[str, Any]) -> str:
    runs = latest_latency(index)
    rows: list[tuple[str, Mapping[str, Any], str]] = []
    colours = assign(
        dict(index.get("colours", {}).get("latency", {})),
        [str(run["system"]) for run in runs],
        PALETTE_LATENCY,
    )
    for run in runs:
        for cell in run["cells"]:
            label = f"{latency_label(run)}, c={cell['concurrency']}" + (
                ", stream" if cell["stream"] else ""
            )
            rows.append((label, cell, colours[str(run["system"])]))
    body = [
        _text(
            56,
            112,
            "Latency pii-guard adds to an LLM call (total minus upstream), mock upstream with a "
            "fixed delay",
            size=24,
            fill=MUTED,
        )
    ]
    # Left: overhead p50 (bar) and p95 (tick), log scale.
    lx0, lx1, ly0, ly1 = 420, 900, 190, 720
    values = [
        v
        for _, c, _ in rows
        for v in ((c["overhead_ms"] or {}).get("p50"), (c["overhead_ms"] or {}).get("p95"))
        if v
    ]
    lo = 10 ** math.floor(math.log10(max(min(values), 0.01))) if values else 0.1
    hi = 10 ** math.ceil(math.log10(max(values))) if values else 10.0
    hi = max(hi, lo * 10)

    def sx(ms: float) -> float:
        ms = min(max(ms, lo), hi)
        return lx0 + (math.log10(ms) - math.log10(lo)) / (math.log10(hi) - math.log10(lo)) * (
            lx1 - lx0
        )

    body.append(_text(56, 165, "Overhead per request: p50 bar, p95 tick", size=24, weight="700"))
    decade = lo
    while decade <= hi * 1.0001:
        x = sx(decade)
        body.append(
            f'<line x1="{_n(x)}" y1="{ly0}" x2="{_n(x)}" y2="{ly1}" stroke="{GRID}" '
            'stroke-width="2"/>'
        )
        body.append(_text(x, ly1 + 32, fmt_duration(decade), size=20, fill=MUTED, anchor="middle"))
        decade *= 10
    rh = (ly1 - ly0) / max(len(rows), 1)
    bar = min(30.0, rh * 0.6)
    for i, (label, cell, color) in enumerate(rows):
        y = ly0 + i * rh + rh / 2
        p = cell["overhead_ms"] or {}
        body.append(_text(lx0 - 14, y + 7, label, size=19, anchor="end"))
        if p.get("p50"):
            body.append(
                f'<rect x="{lx0}" y="{_n(y - bar / 2)}" width="{_n(max(sx(p["p50"]) - lx0, 2))}" '
                f'height="{_n(bar)}" fill="{color}"/>'
            )
        if p.get("p95"):
            x = sx(p["p95"])
            body.append(
                f'<line x1="{_n(x)}" y1="{_n(y - bar / 2 - 4)}" x2="{_n(x)}" '
                f'y2="{_n(y + bar / 2 + 4)}" stroke="{INK}" stroke-width="4"/>'
            )
        if p.get("p50"):
            body.append(
                _text(
                    max(sx(p.get("p95") or p["p50"]), sx(p["p50"])) + 12,
                    y + 7,
                    f"{fmt_duration(p['p50'])} / {fmt_duration(p.get('p95'))}",
                    size=18,
                    fill=MUTED,
                )
            )
    body.append(
        f'<line x1="{lx0}" y1="{ly1}" x2="{lx1}" y2="{ly1}" stroke="{AXIS}" stroke-width="2"/>'
    )
    # Right: where the p50 overhead goes (c=1, not streamed), as shares of the bar.
    rx0, rx1 = 1080, 1544
    body.append(
        _text(rx0 - 20, 165, "Where it goes (p50, c=1, not streamed)", size=24, weight="700")
    )
    ry = 210
    for run in runs:
        cell = next(
            (c for c in run["cells"] if c["concurrency"] == 1 and not c["stream"]),
            run["cells"][0] if run["cells"] else None,
        )
        if cell is None:
            continue
        shares = stage_shares(cell)
        total = sum(v for _, v in shares) or 1.0
        body.append(_text(rx0 - 20, ry, latency_label(run), size=20, weight="600"))
        x = float(rx0 - 20)
        width = rx1 - (rx0 - 20)
        for name, v in shares:
            w = v / total * width
            if w <= 0:
                continue
            body.append(
                f'<rect x="{_n(x)}" y="{ry + 12}" width="{_n(w)}" height="40" '
                f'fill="{STAGE_COLORS[name]}"/>'
            )
            if w >= 70:
                ink = BG if name in ("detect", "unmask") else INK
                body.append(
                    _text(x + w / 2, ry + 40, fmt_duration(v), size=18, fill=ink, anchor="middle")
                )
            x += w
        ry += 110
    lx, ly = float(rx0 - 20), float(max(ry, 560))
    for name, color in STAGE_COLORS.items():
        tw = text_width(name, 19) + 46
        if lx + tw > rx1 + 10:
            lx, ly = float(rx0 - 20), ly + 34
        body.append(f'<rect x="{_n(lx)}" y="{_n(ly - 18)}" width="20" height="20" fill="{color}"/>')
        body.append(_text(lx + 28, ly, name, size=19))
        lx += tw
    delays = sorted({f"{r['upstream_delay_ms']:g} ms" for r in runs})
    hardware = sorted({str(r["hardware"]) for r in runs if r.get("hardware")})
    caption = [
        "Fixture set 'latency-corpus' (hand-written, fictional hu/en/de messages), a new session "
        f"per request, mock upstream delay {', '.join(delays) or 'n/a'}; c = concurrent requests.",
        "Overhead = gateway total - time waiting on the upstream; 'other' = untimed work (HTTP, "
        "scheduling). Hardware: " + ("; ".join(hardware) or "n/a") + ".",
        (
            f"Runs {_span([r['date'] for r in runs])} · commits "
            f"{', '.join(sorted({_short(r['commit']) for r in runs}))} · generated by `pii-guard "
            "eval report` from eval/results/runs/"
        ),
    ]
    return _svg(
        "Gateway overhead",
        "Horizontal bars of the p50 and p95 latency pii-guard adds per request for each mode, "
        "concurrency and streaming setting, and stacked bars of where the p50 overhead goes.",
        body,
        caption,
    )
