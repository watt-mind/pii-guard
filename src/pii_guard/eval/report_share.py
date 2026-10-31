"""Shareable benchmark images, generated from the run records (LAB-1663).

``pii-guard eval report`` writes each image as SVG and PNG, light and dark, in three sizes:
1600 x 900 (the README and docs), 1200 x 630 (Open Graph, X and Discord link cards) and
1080 x 1080 (square social posts). What goes on them is editorial and lives in the ``share``
section of ``docs/benchmarks/config.json``; every number comes from the benchmark index.

- :func:`hero`: leak rate against over-masking on one fixture set, one point per system;
- :func:`card`: a stat card that reads with no context (the headline number, the comparison
  bars, the one-line claim and the repository URL);
- :func:`by_set`: leak and over-masking per fixture set as grouped bars;
- :func:`open_ner`: open NER models dropped into the same rules, head to head;
- :func:`results_table`: the README's results table as a card, a row per fixture set and a
  column per system, each cell ``leak · over-masking``, the lowest per metric in bold (LAB-1675);
- :func:`how_it_works`: the README's request/response diagram (no numbers; LAB-1675).

Most images come in every size of :data:`SIZES`; :data:`IMAGES` names the sizes of the others.

The SVGs are byte-stable functions of the index. The PNGs are rasterized from them with
resvg (:mod:`pii_guard.eval.report_raster`) using the Inter files in ``docs/benchmarks/fonts``,
so text is laid out with the font the widths below are measured from.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from html import escape
from typing import Any

from pii_guard.eval.record import RecordError

__all__ = [
    "DARK",
    "IMAGES",
    "LIGHT",
    "SIZES",
    "Theme",
    "by_set",
    "card",
    "hero",
    "how_it_works",
    "open_ner",
    "parse_spec",
    "render_all",
    "results_table",
    "text_width",
]

FONT = "Inter, 'Helvetica Neue', Helvetica, Arial, sans-serif"

#: Size suffix in the file name -> (width, height). The README size has no suffix.
SIZES: dict[str, tuple[int, int]] = {
    "": (1600, 900),
    "1200x630": (1200, 630),
    "1080x1080": (1080, 1080),
}

LANGUAGE_NAMES = {
    "de": "German",
    "en": "English",
    "hu": "Hungarian",
    "pl": "Polish",
    "es": "Spanish",
    "fr": "French",
    "it": "Italian",
    "nl": "Dutch",
}


@dataclass(frozen=True)
class Theme:
    """Card colors. Data colors differ per theme too, so every series keeps its contrast."""

    suffix: str
    bg: str
    panel: str
    ink: str
    muted: str
    grid: str
    axis: str
    own: str
    own_ink: str
    rules: str
    tools: tuple[str, ...]
    own_tint: str  # the own system's column in the results table
    real: str  # personal data in the how-it-works diagram (placeholders use ``own``)


LIGHT = Theme(
    suffix="",
    bg="#FFFFFF",
    panel="#F4F5F7",
    ink="#16171B",
    muted="#55565F",
    grid="#E3E4E9",
    axis="#8A8B94",
    own="#3D7A0C",
    own_ink="#2F6108",
    rules="#8A8B94",
    tools=("#0072B2", "#C84E00", "#A0558A", "#6A5ACD", "#00796B", "#8D6E00"),
    own_tint="#EBF4E2",
    real="#B44400",
)
DARK = Theme(
    suffix="-dark",
    bg="#0F1115",
    panel="#1A1D23",
    ink="#F2F3F5",
    muted="#B4B6BF",
    grid="#2E3139",
    axis="#7D808A",
    own="#B6F36B",
    own_ink="#C9F78F",
    rules="#9A9CA6",
    tools=("#56B4E9", "#F0884A", "#E09BC8", "#A99BFF", "#4DB6AC", "#E3C454"),
    own_tint="#1D2716",
    real="#F0884A",
)

# Inter advance widths in thousandths of an em, U+0020..U+007E (docs/benchmarks/fonts).
_W_REGULAR = (
    "281 288 466 633 642 982 644 300 365 365 501 662 288 460 288 360 631 407 610 618 646 593 "
    "620 566 619 620 288 302 662 662 662 511 966 690 654 730 722 601 590 746 743 269 571 672 "
    "565 903 753 765 639 765 644 642 646 744 690 985 682 679 629 365 360 365 471 456 323 562 "
    "612 571 612 583 370 613 591 242 242 549 242 876 591 600 612 612 376 528 327 591 562 818 "
    "546 562 552 426 333 426 662"
)
_W_BOLD = (
    "237 338 551 649 655 1016 672 339 377 377 559 679 334 468 334 388 674 431 629 646 676 622 "
    "649 582 651 649 334 343 679 679 679 560 1016 747 662 740 722 607 587 750 747 281 584 719 "
    "565 932 762 771 648 777 657 655 667 732 747 1038 738 731 664 377 388 377 487 476 365 581 "
    "630 588 630 596 398 632 623 271 271 580 271 913 623 613 630 630 407 560 366 623 600 850 "
    "580 602 573 469 372 469 679"
)
_REGULAR = [int(v) for v in _W_REGULAR.split()]
_BOLD = [int(v) for v in _W_BOLD.split()]
_SPECIAL = {
    "·": 300,
    "\u2013": 500,
    "—": 1000,
    "←": 954,
    "→": 954,
    "↓": 860,
    "↙": 780,
    "\u00d7": 670,
}


def text_width(text: str, size: float, *, weight: int = 400) -> float:
    """Rendered width of ``text`` in Inter at ``size`` px (accented letters as their base)."""
    import unicodedata

    table = _BOLD if weight >= 600 else _REGULAR
    total = 0
    for ch in text:
        if ch in _SPECIAL:
            total += _SPECIAL[ch]
            continue
        base = unicodedata.normalize("NFD", ch)[0]
        code = ord(base)
        total += table[code - 0x20] if 0x20 <= code <= 0x7E else 620
    return total / 1000 * size


# --- SVG primitives -----------------------------------------------------------------------


def _n(x: float) -> str:
    s = f"{x:.1f}"
    return s[:-2] if s.endswith(".0") else s


def _text(
    x: float,
    y: float,
    content: str,
    *,
    size: float,
    fill: str,
    anchor: str = "start",
    weight: int = 400,
) -> str:
    attrs = f'x="{_n(x)}" y="{_n(y)}" font-size="{_n(size)}" fill="{fill}"'
    if anchor != "start":
        attrs += f' text-anchor="{anchor}"'
    if weight != 400:
        attrs += f' font-weight="{weight}"'
    return f"<text {attrs}>{escape(content)}</text>"


def _rect(x: float, y: float, w: float, h: float, fill: str, *, rx: float = 0) -> str:
    r = f' rx="{_n(rx)}"' if rx else ""
    return (
        f'<rect x="{_n(x)}" y="{_n(y)}" width="{_n(max(w, 0))}" height="{_n(h)}"{r} fill="{fill}"/>'
    )


def _line(x1: float, y1: float, x2: float, y2: float, stroke: str, width: float = 2) -> str:
    return (
        f'<line x1="{_n(x1)}" y1="{_n(y1)}" x2="{_n(x2)}" y2="{_n(y2)}" stroke="{stroke}" '
        f'stroke-width="{_n(width)}"/>'
    )


def _marker(shape: str, x: float, y: float, r: float, color: str, bg: str, *, hollow: bool) -> str:
    fill = bg if hollow else color
    stroke = f'stroke="{color if hollow else bg}" stroke-width="{_n(r * 0.3)}"'
    if shape == "square":
        s = r * 1.7
        return (
            f'<rect x="{_n(x - s / 2)}" y="{_n(y - s / 2)}" width="{_n(s)}" height="{_n(s)}" '
            f'fill="{fill}" {stroke}/>'
        )
    if shape in ("triangle", "diamond"):
        if shape == "triangle":
            pts = [(x, y - r * 1.2), (x + r * 1.15, y + r * 0.8), (x - r * 1.15, y + r * 0.8)]
        else:
            pts = [(x, y - r * 1.3), (x + r * 1.3, y), (x, y + r * 1.3), (x - r * 1.3, y)]
        return (
            f'<polygon points="{" ".join(f"{_n(a)},{_n(b)}" for a, b in pts)}" '
            f'fill="{fill}" {stroke}/>'
        )
    return f'<circle cx="{_n(x)}" cy="{_n(y)}" r="{_n(r)}" fill="{fill}" {stroke}/>'


def _svg(w: int, h: int, theme: Theme, title: str, desc: str, body: Sequence[str]) -> str:
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" '
        f'height="{h}" role="img" aria-labelledby="t d" '
        f'font-family="{escape(FONT, quote=True)}">',
        f'<title id="t">{escape(title)}</title>',
        f'<desc id="d">{escape(desc)}</desc>',
        _rect(0, 0, w, h, theme.bg),
        *body,
        "</svg>",
    ]
    return "\n".join(out) + "\n"


def _fit(text: str, size: float, width: float, *, weight: int = 400, floor: float = 0.6) -> float:
    """The largest font size <= ``size`` (down to ``floor`` of it) that fits ``width``."""
    w = text_width(text, size, weight=weight)
    if w <= width:
        return size
    return max(size * floor, size * width / w)


# --- Data ---------------------------------------------------------------------------------


def pct(rate: float | None) -> str:
    """``0.2%``: one decimal of the percentage, as the README tables round."""
    return "—" if rate is None else f"{rate * 100:.1f}%"


def _snap(index: Mapping[str, Any], fixture_set: str, system: str) -> Mapping[str, Any]:
    for s in index["snapshots"]:
        if s["fixture_set"] == fixture_set and s["system"] == system:
            if not s.get("complete", True):
                raise RecordError(
                    f"share: {system!r} on {fixture_set!r} misses some of the set's languages"
                )
            return s  # type: ignore[no-any-return]
    raise RecordError(f"share: no snapshot of {system!r} on {fixture_set!r}")


def _metric(index: Mapping[str, Any], fixture_set: str, system: str, key: str) -> float:
    value = _snap(index, fixture_set, system)["all"].get(key)
    if value is None:
        raise RecordError(f"share: {system!r} on {fixture_set!r} has no {key}")
    return float(value)


def set_docs(index: Mapping[str, Any], fixture_set: str) -> int:
    info = index["fixture_sets"].get(fixture_set)
    if info is None:
        raise RecordError(f"share: no fixture set {fixture_set!r}")
    return int(sum(info["documents"].values()))


def set_languages(index: Mapping[str, Any], fixture_set: str, *, codes: bool = False) -> str:
    """``German, English and Hungarian`` (or ``de, en, hu``), in the set's order."""
    langs = list(index["fixture_sets"][fixture_set]["documents"])
    if codes:
        return ", ".join(langs)
    names = [LANGUAGE_NAMES.get(lang, lang) for lang in langs]
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def _dates(index: Mapping[str, Any], pairs: Sequence[tuple[str, str]]) -> str:
    ds = sorted({d for fs, sy in pairs for d in _snap(index, fs, sy)["dates"]})
    return ds[0] if len(ds) == 1 else f"{ds[0]} to {ds[-1]}"


