"""Display formatting shared by the app, the exports and the report (no Streamlit import).

Everything the user reads as a number goes through here so the table, the CSV, the report and the
CLI agree: shares as percentages, dollars with separators, top/bottom-coded medians from their
bound ("$250,000+", "1939 or earlier"), null as an em dash, "use with caution" and "unreliable"
marked with text and a dagger so the meaning never depends on color alone (SPEC §5.5).
"""

from __future__ import annotations

import math

from zipographics.metrics import Metric
from zipographics.profile import IndexValue, MetricValue
from zipographics.stats import MedianCode, Tier, coded_bound

DASH = "\N{EM DASH}"
DAGGER = "\N{DAGGER}"
PLUS_MINUS = "\N{PLUS-MINUS SIGN}"
GEQ = "\N{GREATER-THAN OR EQUAL TO}"
LEQ = "\N{LESS-THAN OR EQUAL TO}"

TIER_LABELS: dict[Tier, str] = {
    "good": "Reliable",
    "caution": "Use with caution",
    "unreliable": "Unreliable",
}
#: Marker appended to an unreliable value (caution is shown in muted text instead).
TIER_MARK: dict[Tier, str] = {"good": "", "caution": "", "unreliable": DAGGER}


def fmt_number(metric: Metric, value: float | None) -> str:
    """A plain value in the metric's unit; an em dash for unknown."""
    if value is None or not math.isfinite(value):
        return DASH
    unit = metric.unit
    if unit == "percent":
        return f"{value * 100:.1f} %"
    if unit == "dollars":
        return f"${value:,.0f}"
    if unit == "count":
        return f"{value:,.0f}"
    if unit == "year":
        return f"{value:.0f}"
    if unit == "years":
        return f"{value:.1f}"
    return f"{value:.2f}"


def fmt_value(metric: Metric, value: MetricValue) -> str:
    """The value as shown to a user, including coded medians from their published bound."""
    if value.estimate is None:
        return DASH
    code: MedianCode = value.code
    if code == "none":
        return fmt_number(metric, value.estimate)
    bound = coded_bound(value.estimate, code)
    if metric.unit == "year":
        return f"{bound:.0f} or later" if code == "top" else f"{bound:.0f} or earlier"
    text = fmt_number(metric, bound)
    return f"{text}+" if code == "top" else f"{text} or less"


def fmt_moe(metric: Metric, value: MetricValue) -> str:
    """``± MOE`` in the metric's unit; empty when there is none (null or coded)."""
    if value.moe is None or value.estimate is None:
        return ""
    if metric.unit == "percent":
        return f"{PLUS_MINUS} {value.moe * 100:.1f} pts"
    return f"{PLUS_MINUS} {fmt_number(metric, value.moe)}"


def fmt_index(index: IndexValue | int | None) -> str:
    n = index.value if isinstance(index, IndexValue) else index
    return DASH if n is None else str(n)


def fmt_threshold(metric: Metric, value: float, basis: str) -> str:
    """A filter threshold: "60 %", "$75,000", "120" (index)."""
    if basis == "index":
        return f"{value:g}"
    if metric.unit == "percent":
        return f"{value * 100:g} %"
    if metric.unit == "dollars":
        return f"${value:,.0f}"
    return f"{value:,g}"


def reliability_text(tier: Tier) -> str:
    return TIER_LABELS[tier]
