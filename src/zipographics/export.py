"""Exports: ZIP lists, CSV (plain and Excel-safe), the attestation, file names (SPEC §5.6, §5.7).

One function, :func:`attestation`, produces the footer for every export so they agree. Restricted
mode is enforced here: the ZIP list is exactly the user's input ZIPs, the CSV carries no filter
state, no index columns and always the input order.
"""

from __future__ import annotations

import csv
import io
import math
import re
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from typing import Literal

from zipographics import metrics
from zipographics.analysis import Analysis
from zipographics.filters import FilterResult, describe
from zipographics.models import UsePolicy
from zipographics.profile import IndexValue, MetricValue
from zipographics.restricted import (
    AD_PLATFORM_NOTICE,
    NOT_LEGAL_ADVICE,
    is_restricted,
    require_unrestricted,
)
from zipographics.ui import TIER_LABELS, clean_text
from zipographics.verticals import RESTRICTED_QUESTION

Style = Literal["comma", "newline"]

_MAX_STEM = 60
_ILLEGAL = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_FORMULA_LEAD = ("=", "+", "-", "@", "\t", "\r")
BOM = "﻿"

NOTE_CODED = (
    "Values ending in + or - are top-coded (+) or bottom-coded (-) medians: the true value is at "
    "or above (+) or at or below (-) that figure, and they have no margin of error or index."
)
NOTE_ZIP = "ZIP = Census ZCTA; PO-box-only and single-organization ZIPs aren't included."
NOTE_MOE = (
    "ACS figures are survey estimates with margins of error at the 90 % confidence level; "
    "aggregated MOEs and in-radius estimates are approximations."
)
NOTE_CENSUS = (
    "This product uses the Census Bureau Data API but is not endorsed or certified by the "
    "Census Bureau."
)
NOTE_GEONAMES = "ZIP-to-city names: GeoNames (geonames.org), licensed CC BY 4.0."


# ------------------------------------------------------------------------- file names
def file_stem(project: str | None) -> str:
    """A project name made safe for a Windows file name (or ``zipographics`` if nothing is left)."""
    text = _ILLEGAL.sub("_", clean_text(project)).strip(" .")
    if not re.search(r"[^\W_]", text):  # nothing but punctuation and underscores is left
        return "zipographics"
    return text[:_MAX_STEM].rstrip(" .")


def filenames(project: str | None, today: date) -> dict[str, str]:
    stem = f"{file_stem(project)}_{today.isoformat()}"
    return {
        "csv": f"{stem}_zips.csv",
        "csv_excel": f"{stem}_zips_excel.csv",
        "ziplist": f"{stem}_ziplist.txt",
        "report": f"{stem}_report.html",
    }


# ------------------------------------------------------------------------- ZIP list
def ad_platform_notice(policy: UsePolicy | None) -> str | None:
    """The notice shown above the ZIP list in restricted mode (and when no policy is known)."""
    return AD_PLATFORM_NOTICE if is_restricted(policy) else None


def zip_list(
    a: Analysis,
    *,
    qualifying: Sequence[str] | None = None,
    include_not_found: bool = True,
    style: Style = "comma",
) -> str:
    """ZIPs for an ad platform, with no header or footer (it must paste and upload cleanly).

    Restricted mode (the Analysis's own policy) returns exactly the valid input ZIPs in input order
    and ignores ``qualifying`` and ``include_not_found``. Otherwise: the qualifying ZIPs when a
    subset is given, else every input ZIP (not-found ones too unless ``include_not_found`` is
    false).
    """
    if style not in ("comma", "newline"):
        raise ValueError(f"Unknown ZIP list style {style!r}: use comma or newline.")
    entered = a.parsed.zips
    if a.restricted:
        chosen: Sequence[str] = entered
    elif qualifying is not None:
        unknown = [z for z in qualifying if z not in a.zips]
        if unknown:
            raise ValueError(
                f"Qualifying ZIPs must be recognized ZIPs; not recognized: {unknown[0]}"
            )
        wanted = set(qualifying)
        chosen = [z for z in entered if z in wanted]
    elif include_not_found:
        chosen = entered
    else:
        recognized = set(a.zips)
        chosen = [z for z in entered if z in recognized]
    return (", " if style == "comma" else "\n").join(chosen)


