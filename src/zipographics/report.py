"""The shareable summary report: one self-contained HTML file (SPEC §5.6 item 3, §5.7, D3).

No scripts, no external requests, no fonts: charts and the map are inline SVG drawn with matplotlib
(Agg backend, text kept as text so it stays small and searchable). A print stylesheet makes
"Print > Save as PDF" in any browser give a clean PDF. Restricted mode: the banner is shown, ZIPs
are in input order, there is no filter state and the map has one neutral fill.
"""

from __future__ import annotations

import html
import io
import math
import re
from collections.abc import Sequence
from datetime import datetime
from typing import Any

import geopandas as gpd
import matplotlib as mpl
import numpy as np
from matplotlib.axes import Axes
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.colors import to_rgba
from matplotlib.figure import Figure
from matplotlib.patches import Patch

from zipographics import charts, metrics
from zipographics.analysis import Analysis
from zipographics.charts import ChartData
from zipographics.export import NOTE_CODED, NOTE_MOE, NOTE_ZIP, attestation, default_metrics
from zipographics.filters import FilterResult, describe
from zipographics.models import UsePolicy
from zipographics.restricted import BANNER, BANNER_TITLE, require_unrestricted
from zipographics.review import review_lines
from zipographics.ui import (
    DAGGER,
    DASH,
    TIER_LABELS,
    fmt_moe,
    fmt_number,
    fmt_value,
)

_TRADE = "#1f4e79"
_BENCH = "#a3acb8"
_NEUTRAL = "#cfd6de"
_MATCH_EDGE = "#b3261e"
CHECK = "\N{CHECK MARK}"
_SVG_RC: dict[Any, Any] = {
    "svg.fonttype": "none",
    "svg.hashsalt": "zipographics",
    "font.family": "sans-serif",
}

_CSS = """
:root { --ink:#1b2430; --muted:#5b6675; --line:#d5dae1; --accent:#1f4e79; --warn:#8a5a00;
  --bg:#ffffff; --card:#f4f6f9; --alert:#fff4e0; }
* { box-sizing: border-box; }
body { margin:0; padding:24px 32px 48px; color:var(--ink); background:var(--bg);
  font-family: system-ui, -apple-system, "Segoe UI", Roboto, Arial, sans-serif; line-height:1.45; }
h1 { margin:0 0 4px; font-size:1.7rem; } h2 { font-size:1.15rem; margin:28px 0 10px;
  border-bottom:2px solid var(--accent); padding-bottom:4px; }
h3 { font-size:.95rem; margin:0 0 4px; }
.meta { color:var(--muted); margin:0 0 12px; } .note { color:var(--muted); font-size:.85rem; }
.banner { background:var(--alert); border-left:6px solid #d98a00; padding:10px 14px; margin:12px 0;
  border-radius:4px; }
.kpis { display:grid; grid-template-columns:repeat(auto-fill,minmax(190px,1fr)); gap:10px; }
.kpi { background:var(--card); border:1px solid var(--line); border-radius:6px; padding:10px 12px;
  break-inside:avoid; } .kpi .label { font-size:.78rem; color:var(--muted); }
.kpi .value { font-size:1.45rem; font-weight:650; }
.kpi .sub { font-size:.8rem; color:var(--muted); }
.charts { display:grid; grid-template-columns:repeat(auto-fit,minmax(380px,1fr)); gap:18px; }
figure { margin:0; break-inside:avoid; } figcaption { font-size:.8rem; color:var(--muted); }
svg { max-width:100%; height:auto; }
table { border-collapse:collapse; width:100%; font-size:.82rem; }
th, td { border-bottom:1px solid var(--line); padding:4px 8px; text-align:right; }
th:nth-child(-n+4), td:nth-child(-n+4), td.zip { text-align:left; }
thead th { background:var(--card); position:sticky; top:0; }
td.caution { color:var(--muted); } td.unrel { color:#6b7280; font-style:italic; }
tr.match td.zip { font-weight:700; } tr.total td { font-weight:650; background:var(--card); }
footer { margin-top:32px; border-top:2px solid var(--line); padding-top:12px; font-size:.8rem;
  color:var(--muted); } footer li { margin:2px 0; } ul.plain { padding-left:18px; }
@media print {
  body { padding:0; font-size:11pt; } h2 { break-after:avoid; page-break-after:avoid; }
  section { break-inside:auto; } #table { break-before:page; page-break-before:always; }
  figure, .kpi { break-inside:avoid; page-break-inside:avoid; } thead th { position:static; }
  tr { break-inside:avoid; page-break-inside:avoid; } a { color:inherit; text-decoration:none; }
}
"""