def parse_spec(raw: object, where: str) -> dict[str, Any]:
    """Validate the config's ``share`` section; :class:`RecordError` names what is wrong."""
    if not isinstance(raw, dict):
        raise RecordError(f"{where}: 'share' must be an object")
    for key in ("own", "url", "claim"):
        if not isinstance(raw.get(key), str):
            raise RecordError(f"{where}: share needs a '{key}' string")
    names = raw.get("names")
    if not isinstance(names, dict) or raw["own"] not in names:
        raise RecordError(f"{where}: share 'names' must name every system, 'own' included")
    headline = raw.get("headline")
    if (
        not isinstance(headline, dict)
        or not isinstance(headline.get("fixture_set"), str)
        or not isinstance(headline.get("systems"), list)
        or not isinstance(headline.get("title"), str)
    ):
        raise RecordError(f"{where}: share 'headline' needs 'fixture_set', 'title', 'systems'")
    sets = raw.get("sets")
    if (
        not isinstance(sets, list)
        or not sets
        or not all(
            isinstance(s, dict) and isinstance(s.get("fixture_set"), str) and "title" in s
            for s in sets
        )
    ):
        raise RecordError(f"{where}: share 'sets' needs objects with 'fixture_set' and 'title'")
    ner = raw.get("open_ner")
    if not isinstance(ner, dict) or not isinstance(ner.get("systems"), dict):
        raise RecordError(f"{where}: share 'open_ner' needs 'fixture_set' and 'systems'")
    for key in [*headline["systems"], *raw.get("set_systems", [])]:
        if key not in names:
            raise RecordError(f"{where}: share 'names' has no display name for {key!r}")
    table = raw.get("table_names", {})
    if not isinstance(table, dict) or not all(isinstance(v, str) for v in table.values()):
        raise RecordError(f"{where}: share 'table_names' must map system keys to names")
    return dict(raw)


def _name(spec: Mapping[str, Any], key: str) -> str:
    return str(spec["names"][key])


