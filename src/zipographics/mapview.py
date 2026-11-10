"""The map layer: GeoJSON, style and legend for the recognized ZIPs (SPEC §5.5, §5.7).

Library-level restricted enforcement, same standard as ``filters``: when the Analysis's own policy
is restricted, :func:`layer` returns the **neutral** style for every metric (one fill, one outline,
no legend, no qualifying highlight), ignores which metric was asked for, and refuses a filter
result that carries rules. Tooltips still show values as context. The folium rendering in the app
is a thin wrapper around the dict returned here; the report's static map shares
:func:`classify`.
"""

from __future__ import annotations

import html
import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal

import geopandas as gpd
import numpy as np
from shapely.geometry import mapping

from zipographics import metrics
from zipographics.analysis import Analysis
from zipographics.filters import FilterResult
from zipographics.restricted import require_unrestricted
from zipographics.ui import fmt_moe, fmt_number, fmt_value

NEUTRAL = "#9aa7b4"  # mid grey: still visible on a street map (and on the report's white page)
#: Sequential blues (ColorBrewer, colorblind-safe), light to dark.
_PALETTE = ("#c6dbef", "#9ecae1", "#6baed6", "#3182bd", "#08519c")
_OUTLINE, _OUTLINE_MATCH, _OUTLINE_UNRELIABLE = "#ffffff", "#111111", "#444444"
_OUTLINE_NEUTRAL = "#2f3e4e"  # restricted mode: one fill, one clearly visible outline
_FILL_OPACITY = 0.82
_DASH = "4 3"


@dataclass(frozen=True, slots=True)
class LegendItem:
    label: str
    color: str


@dataclass(frozen=True)
class MapLayer:
    style: Literal["choropleth", "neutral"]
    metric_id: str | None  # None for the neutral style: no metric chooses a color
    legend_title: str | None
    geojson: dict[str, Any]
    legend: tuple[LegendItem, ...]
    bounds: tuple[tuple[float, float], tuple[float, float]]  # ((south, west), (north, east))
    missing: tuple[str, ...]  # recognized ZIPs that have no polygon
    note: str | None


@dataclass(frozen=True)
class Classification:
    """Quantile bins of the exact values: a bin index per ZIP (None = draw neutral)."""

    edges: tuple[float, ...]
    bins: tuple[int | None, ...]
    shades: tuple[str, ...]  # one per bin, light to dark
    labels: tuple[str, ...]


def _shades(k: int) -> tuple[str, ...]:
    if k <= 1:
        return (_PALETTE[3],)
    return tuple(_PALETTE[round(i * (len(_PALETTE) - 1) / (k - 1))] for i in range(k))


def exact_value(a: Analysis, zip_code: str, metric_id: str) -> float | None:
    """The value to shade by; None when unknown or only a published bound (SPEC §6.2)."""
    v = a.value(zip_code, metric_id)
    if v.estimate is None or v.code != "none" or not math.isfinite(v.estimate):
        return None
    return float(v.estimate)


def classify(a: Analysis, zips: Sequence[str], metric_id: str, bins: int = 5) -> Classification:
    """Quantile classes of ``metric_id`` over ``zips``; one distinct value makes one class."""
    metric = metrics.BY_ID[metric_id]
    values = [exact_value(a, z, metric_id) for z in zips]
    finite = np.array([v for v in values if v is not None])
    if finite.size == 0:
        return Classification((), tuple(None for _ in values), (), ())
    edges = np.unique(np.quantile(finite, np.linspace(0, 1, bins + 1)))
    k = max(len(edges) - 1, 1)
    which = np.clip(np.digitize(finite, edges[1:-1], right=True), 0, k - 1) if k > 1 else None
    it = iter(range(len(finite)))
    out: list[int | None] = []
    for v in values:
        if v is None:
            out.append(None)
        else:
            i = next(it)
            out.append(0 if which is None else int(which[i]))
    if len(edges) > 1:
        labels = tuple(
            f"{fmt_number(metric, edges[i])} to {fmt_number(metric, edges[i + 1])}"
            for i in range(k)
        )
    else:
        labels = (fmt_number(metric, edges[0]),)
    return Classification(tuple(float(e) for e in edges), tuple(out), _shades(k), labels)