def _e(text: object) -> str:
    return html.escape(str(text), quote=False)


def _a(text: object) -> str:
    return html.escape(str(text), quote=True)


# ------------------------------------------------------------------------------------ svg
def _clean_svg(svg: str, label: str) -> str:
    """Make matplotlib's SVG safe to inline: no XML prolog, doctype, namespaces or comments."""
    svg = re.sub(r"<\?xml.*?\?>", "", svg, flags=re.S)
    svg = re.sub(r"<!DOCTYPE.*?>", "", svg, flags=re.S)
    svg = re.sub(r"<!--.*?-->", "", svg, flags=re.S)
    svg = re.sub(r"<metadata>.*?</metadata>", "", svg, flags=re.S)
    svg = re.sub(r'\s+xmlns(?::\w+)?="[^"]*"', "", svg)
    return svg.replace("<svg ", f'<svg role="img" aria-label="{_a(label)}" ', 1).strip()


def _to_svg(fig: Figure, label: str) -> str:
    FigureCanvasAgg(fig)
    buf = io.BytesIO()
    with mpl.rc_context(_SVG_RC):
        fig.savefig(buf, format="svg", metadata={"Date": None}, bbox_inches="tight")
    return _clean_svg(buf.getvalue().decode("utf-8"), label)


def _chart_svg(d: ChartData) -> str:
    n = len(d.rows)
    fig = Figure(figsize=(6.2, 0.62 * n + 1.1))
    ax = fig.subplots()
    ys = list(range(n))
    h = 0.36
    trade = [r.trade or 0.0 for r in d.rows]
    bench = [r.bench or 0.0 for r in d.rows]
    ax.barh([y - h / 2 for y in ys], trade, h, color=_TRADE, label="Trade area")
    ax.barh([y + h / 2 for y in ys], bench, h, color=_BENCH, label=d.benchmark_name)
    for y, r in zip(ys, d.rows, strict=True):
        ax.text((r.trade or 0) + 0.004, y - h / 2, DASH if r.trade is None else f"{r.trade:.1%}",
                va="center", fontsize=7, color="#1b2430")  # fmt: skip
        ax.text((r.bench or 0) + 0.004, y + h / 2, DASH if r.bench is None else f"{r.bench:.1%}",
                va="center", fontsize=7, color="#5b6675")  # fmt: skip
    ax.set_yticks(ys, [r.label for r in d.rows], fontsize=8)
    ax.invert_yaxis()
    top = max([*trade, *bench, 0.05])
    ax.set_xlim(0, top * 1.18)
    ax.xaxis.set_major_formatter(lambda v, _p: f"{v:.0%}")
    ax.tick_params(axis="x", labelsize=7)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.legend(fontsize=7, frameon=False, loc="lower right")
    return _to_svg(fig, f"{d.title}: trade area compared with {d.benchmark_name}")


