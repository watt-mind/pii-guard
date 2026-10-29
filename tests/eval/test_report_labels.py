"""Chart label overlap guards (LAB-1193, LAB-1224): value and axis labels must not collide."""

from __future__ import annotations

import re

from pii_guard.eval import report_charts as charts

_TEXT = re.compile(r"<text[^>]*x=\"([\d.]+)\" y=\"([\d.]+)\"[^>]*>(.*?)</text>")


def _labels(svg: str) -> list[tuple[float, float, str]]:
    out = []
    for m in _TEXT.finditer(svg):
        out.append((float(m.group(1)), float(m.group(2)), m.group(3)))
    return out


def _no_overlap(
    labels: list[tuple[float, float, str]], size: float, *, y_tol: float = 12.0
) -> None:
    for i, (x1, y1, t1) in enumerate(labels):
        w1 = charts.text_width(t1, size, bold=False)
        for x2, y2, t2 in labels[i + 1 :]:
            if abs(y1 - y2) > y_tol:
                continue
            w2 = charts.text_width(t2, size, bold=False)
            assert abs(x1 - x2) >= (w1 + w2) / 2 - 1.0, f"overlap: {t1!r} vs {t2!r}"


def _visual_index(n_systems: int = 13) -> dict:
    systems = {f"visual:sys-{i}": {"short_label": f"sys-{i}"} for i in range(n_systems)}
    runs = [
        {
            "system": f"visual:sys-{i}",
            "fixture_set": "fictional-specimens",
            "date": "2026-10-29",
            "commit": "abc1234",
            "specimens": 4,
            "countries": 2,
            "overall": {"recall_iou50": 0.5 + 0.03 * i, "regions": 10},
            "by_region_type": {
                "text": {"recall_iou50": 0.9, "regions": 6},
                "portrait": {"recall_iou50": 0.4, "regions": 4},
            },
            "by_doc_type": {},
            "by_country": {"hu": 1},
            "over_masking_mean": 0.0,
            "latency_ms": None,
            "cost_usd": None,
        }
        for i in range(n_systems)
    ]
    return {"systems": systems, "colours": {"visual": {}}, "visual": runs}


def test_visual_recall_value_labels_do_not_overlap() -> None:
    svg = charts.visual_recall(_visual_index())
    # Value labels sit just above the bars (plot area y < 670); legend text is above it.
    values = [(x, y, t) for x, y, t in _labels(svg) if y < 660 and t.endswith("%")]
    assert values, "expected value labels in the chart"
    _no_overlap(values, 18)


def test_progress_date_labels_do_not_overlap() -> None:
    systems = {
        "rules": {
            "family": "pii-guard",
            "kind": "text",
            "short_label": "rules",
            "color": "#0072B2",
        }
    }
    history = [
        {
            "system": "rules",
            "fixture_set": "smoke",
            "date": f"2026-10-{10 + i:02d}",
            "commit": f"c{i:07d}",
            "comparable": True,
            "all": {"leak": 0.4 - 0.01 * i},
        }
        for i in range(10)
    ]
    index = {
        "systems": systems,
        "history": history,
        "fixture_sets": {"smoke": {"languages": ["en"], "documents": {"en": 10}}},
    }
    svg = charts.progress(index, fixture_set="smoke", systems=["rules"])
    dates = [(x, y, t) for x, y, t in _labels(svg) if t.startswith("2026-")]
    assert dates, "expected date labels under the axis"
    _no_overlap(dates, 20)