# ------------------------------------------------------------------------- attestation
def _benchmark_label(a: Analysis) -> str:
    level = "national" if a.benchmark.level == "us" else a.benchmark.level
    return f"{a.benchmark.name} ({level})"


def _stamp(now: datetime) -> str:
    moment = now if now.tzinfo is not None else now.astimezone()
    return moment.strftime("%Y-%m-%d %H:%M %Z")


def attestation(
    a: Analysis, result: FilterResult | None, *, now: datetime, version: str
) -> list[str]:
    """The footer / attestation lines (SPEC §5.6 item 4), identical in every export."""
    restricted_on = a.restricted
    if result is not None and result.active and not restricted_on:
        filters = "; ".join(describe(r) for r in result.rules)
    else:
        filters = "none"
    out = [
        f"Project: {a.title}",
        f"Industry: {a.policy.vertical or 'not given'}",
        f"Restricted-use question: {RESTRICTED_QUESTION}",
        f"Answer: {a.policy.answer or 'not given'}",
        f"Restricted mode: {'on' if restricted_on else 'off'}",
        f"Benchmark: {_benchmark_label(a)}",
        "Estimate mode: "
        + ("In-radius estimate (Zipcator overlap)" if a.weighted else "Full ZIPs"),
        f"Filters applied: {filters}",
    ]
    if filters != "none" and result is not None:
        out.append(f"ZIPs matching: {len(result.qualifying)} of {len(result.matches)}")
    out += [
        f"Data: {a.vintage_label}",
        NOTE_ZIP,
        NOTE_MOE,
        f"Generated: {_stamp(now)} by Zipographics {version}",
        NOTE_CENSUS,
        NOTE_GEONAMES,
    ]
    if restricted_on:
        out.append(NOT_LEGAL_ADVICE)
    return out


# ------------------------------------------------------------------------- CSV
def defuse(text: str) -> str:
    """Neutralize spreadsheet formula injection: a leading ``= + - @`` (or tab/CR) gets a quote."""
    return "'" + text if text.startswith(_FORMULA_LEAD) else text


def _num(value: float | None, digits: int = 2) -> float | int | str:
    if value is None or not math.isfinite(value):
        return ""
    rounded = round(value, digits)
    return int(rounded) if rounded == int(rounded) else rounded


_SUFFIX = {"percent": " (%)", "dollars": " ($)", "years": " (years)", "year": " (year)"}


def _header(metric: metrics.Metric) -> str:
    return metric.name + _SUFFIX.get(metric.unit, "")


def _scaled(metric: metrics.Metric, v: float | None) -> float | int | str:
    if v is None:
        return ""
    if metric.unit == "percent":
        return _num(v * 100, 2)
    if metric.unit in ("count", "dollars", "year"):
        return _num(v, 0)
    return _num(v, 2)


def default_metrics(a: Analysis) -> tuple[str, ...]:
    return ("pop", "hh", *[m for m in a.lens.columns if m not in ("pop", "hh")])


def _cells(
    metric_id: str, value: MetricValue, index: IndexValue | None, with_index: bool
) -> list[object]:
    m = metrics.BY_ID[metric_id]
    if value.estimate is None:
        shown: object = ""
    elif value.code != "none":
        from zipographics.stats import coded_bound

        bound = coded_bound(value.estimate, value.code)
        shown = f"{_num(bound, 0)}{'+' if value.code == 'top' else '-'}"
    else:
        shown = _scaled(m, value.estimate)
    moe = "" if value.code != "none" else _scaled(m, value.moe)
    cells: list[object] = [shown, moe, TIER_LABELS[value.tier]]
    if with_index:
        cells.append("" if index is None or index.value is None else index.value)
    return cells