def _shade(ax: Axes, sub: gpd.GeoDataFrame, a: Analysis, metric_id: str) -> None:
    """Quantile-binned fills with a patch legend (no raster colorbar, so the SVG stays vector).

    A ZIP with no value, or a top/bottom-coded one (a bound, not an exact number), is drawn
    neutral. One distinct value makes one bin; no values at all make a plain neutral map.
    """
    metric = metrics.BY_ID[metric_id]
    vals = np.array([_exact(a, z, metric_id) for z in sub["zip"]])
    finite = vals[~np.isnan(vals)]
    neutral = to_rgba(_NEUTRAL)
    if finite.size == 0:
        sub.plot(ax=ax, color=[neutral] * len(sub), edgecolor="#ffffff", linewidth=0.6)
        return
    edges = np.unique(np.quantile(finite, np.linspace(0, 1, 6)))
    bins = max(len(edges) - 1, 1)
    which = np.clip(np.digitize(vals, edges[1:-1], right=True), 0, bins - 1)
    cmap = mpl.colormaps["Blues"]
    shades = [cmap(0.3 + 0.65 * i / max(bins - 1, 1)) for i in range(bins)]
    faces = [neutral if np.isnan(v) else shades[int(w)] for v, w in zip(vals, which, strict=True)]
    sub.plot(ax=ax, color=faces, edgecolor="#ffffff", linewidth=0.6)
    labels = (
        [
            f"{fmt_number(metric, edges[i])} to {fmt_number(metric, edges[i + 1])}"
            for i in range(bins)
        ]
        if len(edges) > 1
        else [fmt_number(metric, edges[0])]
    )
    # "$" starts mathtext in matplotlib: escape it so dollar labels stay dollar labels
    handles = [
        Patch(facecolor=shades[i], label=lb.replace("$", chr(92) + "$"))
        for i, lb in enumerate(labels)
    ]
    ax.legend(handles=handles, title=metric.name, fontsize=7, title_fontsize=7,
              frameon=False, loc="center left", bbox_to_anchor=(1.0, 0.5))  # fmt: skip


def _exact(a: Analysis, zip_code: str, metric_id: str) -> float:
    """The value to shade by, or NaN when unknown or only a published bound (SPEC section 6.2)."""
    v = a.value(zip_code, metric_id)
    return float("nan") if v.estimate is None or v.code != "none" else float(v.estimate)


def _map_svg(
    a: Analysis,
    geo: gpd.GeoDataFrame,
    result: FilterResult | None,
    metric_id: str,
    neutral: bool,
) -> str | None:
    sub = geo[geo["zip"].isin(a.zips)]
    if sub.empty:
        return None
    sub = sub.copy()
    fig = Figure(figsize=(6.4, 4.6))
    ax = fig.subplots()
    if neutral:
        sub.plot(ax=ax, color=_NEUTRAL, edgecolor="#ffffff", linewidth=0.6)
    else:
        _shade(ax, sub, a, metric_id)
        if result is not None and result.active:
            hit = sub[sub["zip"].isin(result.qualifying)]
            if not hit.empty:
                hit.boundary.plot(ax=ax, color=_MATCH_EDGE, linewidth=1.6)
    _, miny, _, maxy = sub.total_bounds
    lat = float((miny + maxy) / 2)
    ax.set_aspect(1 / max(math.cos(math.radians(lat)), 0.2))
    ax.set_axis_off()
    return _to_svg(fig, "Map of the recognized ZIPs")


# ------------------------------------------------------------------------------------ html
def _kpi(a: Analysis, mid: str) -> str:
    m = metrics.BY_ID[mid]
    v = a.trade.values[mid]
    mark = f" {DAGGER}" if v.tier == "unreliable" else ""
    subs: list[str] = []
    moe = fmt_moe(m, v)
    if moe:
        subs.append(_e(moe))
    bench = _e(a.benchmark.name)
    if m.indexable:
        idx = a.index.get(mid)
        if idx is not None and idx.value is not None:
            subs.append(f"Index {idx.value} vs {bench}")
        else:
            subs.append("No index" + (" (outside the published range)" if v.code != "none" else ""))
    else:
        share = a.share_of_benchmark(mid)
        if share is not None:
            noun = "households" if mid == "hh" else "population" if mid == "pop" else m.name.lower()
            subs.append(f"{share * 100:.1f} % of {bench}&#39;s {_e(noun)}")
    subs.append(_e(TIER_LABELS[v.tier]))
    return (
        f'<div class="kpi"><div class="label">{_e(m.name)}</div>'
        f'<div class="value">{_e(fmt_value(m, v))}{mark}</div>'
        f'<div class="sub">{" &middot; ".join(subs)}</div></div>'
    )


