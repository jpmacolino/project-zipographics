"""Display formatting shared by the app, the exports and the report (no Streamlit import).

Everything the user reads as a number goes through here so the table, the CSV, the report and the
CLI agree: shares as percentages, dollars with separators, top/bottom-coded medians from their
bound ("$250,000+", "1939 or earlier"), null as an em dash, "use with caution" and "unreliable"
marked with text and a dagger so the meaning never depends on color alone (SPEC §5.5).
"""

from __future__ import annotations

import math
import re

from zipographics.metrics import Metric
from zipographics.profile import IndexValue, MetricValue
from zipographics.stats import MedianCode, Tier, coded_bound

DASH = "\N{EM DASH}"
DAGGER = "\N{DAGGER}"
PLUS_MINUS = "\N{PLUS-MINUS SIGN}"
GEQ = "\N{GREATER-THAN OR EQUAL TO}"
LEQ = "\N{LESS-THAN OR EQUAL TO}"

# zero-width and bidirectional formatting characters: removed, never shown or written to files
_INVISIBLE = re.compile(
    "[" + "".join(chr(c) for c in (*range(0x200B, 0x2010), *range(0x202A, 0x202F),
                                   *range(0x2066, 0x206A), 0xFEFF)) + "]"
)  # fmt: skip
_CONTROL_OR_SPACE = re.compile(r"[\x00-\x20\x7f]+")


def clean_text(text: str | None, limit: int | None = None) -> str:
    """User text made safe for a title, a CSV footer cell and a file name: invisible and
    bidirectional-override characters removed, control characters and runs of whitespace become
    one space, trimmed, optionally cut to ``limit`` characters."""
    out = _CONTROL_OR_SPACE.sub(" ", _INVISIBLE.sub("", text or "")).strip()
    return out[:limit].rstrip() if limit else out


TIER_LABELS: dict[Tier, str] = {
    "good": "Reliable",
    "caution": "Use with caution",
    "unreliable": "Unreliable",
}
TILDE = "~"
#: Marker appended to a value in a table, tooltip or report: reliability is never conveyed by
#: colour alone (SPEC 7; DECISIONS P14). A dagger means unreliable, a tilde use with caution.
TIER_MARK: dict[Tier, str] = {"good": "", "caution": TILDE, "unreliable": DAGGER}


def marker_for(tier: Tier, *, known: bool = True, coded: bool = False) -> str:
    """The marker for a shown value. A coded median ("$250,000+") already says it is a bound, and
    an unknown value is a dash, so neither gets one."""
    return TIER_MARK[tier] if known and not coded else ""


#: How each unit is displayed: (scale, decimals). A share shows 100x with one decimal ("46.8 %").
_PRECISION: dict[str, tuple[int, int]] = {
    "percent": (100, 1),
    "dollars": (1, 0),
    "count": (1, 0),
    "year": (1, 0),
    "years": (1, 1),
    "ratio": (1, 2),
}


def scale_of(metric: Metric) -> int:
    """The factor a value is multiplied by before display (100 for a share)."""
    return _PRECISION[metric.unit][0]


def displayed_value(metric: Metric, value: float) -> float:
    """``value`` rounded to the precision :func:`fmt_number` shows, in the metric's own units.

    Filters compare this, so a value displayed as meeting a threshold always qualifies (DECISIONS
    P10): a share of 0.2496 is shown as "25.0 %" and counts as 0.25; $74,999.6 as $75,000.
    """
    scale, digits = _PRECISION[metric.unit]
    return float(f"{value * scale:.{digits}f}") / scale


def fmt_number(metric: Metric, value: float | None) -> str:
    """A plain value in the metric's unit; an em dash for unknown."""
    if value is None or not math.isfinite(value):
        return DASH
    scale, digits = _PRECISION[metric.unit]
    text = f"{value * scale:,.{digits}f}"
    if metric.unit == "percent":
        return f"{text} %"
    if metric.unit == "dollars":
        return f"${text}"
    if metric.unit in ("year", "years", "ratio"):
        return text.replace(",", "")
    return text


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


def fmt_overlap(pct: float) -> str:
    """An overlap percentage for display: one decimal at most, whole numbers without ".0"."""
    if 0 < pct < 0.05:  # a sliver of a ZIP (Zipcator writes values like 0.006514)
        return "<0.1"
    text = f"{pct:.1f}"
    return text[:-2] if text.endswith(".0") else text


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
