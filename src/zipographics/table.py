"""The ZIP table: ordering and the display view, policy-enforced (SPEC §5.5, §5.7).

Input order and ZIP order are always allowed. Ordering by any metric is ranking ZIPs by a
demographic characteristic, so restricted mode refuses it for **every** metric (D4); the index
toggle, a filter result with rules and "only matching ZIPs" are refused too. :func:`build_view`
returns display strings and CSS for the grid; the app only renders them.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

import pandas as pd

from zipographics import metrics, stats
from zipographics.analysis import Analysis
from zipographics.filters import FilterResult
from zipographics.restricted import label_of, require_unrestricted
from zipographics.ui import DAGGER, DASH, fmt_index, fmt_moe, fmt_number, fmt_value

INPUT = "input"
ZIP = "zip"


def order(
    a: Analysis,
    key: str,
    *,
    descending: bool = False,
    index: bool = False,
) -> tuple[str, ...]:
    """The recognized ZIPs of ``a`` ordered by ``key``: ``"input"``, ``"zip"`` or a metric id.

    ``index=True`` orders by the ZIP's index against the benchmark instead of its value. Unknown
    values sort last in both directions; ties keep input order. Ordering by anything but input or
    ZIP order is ranking by a demographic characteristic: it raises
    :class:`~zipographics.errors.RestrictedUseError` when the Analysis's own policy is restricted.
    """
    if key == INPUT:
        return a.zips[::-1] if descending else a.zips
    if key == ZIP:
        return tuple(sorted(a.zips, reverse=descending))
    require_unrestricted(a.policy, "rank")
    if key not in metrics.BY_ID:
        raise ValueError(f"Unknown order key: {key!r}")
    if index:
        if not metrics.BY_ID[key].indexable:
            raise ValueError(f"{metrics.BY_ID[key].name} is a count and has no index.")
        values: list[float | None] = [v.value for v in a.zip_index(key)]
    else:
        values = [a.value(z, key).estimate for z in a.zips]
    known = [
        (v, z) for v, z in zip(values, a.zips, strict=True) if v is not None and not math.isnan(v)
    ]
    unknown = tuple(z for v, z in zip(values, a.zips, strict=True) if v is None or math.isnan(v))
    known.sort(key=lambda item: item[0], reverse=descending)  # stable, so ties keep input order
    return tuple(z for _, z in known) + unknown


_CAUTION = "color: #5b6675"
_UNRELIABLE = "color: #6b7280; font-style: italic"
_MATCH_ZIP = "font-weight: 700"
CHECK = "\N{CHECK MARK}"
PM = "\N{PLUS-MINUS SIGN}"


@dataclass(frozen=True)
class TableView:
    zips: tuple[str, ...]  # the rows, in display order
    frame: pd.DataFrame  # strings only: ZIPs stay text, unknown values are an em dash
    styles: pd.DataFrame  # CSS per cell, same shape as ``frame``
    help: dict[str, str]  # column header tooltips


@dataclass(frozen=True, slots=True)
class UnreliableCell:
    zip: str
    metric_id: str
    metric: str
    estimate: str
    moe: str
    cv: float | None  # coefficient of variation in percent


def _check_ids(ids: Sequence[str]) -> list[str]:
    unknown = [m for m in ids if m not in metrics.BY_ID]
    if unknown:
        raise ValueError(f"Unknown metric: {unknown[0]!r}")
    return list(ids)


def _tier_css(tier: stats.Tier, estimate: float | None) -> str:
    if estimate is None:
        return ""
    return {"good": "", "caution": _CAUTION, "unreliable": _UNRELIABLE}[tier]


def _columns(ids: Sequence[str], index: bool, show_moe: bool) -> list[tuple[str, str, str]]:
    """(header, metric id, kind) for each metric column; kind is value, index or moe."""
    out: list[tuple[str, str, str]] = []
    for mid in ids:
        m = metrics.BY_ID[mid]
        if index and m.indexable:
            out.append((f"{m.name} (index)", mid, "index"))
        else:
            out.append((m.name, mid, "value"))
        if show_moe:
            out.append((f"{m.name} {PM}", mid, "moe"))
    return out


def build_view(
    a: Analysis,
    result: FilterResult | None,
    *,
    metric_ids: Sequence[str] | None = None,
    show_moe: bool = False,
    index: bool = False,
    sort: str = INPUT,
    descending: bool = False,
    only_matching: bool = False,
) -> TableView:
    """The table the dashboard shows: ZIP, City, County, State, Population, Households, in-radius
    columns when on, then the metric columns (values, or indexes with ``index``), optional margins
    of error, and a Matches column when filters are active.

    Restricted analysis: ``index``, a ``sort`` by anything but ``input``/``zip``, a ``result``
    with rules and ``only_matching`` with one all raise
    :class:`~zipographics.errors.RestrictedUseError`.
    """
    # Population and Households are always the first columns, so they are never repeated
    ids = [
        m
        for m in _check_ids(metric_ids if metric_ids is not None else a.lens.columns)
        if m not in ("pop", "hh")
    ]
    active = result is not None and result.active
    if active:
        require_unrestricted(a.policy, "select")
    if index:
        require_unrestricted(a.policy, "rank")
    by_index = index and sort not in (INPUT, ZIP)
    zips = order(a, sort, descending=descending, index=by_index)
    if only_matching and active:
        assert result is not None
        zips = tuple(z for z in zips if result.matches[z].qualifies)

    head = ["ZIP", "City", "County", "State", "Population", "Households"]
    if a.weighted:
        head += ["Overlap %", "In-radius households"]
    columns = _columns(ids, index, show_moe)
    head += [h for h, _, _ in columns]
    if active:
        head.append("Matches")

    idx_cols = {mid: a.zip_index(mid) for mid in ids if index and metrics.BY_ID[mid].indexable}
    pos = {z: i for i, z in enumerate(a.zips)}
    rows: list[list[str]] = []
    css: list[list[str]] = []
    for z in zips:
        f = a.row_facts(z)
        cells = [z, f["city"] or "", f["county"] or "", f["state"] or ""]
        style = ["", "", "", ""]
        for mid in ("pop", "hh"):
            v = a.value(z, mid)
            cells.append(fmt_value(metrics.BY_ID[mid], v))
            style.append(_tier_css(v.tier, v.estimate))
        if a.weighted:
            hh = fmt_number(metrics.BY_ID["hh"], a.in_radius(z, "hh"))
            cells += [f"{a.overlap_pct(z):g}", hh]
            style += ["", ""]
        for _, mid, kind in columns:
            m = metrics.BY_ID[mid]
            v = a.value(z, mid)
            if kind == "index":
                iv = idx_cols[mid][pos[z]]
                mark = f" {DAGGER}" if iv.tier == "unreliable" and iv.value is not None else ""
                cells.append(fmt_index(iv) + mark)
                style.append(_tier_css(iv.tier, iv.value))
            elif kind == "moe":
                cells.append(fmt_moe(m, v))
                style.append("")
            else:
                mark = f" {DAGGER}" if v.tier == "unreliable" and v.estimate is not None else ""
                cells.append(fmt_value(m, v) + mark)
                style.append(_tier_css(v.tier, v.estimate))
        match = bool(active and result is not None and result.matches[z].qualifies)
        if active:
            cells.append(CHECK if match else "")
            style.append("")
        if match:
            style[0] = _MATCH_ZIP
        rows.append(cells)
        css.append(style)
    frame = pd.DataFrame(rows, columns=head, dtype="object")
    styles = pd.DataFrame(css, columns=head, dtype="object")
    helps = {"ZIP": "Census ZIP Code Tabulation Area (ZCTA); not every USPS ZIP is one."}
    notes = {"index": " Shown as an index: 100 = the benchmark.", "moe": " Margin of error.",
             "value": ""}  # fmt: skip
    for header, mid, kind in columns:
        m = metrics.BY_ID[mid]
        tag = label_of(m)
        helps[header] = m.help + notes[kind] + (f" Characteristic: {tag}." if tag else "")
    return TableView(tuple(zips), frame, styles, helps)


def unreliable_cells(a: Analysis, metric_ids: Sequence[str]) -> list[UnreliableCell]:
    """Every ZIP value whose tier is unreliable, with its estimate, margin and CV, for the
    "Why are some values grey?" expander."""
    ids = _check_ids(metric_ids)
    out: list[UnreliableCell] = []
    for z in a.zips:
        for mid in ids:
            m = metrics.BY_ID[mid]
            v = a.value(z, mid)
            if v.tier == "unreliable" and v.estimate is not None:
                cv = stats.cv(v.estimate, v.moe)
                out.append(
                    UnreliableCell(z, mid, m.name, fmt_value(m, v), fmt_moe(m, v) or DASH, cv)
                )
    return out