def _colors(spec: Mapping[str, Any], theme: Theme, systems: Sequence[str]) -> dict[str, str]:
    """Own system green, rules-only grey, comparison tools one hue each, in config order."""
    out: dict[str, str] = {}
    tools = iter(theme.tools)
    for key in systems:
        if key == spec["own"]:
            out[key] = theme.own
        elif key == spec.get("rules"):
            out[key] = theme.rules
        else:
            out[key] = next(tools)
    return out


@dataclass(frozen=True)
class _Type:
    """Type scale for one canvas size."""

    k: float
    m: float  # outer margin

    def __call__(self, px: float) -> float:
        return round(px * self.k, 1)


def _type(w: int, h: int) -> _Type:
    if (w, h) == (1200, 630):
        return _Type(0.8, 44)
    if w == h:
        return _Type(0.95, 56)
    return _Type(1.0, 64)


def _footer(
    w: int, h: int, theme: Theme, t: _Type, lines: Sequence[str], url: str
) -> tuple[list[str], float]:
    """Muted footer lines at the bottom, the URL right-aligned on the last; returns the top."""
    size = t(19)
    body: list[str] = []
    y = h - t.m * 0.75
    url_w = text_width(url, size, weight=600)
    for i, line in enumerate(reversed(lines)):
        avail = w - 2 * t.m - (url_w + 24 if i == 0 else 0)
        s = _fit(line, size, avail)
        body.append(_text(t.m, y, line, size=s, fill=theme.muted))
        if i == 0:
            body.append(_text(w - t.m, y, url, size=size, fill=theme.ink, anchor="end", weight=600))
        y -= size * 1.45
    return body, y


def _header(w: int, theme: Theme, t: _Type, title: str, subtitle: str) -> tuple[list[str], float]:
    ts = _fit(title, t(44), w - 2 * t.m, weight=700)
    y = t.m + ts * 0.8
    body = [_text(t.m, y, title, size=ts, fill=theme.ink, weight=700)]
    ss = _fit(subtitle, t(24), w - 2 * t.m)
    y += ss * 1.7
    body.append(_text(t.m, y, subtitle, size=ss, fill=theme.muted))
    return body, y


def _provenance(index: Mapping[str, Any], pairs: Sequence[tuple[str, str]]) -> str:
    return (
        f"Runs {_dates(index, pairs)} · generated by pii-guard eval report from the run "
        "records in eval/results/runs/"
    )


# --- (a) hero: leak vs over-masking -------------------------------------------------------


def _hero_labels(
    pts: Sequence[Mapping[str, Any]],
    index: Mapping[str, Any],
    spec: Mapping[str, Any],
    theme: Theme,
    colors: Mapping[str, str],
    t: _Type,
    bounds: tuple[float, float, float, float],
    scales: tuple[Callable[[float], float], Callable[[float], float]],
    tint_box: tuple[float, float, float],
) -> list[str]:
    px0, px1, py0, py1 = bounds
    sx, sy = scales
    tint_x1, tint_y0, tag_s = tint_box
    r = t(13)
    name_s, val_s = t(23), t(19)
    marks = [(sx(p["over"]), sy(p["leak"])) for p in pts]
    taken = [(mx - r * 1.4, my - r * 1.4, mx + r * 1.4, my + r * 1.4) for mx, my in marks]
    tag_w = text_width("↙ better", tag_s, weight=700)
    taken.append((tint_x1 - t(12) - tag_w, tint_y0, tint_x1, tint_y0 + tag_s * 1.6))
    order = sorted(pts, key=lambda p: (p["key"] != spec["own"], p["leak"]))
    placed: list[str] = []
    for p in order:
        x, y = sx(p["over"]), sy(p["leak"])
        name = _name(spec, p["key"])
        vals = f"leak {pct(p['leak'])} · over-masking {pct(p['over'])}"
        bw = max(text_width(name, name_s, weight=700), text_width(vals, val_s))
        bh = name_s + val_s * 1.4
        g = r * 1.1
        cands = [
            (x + g, y - bh - g * 0.4),  # above right
            (x + g, y + g * 0.4),  # below right
            (x - g - bw, y - bh - g * 0.4),  # above left
            (x - g - bw, y + g * 0.4),  # below left
            (x + r * 2, y - bh / 2),  # right
            (x - r * 2 - bw, y - bh / 2),  # left
            (x - bw / 2, y - bh - r * 1.8),  # above
            (x - bw / 2, y + r * 1.8),  # below
        ]

        def inside(c: tuple[float, float], bw: float = bw, bh: float = bh) -> bool:
            return (
                c[0] - 4 >= px0 + 2
                and c[0] + bw + 4 <= px1
                and c[1] - 2 >= py0 - t(30)
                and c[1] + bh + 2 <= py1 - 2
            )

        choice = next((c for c in cands if inside(c)), cands[0])
        for left, top_y in cands:
            box = (left - 4, top_y - 2, left + bw + 4, top_y + bh + 2)
            if not inside((left, top_y)):
                continue
            if any(
                not (box[2] < o[0] or box[0] > o[2] or box[3] < o[1] or box[1] > o[3])
                for o in taken
            ):
                continue
            choice = (left, top_y)
            break
        left, top_y = choice
        taken.append((left - 4, top_y - 2, left + bw + 4, top_y + bh + 2))
        own = p["key"] == spec["own"]
        placed.append(
            _text(
                left,
                top_y + name_s * 0.85,
                name,
                size=name_s,
                fill=theme.own_ink if own else theme.ink,
                weight=700,
            )
        )
        placed.append(_text(left, top_y + name_s + val_s * 1.1, vals, size=val_s, fill=theme.muted))
    out: list[str] = []
    for p in pts:
        st = index["systems"].get(p["key"], {})
        own = p["key"] == spec["own"]
        shape = "circle" if own or p["key"] == spec.get("rules") else st.get("shape", "circle")
        out.append(
            _marker(
                shape,
                sx(p["over"]),
                sy(p["leak"]),
                r * (1.25 if own else 1),
                colors[p["key"]],
                theme.bg,
                hollow=not own and p["key"] != spec.get("rules"),
            )
        )
    out.extend(placed)
    return out