def _cell(a: Analysis, z: str, mid: str) -> str:
    m = metrics.BY_ID[mid]
    v = a.value(z, mid)
    text = fmt_value(m, v)
    cls = {"good": "", "caution": ' class="caution"', "unreliable": ' class="unrel"'}[v.tier]
    if v.tier == "unreliable" and v.estimate is not None:
        text += f" {DAGGER}"
    moe = fmt_moe(m, v)
    title = f' title="{_a(moe)}"' if moe else ""
    return f"<td{cls}{title}>{_e(text)}</td>"


def _table(
    a: Analysis,
    result: FilterResult | None,
    ids: Sequence[str],
    order: Sequence[str],
    shown_filters: bool,
) -> str:
    lead = ["ZIP", "City", "County", "State"]
    if a.weighted:
        lead += ["Overlap %", "In-radius households", "In-radius population"]
    head = [*lead, *[metrics.BY_ID[m].name for m in ids], *(["Matches"] if shown_filters else [])]
    rows = []
    for z in order:
        f = a.row_facts(z)
        cells = [f'<td class="zip">{_e(z)}</td>'] + [
            f"<td>{_e(f[k] or '')}</td>" for k in ("city", "county", "state")
        ]
        if a.weighted:
            pct = a.overlap_pct(z)
            hh, pop = a.in_radius(z, "hh"), a.in_radius(z, "pop")
            cells += [
                f"<td>{'' if pct is None else f'{pct:g}'}</td>",
                f"<td>{_e(fmt_number(metrics.BY_ID['hh'], hh))}</td>",
                f"<td>{_e(fmt_number(metrics.BY_ID['pop'], pop))}</td>",
            ]
        cells += [_cell(a, z, mid) for mid in ids]
        match = bool(shown_filters and result is not None and result.matches[z].qualifies)
        if shown_filters:
            cells.append(f"<td>{CHECK if match else ''}</td>")
        cls = ' class="match"' if match else ""
        rows.append(f"<tr{cls}>{''.join(cells)}</tr>")
    for label, name, values in (
        ("Trade area", f"All {len(a.zips)} ZIPs", a.trade.values),
        ("Benchmark", a.benchmark.name, a.bench.values),
    ):
        cells = [f'<td colspan="{len(lead)}"><strong>{label}</strong> {_e(name)}</td>']
        cells += [f"<td>{_e(fmt_value(metrics.BY_ID[mid], values[mid]))}</td>" for mid in ids]
        if shown_filters:
            cells.append("<td></td>")
        rows.append(f'<tr class="total">{"".join(cells)}</tr>')
    th = "".join(f"<th>{_e(h)}</th>" for h in head)
    return f"<table><thead><tr>{th}</tr></thead><tbody>{''.join(rows)}</tbody></table>"


def _sources(a: Analysis) -> str:
    return (
        '<section id="sources"><h2>Sources</h2><ul class="plain">'
        f"<li>{_e(a.vintage_label)}: U.S. Census Bureau, American Community Survey, via the "
        'Census <a href="https://www.census.gov/data/developers/data-sets/acs-5year.html">'
        "Data API</a>.</li>"
        "<li>ZIP code tabulation areas: U.S. Census Bureau, "
        '<a href="https://www.census.gov/programs-surveys/geography/guidance/geo-areas/zctas.html">'
        "ZCTA documentation</a>; ZCTA-to-county relationship file.</li>"
        "<li>City names: GeoNames, "
        '<a href="https://www.geonames.org/">geonames.org</a>, CC BY 4.0.</li></ul></section>'
    )