def csv_text(
    a: Analysis,
    result: FilterResult | None = None,
    *,
    excel: bool = False,
    metric_ids: Sequence[str] | None = None,
    order: Sequence[str] | None = None,
    now: datetime,
    version: str,
) -> str:
    """The profile as CSV text: one row per recognized ZIP, a Trade area row, a Benchmark row, a
    blank line, then the footer (one ``Note:`` cell per line).

    Restricted mode (the Analysis's own policy): input order always, no index columns, no
    Qualifies column;
    passing a filter result that has rules raises :class:`RestrictedUseError`.
    """
    locked = a.restricted
    if locked and result is not None and result.active:
        require_unrestricted(a.policy, "select")
    ids = list(metric_ids) if metric_ids is not None else list(default_metrics(a))
    zips = list(a.zips)
    if order is not None and not locked:
        if sorted(order) != sorted(zips):
            raise ValueError("The requested order must list every recognized ZIP exactly once.")
        zips = list(order)
    with_index = not locked
    qualifies = result is not None and result.active and not locked

    unknown = [m for m in ids if m not in metrics.BY_ID]
    if unknown:
        raise ValueError(f"Unknown metric: {unknown[0]!r}")
    if len(set(ids)) != len(ids):
        dup = next(m for m in ids if ids.count(m) > 1)
        raise ValueError(f"Metric {dup!r} is listed twice.")
    indexes = {m: a.zip_index(m) for m in ids if with_index and metrics.BY_ID[m].indexable}
    position = {z: i for i, z in enumerate(a.zips)}

    head: list[str] = ["Row type", "ZIP", "City", "County", "State"]
    if a.weighted:
        head += ["Overlap %", "In-radius households", "In-radius population"]
    for mid in ids:
        m = metrics.BY_ID[mid]
        moe = f"{m.name} MOE (pts)" if m.unit == "percent" else f"{m.name} MOE"
        head += [_header(m), moe, f"{m.name} reliability"]
        if with_index:
            head.append(f"{m.name} index")
    if qualifies:
        head.append("Qualifies")

    buffer = io.StringIO()
    writer = csv.writer(buffer, quoting=csv.QUOTE_NONNUMERIC, lineterminator="\r\n")
    writer.writerow(head)
    n_extra = 3 if a.weighted else 0
    for z in zips:
        facts = a.row_facts(z)
        row: list[object] = [
            "ZIP",
            f'="{z}"' if excel else z,
            *[defuse(facts[k] or "") for k in ("city", "county", "state")],
        ]
        if a.weighted:
            row += [
                _num(a.overlap_pct(z), 6),
                _num(a.in_radius(z, "hh"), 0),
                _num(a.in_radius(z, "pop"), 0),
            ]
        pos = position[z]
        for mid in ids:
            idx = indexes[mid][pos] if mid in indexes else None
            row += _cells(mid, a.value(z, mid), idx, with_index)
        if qualifies:
            assert result is not None
            match = result.matches[z]
            row.append(
                "No"
                if not match.qualifies
                else "Yes (unreliable estimate)"
                if match.on_unreliable
                else "Yes"
            )
        writer.writerow(row)

    def summary_row(
        kind: str,
        label: str,
        values: Mapping[str, MetricValue],
        indexes: Mapping[str, IndexValue] | None,
    ) -> None:
        row: list[object] = [kind, "", defuse(label), "", "", *([""] * n_extra)]
        for mid in ids:
            idx = indexes.get(mid) if indexes is not None else None
            row += _cells(mid, values[mid], idx, with_index)
        if qualifies:
            row.append("")
        writer.writerow(row)

    summary_row("Trade area", f"All {len(a.zips)} ZIPs (trade area)", a.trade.values, a.index)
    summary_row(
        "Benchmark",
        _benchmark_label(a),
        a.bench.values,
        None,
    )
    writer.writerow([])
    for line in [*attestation(a, result, now=now, version=version), NOTE_CODED]:
        writer.writerow([f"Note: {line}"])
    return buffer.getvalue()


def csv_bytes(
    a: Analysis,
    result: FilterResult | None = None,
    *,
    excel: bool = False,
    metric_ids: Sequence[str] | None = None,
    order: Sequence[str] | None = None,
    now: datetime,
    version: str,
) -> bytes:
    """UTF-8 bytes for download: with a BOM and ``="02108"`` ZIP cells when ``excel``."""
    text = csv_text(
        a, result, excel=excel, metric_ids=metric_ids, order=order, now=now, version=version
    )
    return (BOM + text).encode("utf-8") if excel else text.encode("utf-8")
