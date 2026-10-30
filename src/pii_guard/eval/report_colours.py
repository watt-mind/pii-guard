"""Stable chart colours: a committed, append-only registry of system -> colour (and shape).

Colours used to follow each system's position in the sorted system list, so adding one system
recoloured every system after it and rewrote every chart and both index files. The registry
(``docs/benchmarks/colours.json``) pins every system it has seen. ``pii-guard eval report``
only ever *adds* entries: a new system takes the least-used entry of its palette (ties go to
palette order), existing entries never move, and entries of systems with no records left are
kept so a system that comes back gets its old colour.

Sections:

- ``systems``: the colour and marker shape of each detection system in the index (the UI and
  the leak-vs-latency, by-language, progress and type-recall charts). pii-guard systems take
  :data:`~pii_guard.eval.report_index.PALETTE_OURS` with a circle; comparison tools are grey
  and told apart by shape.
- ``visual``: the bar colour of each system in the visual-recall chart.
- ``latency``: the bar colour of each gateway-latency system in the latency chart.

Palette values are unchanged, so the UI's dark-canvas overrides for ``#882255`` and
``#332288`` (``ui/src/index.css``, LAB-1155) keep matching.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

__all__ = [
    "ABOUT",
    "DEFAULT_REGISTRY",
    "PALETTE_LATENCY",
    "PALETTE_VISUAL",
    "SECTIONS",
    "assign",
    "dumps_registry",
    "load_registry",
]

DEFAULT_REGISTRY = Path("docs/benchmarks/colours.json")
SECTIONS = ("systems", "visual", "latency")
ABOUT = (
    "Stable chart colours, maintained by `pii-guard eval report`: a new system takes the "
    "least-used palette entry, existing entries never change. Edit a value by hand only to "
    "recolour a system on purpose."
)

#: Visual-recall bars (Okabe-Ito blue, then Paul Tol muted), assigned per system.
PALETTE_VISUAL = [
    "#0072B2",
    "#332288",
    "#44AA99",
    "#CC6677",
    "#88CCEE",
    "#DDCC77",
    "#117733",
    "#AA4499",  # 8th: Paul Tol muted purple, distinct from the Blues/Greens above (LAB-1202)
]
#: Latency bars, assigned per gateway-latency system.
PALETTE_LATENCY = ["#0072B2", "#009E73", "#D55E00", "#CC79A7", "#332288", "#999933"]


def load_registry(path: Path) -> dict[str, dict[str, Any]]:
    """The registry at ``path``; empty sections when the file does not exist yet."""
    data: dict[str, Any] = {}
    if path.is_file():
        data = json.loads(path.read_text(encoding="utf-8"))
    return {name: dict(data.get(name) or {}) for name in SECTIONS}


def dumps_registry(registry: Mapping[str, Mapping[str, Any]]) -> str:
    """Sorted keys, so concurrent PRs adding different systems touch different lines."""
    body = {"about": ABOUT, **{name: dict(registry.get(name) or {}) for name in SECTIONS}}
    return json.dumps(body, indent=2, ensure_ascii=False, sort_keys=True) + "\n"


def assign(
    section: dict[str, Any], keys: Iterable[str], candidates: Sequence[Any]
) -> dict[str, Any]:
    """Give every key in ``keys`` without an entry the least-used of ``candidates``.

    Mutates and returns ``section``. A key whose entry is not one of ``candidates`` (say, a
    system that moved from comparison to pii-guard) is re-assigned. Deterministic in the order
    of ``keys``, which callers make a pure function of the records.
    """
    for key in keys:
        if section.get(key) in candidates:
            continue
        used = list(section.values())
        section[key] = min(candidates, key=lambda c: (used.count(c), candidates.index(c)))
    return section
