"""SVG layout primitives, color themes, and spec parsing for shareable benchmark cards."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from html import escape
from typing import Any

from pii_guard.eval.record import RecordError

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
            return s
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