def hero(
    index: Mapping[str, Any], spec: Mapping[str, Any], size: tuple[int, int], theme: Theme
) -> str:
    """Leak rate (y) against over-masking rate (x) on the headline set; lower-left is better."""
    w, h = size
    t = _type(w, h)
    hl = spec["headline"]
    fs, systems = hl["fixture_set"], list(hl["systems"])
    colors = _colors(spec, theme, systems)
    pts = [
        {
            "key": k,
            "leak": _metric(index, fs, k, "leak"),
            "over": _metric(index, fs, k, "over_masking"),
        }
        for k in systems
    ]
    n = set_docs(index, fs)
    title = "Leak vs over-masking: lower-left is better"
    subtitle = (
        f"{n} fictional {hl['title']} documents ({set_languages(index, fs, codes=True)}) · "
        "same documents and scorer for every tool"
    )
    body, top = _header(w, theme, t, title, subtitle)
    footer, foot_top = _footer(
        w,
        h,
        theme,
        t,
        [
            "Leak: labeled personal values left readable. Over-masking: masks on text that "
            "was not personal data.",
            _provenance(index, [(fs, k) for k in systems]),
        ],
        spec["url"],
    )
    body.extend(footer)

    lab = t(20)
    px0 = t.m + lab * 3.4
    px1 = w - t.m - t(10)
    py0 = top + t(46)
    py1 = foot_top - lab * 3.6
    xmax = max(0.1, -(-max(p["over"] for p in pts) * 10 // 1) / 10)
    ymax = max(0.1, -(-max(p["leak"] for p in pts) * 10 // 1) / 10)

    def sx(v: float) -> float:
        return px0 + v / xmax * (px1 - px0)

    def sy(v: float) -> float:
        return py1 - v / ymax * (py1 - py0)

    # A tint over the better corner, then the grid.
    body.append(_rect(px0, sy(ymax * 0.25), (px1 - px0) * 0.25, py1 - sy(ymax * 0.25), theme.panel))
    step_x = 0.1 if xmax <= 0.5 else 0.2
    step_y = 0.1 if ymax <= 0.5 else 0.2
    for i in range(round(ymax / step_y) + 1):
        v = round(i * step_y, 2)
        body.append(_line(px0, sy(v), px1, sy(v), theme.grid))
        body.append(
            _text(
                px0 - t(12),
                sy(v) + lab * 0.35,
                f"{v * 100:.0f}%",
                size=lab,
                fill=theme.muted,
                anchor="end",
            )
        )
    for i in range(round(xmax / step_x) + 1):
        v = round(i * step_x, 2)
        body.append(_line(sx(v), py0, sx(v), py1, theme.grid))
        body.append(
            _text(
                sx(v),
                py1 + lab * 1.5,
                f"{v * 100:.0f}%",
                size=lab,
                fill=theme.muted,
                anchor="middle",
            )
        )
    body.append(_line(px0, py1, px1, py1, theme.axis))
    body.append(_line(px0, py0, px0, py1, theme.axis))
    axis = t(21)
    body.append(
        _text(
            (px0 + px1) / 2,
            py1 + lab * 1.5 + axis * 1.5,
            "Over-masking → (share of masks on non-personal text)",
            size=axis,
            fill=theme.ink,
            anchor="middle",
        )
    )
    ly = (py0 + py1) / 2
    lx = t.m + axis * 0.4
    body.append(
        f'<text x="{_n(lx)}" y="{_n(ly)}" font-size="{_n(axis)}" fill="{theme.ink}" '
        f'text-anchor="middle" transform="rotate(-90 {_n(lx)} {_n(ly)})">'
        f"{escape('Leak → (share of personal values left readable)')}</text>"
    )
    tint_x1, tint_y0 = px0 + (px1 - px0) * 0.25, sy(ymax * 0.25)
    tag_s = t(20)
    body.append(
        _text(
            tint_x1 - t(12),
            tint_y0 + tag_s * 1.3,
            "↙ better",
            size=tag_s,
            fill=theme.muted,
            anchor="end",
            weight=600,
        )
    )
    body.extend(
        _hero_labels(
            pts,
            index,
            spec,
            theme,
            colors,
            t,
            (px0, px1, py0, py1),
            (sx, sy),
            (tint_x1, tint_y0, tag_s),
        )
    )
    desc = (
        f"Scatter of leak rate against over-masking rate on {n} fictional {hl['title']} "
        "documents; lower-left is better. "
        + "; ".join(
            f"{_name(spec, p['key'])}: leak {pct(p['leak'])}, over-masking {pct(p['over'])}"
            for p in pts
        )
        + "."
    )
    return _svg(w, h, theme, title, desc, body)


# --- (b) stat card ------------------------------------------------------------------------


def _card_bars(
    systems: Sequence[str],
    leak: Mapping[str, float],
    over: Mapping[str, float],
    colors: Mapping[str, str],
    spec: Mapping[str, Any],
    theme: Theme,
    t: _Type,
    w: int,
    square: bool,
    top: float,
    bottom: float,
) -> list[str]:
    own = spec["own"]
    rows = len(systems)
    row_h = min(t(96 if square else 70), (bottom - top) / max(rows, 1))
    label_s = min(t(26 if square else 24), row_h * 0.42)
    short = {k: str(spec.get("short_names", {}).get(k, _name(spec, k))) for k in systems}
    label_w = max(text_width(short[k], label_s, weight=700) for k in systems) + t(24)
    label_w = min(label_w, w * 0.34)
    note_w = text_width("16.6%  over-masking 35.2%", label_s * 0.95) + t(16)
    bx0 = t.m + label_w
    bx1 = w - t.m - note_w
    vmax = max(leak.values()) or 1.0
    head = "Leak: share of labeled personal values that reached the model"
    out = [
        _text(
            t.m,
            top - label_s * 0.4,
            head,
            size=_fit(head, label_s * 0.85, w - 2 * t.m),
            fill=theme.muted,
        )
    ]
    for i, k in enumerate(sorted(systems, key=lambda s: leak[s])):
        cy = top + row_h * (i + 0.5) + label_s * 0.3
        bh = row_h * 0.5
        is_own = k == own
        name = short[k]
        out.append(
            _text(
                t.m,
                cy + label_s * 0.35,
                name,
                size=label_s,
                fill=theme.own_ink if is_own else theme.ink,
                weight=700 if is_own else 600,
            )
        )
        out.append(_rect(bx0, cy - bh / 2, bx1 - bx0, bh, theme.panel, rx=bh * 0.2))
        bw = max(bh * 0.25, leak[k] / vmax * (bx1 - bx0))
        out.append(_rect(bx0, cy - bh / 2, bw, bh, colors[k], rx=bh * 0.2))
        vx = bx1 + t(16)
        val = pct(leak[k])
        out.append(
            _text(
                vx,
                cy + label_s * 0.35,
                val,
                size=label_s,
                fill=theme.own_ink if is_own else theme.ink,
                weight=700,
            )
        )
        out.append(
            _text(
                vx + text_width(val, label_s, weight=700) + t(10),
                cy + label_s * 0.35,
                f"over-masking {pct(over[k])}",
                size=label_s * 0.8,
                fill=theme.muted,
            )
        )
    return out


def card(
    index: Mapping[str, Any], spec: Mapping[str, Any], size: tuple[int, int], theme: Theme
) -> str:
    """The headline number, the comparison bars, the claim and the URL: no context needed."""
    w, h = size
    t = _type(w, h)
    hl = spec["headline"]
    fs = hl["fixture_set"]
    systems = [k for k in hl["systems"] if k != spec.get("rules")]
    colors = _colors(spec, theme, systems)
    own = spec["own"]
    leak = {k: _metric(index, fs, k, "leak") for k in systems}
    over = {k: _metric(index, fs, k, "over_masking") for k in systems}
    n = set_docs(index, fs)
    square = w == h

    body: list[str] = []
    # Brand line.
    bs = t(34)
    y = t.m + bs * 0.8
    body.append(_text(t.m, y, "PII Guard", size=bs, fill=theme.ink, weight=700))
    tag = "open-source privacy gateway for AI agents"
    tx = t.m + text_width("PII Guard", bs, weight=700) + t(18)
    body.append(_text(tx, y, tag, size=_fit(tag, t(24), w - t.m - tx), fill=theme.muted))

    footer, foot_top = _footer(
        w,
        h,
        theme,
        t,
        [
            f"{n} fictional {hl['title']} documents ({set_languages(index, fs)}) · same "
            "documents and scorer for every tool",
            _provenance(index, [(fs, k) for k in systems]).replace(
                "generated by pii-guard eval report from the run records in eval/results/runs/",
                "generated from the committed run records",
            ),
        ],
        spec["url"],
    )
    claim_s = t(28) if not square else t(30)
    claim = spec["claim"]
    claim_s = _fit(claim, claim_s, w - 2 * t.m, weight=600)
    claim_y = foot_top - claim_s * 0.9
    body.append(_text(t.m, claim_y, claim, size=claim_s, fill=theme.ink, weight=600))
    body.extend(footer)

    # Big number and its sentence.
    big = t(150) if not square else t(190)
    if (w, h) == (1200, 630):
        big = t(140)
    num = pct(leak[own])
    ny = y + bs * 0.9 + big * 0.95
    body.append(_text(t.m - big * 0.04, ny, num, size=big, fill=theme.own_ink, weight=700))
    nx = t.m + text_width(num, big, weight=700) + t(28)
    line1 = "of personal values reached the model"
    line2 = f"over-masking {pct(over[own])} · rules + local NER, on CPU"
    room = w - t.m - nx
    s1 = _fit(line1, t(38), room, weight=600)
    s2 = _fit(line2, t(26), room)
    body.append(_text(nx, ny - big * 0.42, line1, size=s1, fill=theme.ink, weight=600))
    body.append(_text(nx, ny - big * 0.42 + s2 * 1.6, line2, size=s2, fill=theme.muted))

    top = ny + t(40 if not square else 70)
    bottom = claim_y - claim_s * 1.9
    body.extend(_card_bars(systems, leak, over, colors, spec, theme, t, w, square, top, bottom))
    title = f"PII Guard: {pct(leak[own])} of personal values reached the model"
    desc = (
        f"Stat card. On {n} fictional {hl['title']} documents, "
        + "; ".join(
            f"{_name(spec, k)} leaked {pct(leak[k])} with {pct(over[k])} over-masking"
            for k in systems
        )
        + f". {claim} {spec['url']}"
    )
    return _svg(w, h, theme, title, desc, body)


# --- (c) leak and over-masking per set ----------------------------------------------------


def by_set(
    index: Mapping[str, Any], spec: Mapping[str, Any], size: tuple[int, int], theme: Theme
) -> str:
    """Two panels of grouped bars, one group per fixture set: leak, then over-masking."""
    w, h = size
    t = _type(w, h)
    systems = list(spec["set_systems"])
    colors = _colors(spec, theme, systems)
    sets = spec["sets"]
    data = {
        (s["fixture_set"], k): (
            _metric(index, s["fixture_set"], k, "leak"),
            _metric(index, s["fixture_set"], k, "over_masking"),
        )
        for s in sets
        for k in systems
    }
    title = "Leak and over-masking on every set"
    subtitle = "Same documents and scorer for every tool within a set · lower is better"
    body, top = _header(w, theme, t, title, subtitle)
    footer, foot_top = _footer(
        w,
        h,
        theme,
        t,
        [_provenance(index, [(s["fixture_set"], k) for s in sets for k in systems])],
        spec["url"],
    )
    body.extend(footer)
    # Legend.
    ls = t(20)
    lx, ly = t.m, top + ls * 2.0
    for k in systems:
        body.append(_rect(lx, ly - ls * 0.75, ls * 0.9, ls * 0.9, colors[k], rx=3))
        name = _name(spec, k)
        body.append(
            _text(
                lx + ls * 1.3,
                ly,
                name,
                size=ls,
                fill=theme.ink,
                weight=700 if k == spec["own"] else 400,
            )
        )
        lx += ls * 1.3 + text_width(name, ls, weight=700) + ls * 1.6
    gtop = ly + ls * 2.2
    label_s = t(19)
    gbot = foot_top - t(18) - label_s * 1.4
    label_w = max(text_width(str(s["title"]), label_s, weight=700) for s in sets) + t(20)
    panel_gap = t(36)
    pw = (w - 2 * t.m - label_w - panel_gap) / 2
    groups = len(sets)
    gh = (gbot - gtop - label_s * 1.6) / groups
    bar = gh * 0.78 / len(systems)
    val_s = min(t(17), bar * 0.95)
    for p, (title_p, idx) in enumerate((("Leak", 0), ("Over-masking", 1))):
        x0 = t.m + label_w + p * (pw + panel_gap)
        x1 = x0 + pw - text_width("88.8%", val_s) - t(8)
        vmax = max(0.1, -(-max(v[idx] for v in data.values()) * 10 // 1) / 10)
        body.append(
            _text(x0, gtop + label_s * 0.2, title_p, size=label_s * 1.1, fill=theme.ink, weight=700)
        )
        y0 = gtop + label_s * 1.6
        for j in range(round(vmax / 0.2) + 1 if vmax > 0.5 else round(vmax / 0.1) + 1):
            v = j * (0.2 if vmax > 0.5 else 0.1)
            x = x0 + v / vmax * (x1 - x0)
            body.append(_line(x, y0 - 4, x, gbot, theme.grid, 1.5))
            body.append(
                _text(
                    x,
                    gbot + val_s * 1.3,
                    f"{v * 100:.0f}%",
                    size=val_s * 0.9,
                    fill=theme.muted,
                    anchor="middle",
                )
            )
        for gi, s in enumerate(sets):
            gy = y0 + gi * gh + gh * 0.08
            for si, k in enumerate(systems):
                v = data[(s["fixture_set"], k)][idx]
                by = gy + si * bar
                bw = max(2.0, v / vmax * (x1 - x0))
                body.append(_rect(x0, by + bar * 0.08, bw, bar * 0.84, colors[k]))
                body.append(
                    _text(
                        x0 + bw + t(6),
                        by + bar * 0.5 + val_s * 0.36,
                        pct(v),
                        size=val_s,
                        fill=theme.own_ink if k == spec["own"] else theme.muted,
                        weight=700 if k == spec["own"] else 400,
                    )
                )
    for gi, s in enumerate(sets):
        gy = gtop + label_s * 1.6 + gi * gh + gh * 0.08
        fs = s["fixture_set"]
        body.append(
            _text(
                t.m, gy + label_s * 0.9, str(s["title"]), size=label_s, fill=theme.ink, weight=700
            )
        )
        body.append(
            _text(
                t.m,
                gy + label_s * 2.1,
                f"{set_docs(index, fs)} docs",
                size=label_s * 0.85,
                fill=theme.muted,
            )
        )
        body.append(
            _text(
                t.m,
                gy + label_s * 3.1,
                set_languages(index, fs, codes=True),
                size=label_s * 0.85,
                fill=theme.muted,
            )
        )
    desc = "Grouped bars of leak and over-masking per fixture set. " + " ".join(
        f"{s['title']}: "
        + ", ".join(
            f"{_name(spec, k)} leak {pct(data[(s['fixture_set'], k)][0])}, over-masking "
            f"{pct(data[(s['fixture_set'], k)][1])}"
            for k in systems
        )
        + "."
        for s in sets
    )
    return _svg(w, h, theme, title, desc, body)


# --- (d) open NER models head to head -----------------------------------------------------


def open_ner(
    index: Mapping[str, Any], spec: Mapping[str, Any], size: tuple[int, int], theme: Theme
) -> str:
    """Leak of each open NER model with the same rules in front, on one set."""
    w, h = size
    t = _type(w, h)
    cfg = spec["open_ner"]
    fs = cfg["fixture_set"]
    names: Mapping[str, str] = cfg["systems"]
    rows = sorted(
        (
            (
                k,
                _metric(index, fs, k, "leak"),
                _metric(index, fs, k, "over_masking"),
                _metric(index, fs, k, "f1"),
            )
            for k in names
        ),
        key=lambda r: (r[1], r[2]),
    )
    title = "Open PII NER models, same rules around each"
    subtitle = (
        f"Hand-written set: {set_docs(index, fs)} fictional documents "
        f"({set_languages(index, fs, codes=True)}) · leak, lower is safer"
    )
    body, top = _header(w, theme, t, title, subtitle)
    footer, foot_top = _footer(
        w, h, theme, t, [_provenance(index, [(fs, k) for k in names])], spec["url"]
    )
    body.extend(footer)
    y0, y1 = top + t(30), foot_top - t(20)
    row_h = (y1 - y0) / len(rows)
    name_s = min(t(22), row_h * 0.34)
    bar_h = row_h * 0.32
    note = "100.0%  over-masking 10.0% · F1 99.9%"
    x0 = t.m
    x1 = w - t.m - text_width(note, name_s * 0.9) - t(16)
    vmax = max(0.05, -(-max(r[1] for r in rows) * 20 // 1) / 20)
    for i, (k, leak, over, f1) in enumerate(rows):
        own = k == spec["own"]
        ty = y0 + i * row_h + name_s
        body.append(
            _text(
                x0,
                ty,
                names[k],
                size=_fit(names[k], name_s, w - 2 * t.m, weight=600),
                fill=theme.own_ink if own else theme.ink,
                weight=700 if own else 600,
            )
        )
        by = ty + name_s * 0.45
        body.append(_rect(x0, by, x1 - x0, bar_h, theme.panel, rx=bar_h * 0.2))
        bw = max(bar_h * 0.3, leak / vmax * (x1 - x0))
        body.append(_rect(x0, by, bw, bar_h, theme.own if own else theme.tools[0], rx=bar_h * 0.2))
        vx = x1 + t(14)
        val = pct(leak)
        body.append(
            _text(
                vx,
                by + bar_h * 0.8,
                val,
                size=name_s * 0.95,
                fill=theme.own_ink if own else theme.ink,
                weight=700,
            )
        )
        body.append(
            _text(
                vx + text_width(val, name_s * 0.95, weight=700) + t(10),
                by + bar_h * 0.8,
                f"over-masking {pct(over)} · F1 {pct(f1)}",
                size=name_s * 0.78,
                fill=theme.muted,
            )
        )
    desc = "Horizontal bars of leak rate per open NER model behind the same rules. " + "; ".join(
        f"{names[k]}: leak {pct(leak)}, over-masking {pct(over)}, F1 {pct(f1)}"
        for k, leak, over, f1 in rows
    )
    return _svg(w, h, theme, title, desc, body)


# --- (e) the README results table ---------------------------------------------------------


def _one_decimal(rate: float) -> float:
    """The rate as the table prints it, so "lowest" means lowest as shown (as in the README)."""
    return float(f"{rate * 100:.1f}")


def _lowest(values: Sequence[float]) -> set[int]:
    shown = [_one_decimal(v) for v in values]
    return {i for i, v in enumerate(shown) if v == min(shown)}


def _short_pct(rate: float) -> str:
    return pct(rate)


def results_table(
    index: Mapping[str, Any], spec: Mapping[str, Any], size: tuple[int, int], theme: Theme
) -> str:
    """A row per fixture set, a column per system, each cell ``leak · over-masking``.

    The same sets, systems, rounding and bolding as the README's compact table: the own
    system's column is tinted, and the lowest leak and the lowest over-masking in each row
    are bold.
    """
    w, h = size
    t = _type(w, h)
    systems = list(spec["set_systems"])
    sets = spec["sets"]
    own = spec["own"]
    names = {k: str(spec.get("table_names", {}).get(k, _name(spec, k))) for k in systems}
    data = {
        (s["fixture_set"], k): (
            _metric(index, s["fixture_set"], k, "leak"),
            _metric(index, s["fixture_set"], k, "over_masking"),
        )
        for s in sets
        for k in systems
    }
    title = "Leak and over-masking, set by set"
    subtitle = (
        "Each cell: leak · over-masking · lower is better · bold: the lowest in its row, per metric"
    )
    body, top = _header(w, theme, t, title, subtitle)
    footer, foot_top = _footer(
        w,
        h,
        theme,
        t,
        [
            "Leak: labeled personal values left readable. Over-masking: masks on text that "
            "was not personal data. All documents are fictional.",
            _provenance(index, [(s["fixture_set"], k) for s in sets for k in systems]),
        ],
        spec["url"],
    )
    body.extend(footer)

    title_s, sub_s = t(25), t(19)
    subs = {
        s["fixture_set"]: (
            f"{set_docs(index, s['fixture_set'])} docs · "
            f"{set_languages(index, s['fixture_set'], codes=True)}"
        )
        for s in sets
    }
    label_w = max(
        max(text_width(str(s["title"]), title_s, weight=700) for s in sets),
        max(text_width(v, sub_s) for v in subs.values()),
    ) + t(32)
    x0, x1 = t.m, w - t.m
    cw = (x1 - x0 - label_w) / len(systems)
    y0 = top + t(34)
    head_h = t(84)
    y1 = foot_top - t(22)
    row_h = (y1 - y0 - head_h) / len(sets)
    cell_s = _fit("88.8% · 88.8%", t(31), cw - t(30), weight=700)

    def cx(j: int) -> float:
        return x0 + label_w + cw * (j + 0.5)

    # The own column, tinted from the header to the last row.
    for j, k in enumerate(systems):
        if k == own:
            left = x0 + label_w + cw * j
            body.append(_rect(left, y0, cw, y1 - y0, theme.own_tint, rx=t(16)))
            body.append(_rect(left, y0, cw, t(6), theme.own, rx=t(3)))
    # Header: system name, then what the two numbers are.
    name_s = min(t(25), min(_fit(names[k], t(25), cw - t(20), weight=700) for k in systems))
    for j, k in enumerate(systems):
        is_own = k == own
        body.append(
            _text(
                cx(j),
                y0 + head_h * 0.46,
                names[k],
                size=name_s,
                fill=theme.own_ink if is_own else theme.ink,
                anchor="middle",
                weight=700,
            )
        )
        body.append(
            _text(
                cx(j),
                y0 + head_h * 0.46 + t(28),
                "leak · over-masking",
                size=t(18),
                fill=theme.muted,
                anchor="middle",
            )
        )
    body.append(_line(x0, y0 + head_h, x1, y0 + head_h, theme.axis, 1.5))

    for i, s in enumerate(sets):
        fs = s["fixture_set"]
        ry = y0 + head_h + row_h * i
        if i:
            body.append(_line(x0, ry, x1, ry, theme.grid, 1.5))
        mid = ry + row_h / 2
        body.append(
            _text(x0 + t(4), mid - t(3), str(s["title"]), size=title_s, fill=theme.ink, weight=700)
        )
        body.append(_text(x0 + t(4), mid + sub_s * 1.15, subs[fs], size=sub_s, fill=theme.muted))
        leaks = [data[(fs, k)][0] for k in systems]
        overs = [data[(fs, k)][1] for k in systems]
        best_leak, best_over = _lowest(leaks), _lowest(overs)
        for j, k in enumerate(systems):
            strong = theme.own_ink if k == own else theme.ink

            def span(value: float, best: bool, strong: str = strong) -> str:
                weight = ' font-weight="700"' if best else ""
                fill = strong if best else theme.muted
                return f'<tspan fill="{fill}"{weight}>{escape(_short_pct(value))}</tspan>'

            body.append(
                f'<text x="{_n(cx(j))}" y="{_n(mid + cell_s * 0.36)}" font-size="{_n(cell_s)}" '
                f'text-anchor="middle">{span(leaks[j], j in best_leak)}'
                f'<tspan fill="{theme.axis}"> · </tspan>{span(overs[j], j in best_over)}</text>'
            )
    desc = (
        "Table of leak and over-masking per fixture set; lower is better, the lowest per "
        "metric in each row in bold. "
        + " ".join(
            f"{s['title']} ({subs[s['fixture_set']]}): "
            + "; ".join(
                f"{names[k]} leak {pct(data[(s['fixture_set'], k)][0])}, over-masking "
                f"{pct(data[(s['fixture_set'], k)][1])}"
                for k in systems
            )
            + "."
            for s in sets
        )
    )
    return _svg(w, h, theme, title, desc, body)


# --- (f) how it works ---------------------------------------------------------------------

#: The gateway's steps, in the order a request meets them; the last one is on the way back.
STEPS = (
    "Extract text, tool calls, image regions",
    "Detect: rules → NER → optional audit LLM",
    "Apply policies, pseudonymize (keyed)",
    "Mask image regions (faces, SAM 3.1, OCR)",
    "Restore placeholders, chunk by chunk",
)
#: What crosses each arrow: a fictional name, and the placeholder that stands for it.
_REAL, _PLACEHOLDER = "Jane Doe", "[[PERSON_968e29]]"


def _arrow(x1: float, x2: float, y: float, color: str, width: float = 3) -> list[str]:
    """A horizontal arrow from ``x1`` to ``x2`` (either direction), head at ``x2``."""
    d = 1 if x2 > x1 else -1
    head = 14
    return [
        _line(x1, y, x2 - d * head, y, color, width),
        f'<polygon points="{_n(x2)},{_n(y)} {_n(x2 - d * head)},{_n(y - 8)} '
        f'{_n(x2 - d * head)},{_n(y + 8)}" fill="{color}"/>',
    ]


def _chip(x: float, y: float, text: str, color: str, theme: Theme, size: float) -> list[str]:
    """``text`` in an outlined pill centered on (x, y)."""
    tw = text_width(text, size, weight=600)
    pw, ph = tw + 22, size * 1.75
    return [
        f'<rect x="{_n(x - pw / 2)}" y="{_n(y - ph / 2)}" width="{_n(pw)}" height="{_n(ph)}" '
        f'rx="{_n(ph / 2)}" fill="{theme.bg}" stroke="{color}" stroke-width="2.5"/>',
        _text(x, y + size * 0.36, text, size=size, fill=color, anchor="middle", weight=600),
    ]


def _box(x: float, y: float, w: float, h: float, theme: Theme, stroke: str, sw: float) -> str:
    return (
        f'<rect x="{_n(x)}" y="{_n(y)}" width="{_n(w)}" height="{_n(h)}" rx="20" '
        f'fill="{theme.bg}" stroke="{stroke}" stroke-width="{_n(sw)}"/>'
    )


def how_it_works(
    index: Mapping[str, Any], spec: Mapping[str, Any], size: tuple[int, int], theme: Theme
) -> str:
    """Your app, the gateway's five steps and the LLM provider; only placeholders cross."""
    del index  # no numbers: the same signature as the other images
    w, h = size
    if (w, h) != (1600, 900):
        raise RecordError("share: how-it-works is drawn at 1600 x 900 only")
    m = 64
    body, _ = _header(
        w,
        theme,
        _type(w, h),
        "How it works",
        "Personal data is swapped for keyed placeholders before a request leaves your side, "
        "and put back in the streamed answer",
    )
    t = _type(w, h)
    footer, _ = _footer(
        w,
        h,
        theme,
        t,
        [
            "Speaks the OpenAI Chat Completions and Responses APIs · fails closed on anything "
            "it cannot mask · the name is fictional"
        ],
        spec["url"],
    )
    body.extend(footer)

    top, bottom, edge = 190, 806, 1098
    # Your side: a tinted region; the provider's side is the bare card.
    body.append(_rect(m - 24, top, edge - (m - 24), bottom - top, theme.panel, rx=24))
    body.append(
        f'<line x1="{edge}" y1="{top - 10}" x2="{edge}" y2="{bottom + 10}" stroke="{theme.axis}" '
        'stroke-width="2.5" stroke-dasharray="10 8"/>'
    )
    tag = t(18)
    body.append(
        _text(
            m,
            top + 34,
            "YOUR SIDE · personal data stays here",
            size=tag,
            fill=theme.muted,
            weight=700,
        )
    )
    body.append(_text(edge + 24, top + 34, "PROVIDER SIDE", size=tag, fill=theme.muted, weight=700))
    body.append(_text(edge + 24, top + 58, "sees placeholders only", size=tag, fill=theme.muted))

    by0, by1 = 270, 782
    app = (m, 180)
    guard = (434, 640)
    prov = (1336, w - m - 1336)
    body.append(_box(app[0], by0, app[1], by1 - by0, theme, theme.axis, 2))
    body.append(_box(guard[0], by0, guard[1], by1 - by0, theme, theme.own, 3.5))
    body.append(_box(prov[0], by0, prov[1], by1 - by0, theme, theme.axis, 2))
    mid = (by0 + by1) / 2
    for (x, bw), lines in ((app, ("Your app", "or agent")), (prov, ("LLM", "provider"))):
        for k, line in enumerate(lines):
            body.append(
                _text(
                    x + bw / 2,
                    mid - 6 + k * 36,
                    line,
                    size=28,
                    fill=theme.ink,
                    anchor="middle",
                    weight=700,
                )
            )

    gx = guard[0] + 30
    body.append(_text(gx, by0 + 50, "PII Guard", size=32, fill=theme.own_ink, weight=700))
    body.append(
        _text(
            gx + text_width("PII Guard", 32, weight=700) + 14,
            by0 + 50,
            "gateway on your machine",
            size=21,
            fill=theme.muted,
        )
    )
    out_y, back_y = by0 + 98, by0 + 382
    body.append(_text(gx, out_y, "ON THE WAY OUT", size=tag, fill=theme.muted, weight=700))
    body.append(_text(gx, back_y, "ON THE WAY BACK", size=tag, fill=theme.muted, weight=700))
    body.append(_line(gx, back_y - 42, guard[0] + guard[1] - 30, back_y - 42, theme.grid, 2))
    step_ys = [out_y + 48 + 52 * i for i in range(4)] + [back_y + 50]
    for n, (sy, step) in enumerate(zip(step_ys, STEPS, strict=True), 1):
        body.append(f'<circle cx="{_n(gx + 17)}" cy="{_n(sy - 8)}" r="17" fill="{theme.own}"/>')
        body.append(
            _text(gx + 17, sy - 8 + 7, str(n), size=19, fill=theme.bg, anchor="middle", weight=700)
        )
        body.append(_text(gx + 50, sy, step, size=23, fill=theme.ink))
    body.append(
        _text(
            gx + 50,
            back_y + 100,
            "The placeholder ↔ value mapping stays here, never sent.",
            size=19,
            fill=theme.muted,
        )
    )

    # Request lane level with steps 1-4, response lane level with step 5.
    req_y, res_y = step_ys[1] + 18, step_ys[4] - 8
    chip_s = 19
    lanes = (
        (app[0] + app[1], guard[0], req_y, _REAL, theme.real, "request"),
        (guard[0] + guard[1], prov[0], req_y, _PLACEHOLDER, theme.own_ink, "masked request"),
        (prov[0], guard[0] + guard[1], res_y, _PLACEHOLDER, theme.own_ink, "streamed answer"),
        (guard[0], app[0] + app[1], res_y, _REAL, theme.real, "restored answer"),
    )
    for a, b, y, chip, color, label in lanes:
        body.extend(_arrow(a, b, y, theme.ink))
        # Right of the boundary, the placeholder chips sit wholly on the provider's side.
        cxm = (edge + prov[0]) / 2 if min(a, b) >= edge - 30 else (a + b) / 2
        body.extend(_chip(cxm, y - 34, chip, color, theme, chip_s))
        body.append(_text(cxm, y + 32, label, size=18, fill=theme.muted, anchor="middle"))

    title = "How PII Guard works"
    desc = (
        "Diagram. Your app or agent sends a request to PII Guard, on your side. On the way "
        "out PII Guard: "
        + "; ".join(f"{i}. {s}" for i, s in enumerate(STEPS[:4], 1))
        + ". Only the masked request, with placeholders in place of personal data, crosses to "
        "the LLM provider. The response streams back to PII Guard, which does: 5. "
        + STEPS[4]
        + ", and your app gets the answer with the real values back. The placeholder-to-value "
        "mapping never leaves PII Guard."
    )
    return _svg(w, h, theme, title, desc, body)


Render = Callable[[Mapping[str, Any], Mapping[str, Any], tuple[int, int], Theme], str]

#: File stem -> (renderer, size keys of :data:`SIZES`), each size in both themes.
IMAGES: dict[str, tuple[Render, tuple[str, ...]]] = {
    "leak-vs-overmasking": (hero, tuple(SIZES)),
    "results-card": (card, tuple(SIZES)),
    "results-by-set": (by_set, tuple(SIZES)),
    "open-ner-models": (open_ner, tuple(SIZES)),
    "results-table": (results_table, ("", "1200x630")),
    "how-it-works": (how_it_works, ("",)),
}


def file_stem(name: str, size_key: str, theme: Theme) -> str:
    """``results-card-1200x630-dark``: name, size (none for the README size), theme."""
    return name + (f"-{size_key}" if size_key else "") + theme.suffix


def render_all(index: Mapping[str, Any], spec: Mapping[str, Any]) -> dict[str, str]:
    """Every image's SVG by file stem (no extension)."""
    out: dict[str, str] = {}
    for name, (render, size_keys) in IMAGES.items():
        for size_key in size_keys:
            for theme in (LIGHT, DARK):
                out[file_stem(name, size_key, theme)] = render(index, spec, SIZES[size_key], theme)
    return out