def render(
    a: Analysis,
    result: FilterResult | None,
    *,
    geo: gpd.GeoDataFrame | None,
    now: datetime,
    version: str,
    metric_ids: Sequence[str] | None = None,
    order: Sequence[str] | None = None,
    map_metric: str | None = None,
) -> str:
    """The report as one HTML string. Restricted mode refuses a result that carries rules."""
    policy: UsePolicy = a.policy
    locked = a.restricted
    if locked and result is not None and result.active:
        require_unrestricted(policy, "select")
    shown_filters = bool(result is not None and result.active and not locked)
    ids = list(metric_ids) if metric_ids is not None else list(default_metrics(a))
    zips = list(a.zips)
    if order is not None and not locked:
        if sorted(order) != sorted(zips):
            raise ValueError("The requested order must list every recognized ZIP exactly once.")
        zips = list(order)
    chosen_map = map_metric or next((m for m in a.lens.kpis if metrics.BY_ID[m].indexable), "owner")

    parts: list[str] = []
    mode = "In-radius estimate (Zipcator overlap)" if a.weighted else "Full ZIPs"
    meta = " &middot; ".join(
        _e(x)
        for x in (
            now.strftime("%Y-%m-%d"),
            policy.vertical or "Industry not given",
            f"Benchmark: {a.benchmark.name}",
            f"Estimate mode: {mode}",
            a.vintage_label,
        )
    )
    parts.append(f'<header><h1>{_e(a.title)}</h1><p class="meta">{meta}</p>')
    if locked:
        body = BANNER[len(BANNER_TITLE) :].strip()
        parts.append(
            f'<div class="banner" role="note"><strong>{_e(BANNER_TITLE)}</strong> {_e(body)}</div>'
        )
    parts.append(f'<p class="note">{_e(NOTE_ZIP)}</p></header>')

    parts.append('<section id="kpis"><h2>Key figures</h2><div class="kpis">')
    parts += [_kpi(a, mid) for mid in a.lens.all_kpis]
    parts.append("</div></section>")

    parts.append('<section id="charts"><h2>Trade area vs benchmark</h2><div class="charts">')
    for d in charts.charts_for(a):
        note = f"<figcaption>{_e(d.note)}</figcaption>" if d.note else ""
        parts.append(f"<figure><h3>{_e(d.title)}</h3>{_chart_svg(d)}{note}</figure>")
    parts.append("</div></section>")

    parts.append('<section id="map"><h2>Map</h2>')
    svg = _map_svg(a, geo, result, chosen_map, neutral=locked) if geo is not None else None
    if svg is None:
        parts.append("<p>The map is unavailable for this report (no boundaries were loaded).</p>")
    else:
        caption = (
            "Recognized ZIPs with one neutral fill (restricted mode)"
            if locked
            else f"Shaded by {metrics.BY_ID[chosen_map].name}"
            + ("; ZIPs that match the filters are outlined" if shown_filters else "")
        )
        parts.append(
            f"<figure>{svg}<figcaption>{_e(caption)}. Boundaries are simplified and "
            "indicative.</figcaption></figure>"
        )
    parts.append("</section>")

    if shown_filters and result is not None:
        rules = "".join(f"<li>{_e(describe(r))}</li>" for r in result.rules)
        parts.append(
            f'<section id="filters"><h2>Filters applied</h2><ul class="plain">{rules}</ul>'
            f"<p>{_e(result.summary_line() or '')}</p></section>"
        )

    parts.append(
        '<section id="table"><h2>ZIP codes</h2>'
        f"{_table(a, result, ids, zips, shown_filters)}</section>"
    )

    notes = [
        _e(x)
        for x in (
            "Estimates carry a margin of error at the 90 % confidence level; "
            f"{DAGGER} marks an unreliable estimate (coefficient of variation above 30 %) and "
            "muted text means use with caution (15-30 %).",
            NOTE_MOE,
            NOTE_CODED,
        )
    ]
    notes += [_e(line) for line in review_lines(a.summary)]
    parts.append(
        '<section id="notes"><h2>Data notes</h2><ul class="plain">'
        + "".join(f"<li>{n}</li>" for n in notes)
        + "</ul></section>"
    )
    parts.append(_sources(a))
    foot = "".join(
        f"<li>{_e(line)}</li>" for line in attestation(a, result, now=now, version=version)
    )
    parts.append(f'<footer><ul class="plain">{foot}</ul></footer>')

    title = f"{_e(a.title)} - Zipographics report"
    return (
        '<!doctype html>\n<html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{title}</title><style>{_CSS}</style></head><body>"
        + "\n".join(parts)
        + "</body></html>\n"
    )