def _tooltip(a: Analysis, z: str, metric_ids: Sequence[str]) -> str:
    facts = a.row_facts(z)
    place = ", ".join(x for x in (facts["city"], facts["county"], facts["state"]) if x)
    lines = [f"<b>{html.escape(z)}</b> {html.escape(place)}"]
    for mid in metric_ids:
        m = metrics.BY_ID[mid]
        v = a.value(z, mid)
        text = html.escape(fmt_value(m, v))
        moe = fmt_moe(m, v)
        extra = f" {html.escape(moe)}" if moe else ""
        flag = (
            " (Unreliable \N{DAGGER})" if v.tier == "unreliable" and v.estimate is not None else ""
        )
        lines.append(f"{html.escape(m.name)}: {text}{extra}{flag}")
    return "<br>".join(lines)


def layer(
    a: Analysis, metric: str | None, result: FilterResult | None, geo: gpd.GeoDataFrame | None
) -> MapLayer | None:
    """The map layer for ``a``'s recognized ZIPs, or None without geometry for any of them.

    Restricted analysis: neutral style whatever ``metric`` is; a ``result`` with rules raises
    :class:`~zipographics.errors.RestrictedUseError`.
    """
    locked = a.restricted
    if locked and result is not None and result.active:
        require_unrestricted(a.policy, "select")
    if not locked and (metric is None or metric not in metrics.BY_ID):
        raise ValueError(f"Unknown metric: {metric!r}")
    if geo is None:
        return None
    sub = geo[geo["zip"].isin(a.zips)]
    if sub.empty:
        return None
    zips = [str(z) for z in sub["zip"]]
    missing = tuple(z for z in a.zips if z not in set(zips))
    shown = ["pop", "hh"]
    if locked:
        shown += [m for m in a.lens.columns if m not in shown][:3]
        cls = None
    else:
        assert metric is not None
        cls = classify(a, zips, metric)
        if metric not in shown:
            shown.append(metric)
    wins = set(result.qualifying) if result is not None and result.active and not locked else None
    features = []
    for i, (z, geom) in enumerate(zip(zips, sub.geometry, strict=True)):
        fill, outline, weight, dash = NEUTRAL, _OUTLINE_NEUTRAL if locked else _OUTLINE, 0.8, None
        props: dict[str, Any] = {"zip": z}
        if cls is not None and cls.bins[i] is not None:
            fill = cls.shades[cls.bins[i]]  # type: ignore[index]
        if cls is not None and metric is not None:
            v = a.value(z, metric)
            if v.tier == "unreliable" and v.estimate is not None:
                outline, weight, dash = _OUTLINE_UNRELIABLE, 1.2, _DASH
        if wins is not None:
            props["qualifies"] = z in wins
            if z in wins:
                outline, weight, dash = _OUTLINE_MATCH, 3.0, None
        if locked:
            weight = 1.4
        props["style"] = {
            "fillColor": fill, "color": outline, "weight": weight,
            "dashArray": dash, "fillOpacity": _FILL_OPACITY,
        }  # fmt: skip
        props["tooltip"] = _tooltip(a, z, shown)
        features.append({"type": "Feature", "geometry": mapping(geom), "properties": props})
    minx, miny, maxx, maxy = (float(x) for x in sub.total_bounds)
    legend = tuple(LegendItem(lb, cls.shades[j]) for j, lb in enumerate(cls.labels)) if cls else ()
    note = None
    if missing:
        note = (
            f"{len(missing)} of {len(a.zips)} ZIPs have no boundary on the map and are not drawn."
        )
    return MapLayer(
        style="neutral" if locked else "choropleth",
        metric_id=None if locked else metric,
        legend_title=None if locked or metric is None else metrics.BY_ID[metric].name,
        geojson={"type": "FeatureCollection", "features": features},
        legend=legend,
        bounds=((miny, minx), (maxy, maxx)),
        missing=missing,
        note=note,
    )
