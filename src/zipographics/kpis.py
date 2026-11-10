"""KPI card data for the dashboard, the report and the CLI (SPEC §5.5).

One function builds every card, so the three places show the same numbers and wording. Counts show
their share of the benchmark's total instead of an index; shares, medians, means and ratios show
``Index N vs <benchmark>``; a top- or bottom-coded median shows its bound and says it has no index.
The reliability marker uses the worse of the value's and the index's tier.
"""

from __future__ import annotations

from dataclasses import dataclass

from zipographics import metrics, stats
from zipographics.analysis import Analysis
from zipographics.stats import Tier
from zipographics.ui import DAGGER, DASH, TIER_LABELS, fmt_moe, fmt_value

_NOUNS = {"hh": "households", "pop": "population"}

_EXPLANATION: dict[Tier, str] = {
    "good": "",
    "caution": (
        "Use with caution: the margin of error is between 15 % and 30 % of the estimate, so the "
        "true value could be noticeably different."
    ),
    "unreliable": (
        "Unreliable: the margin of error is more than 30 % of the estimate (or unknown). Treat "
        "it as a rough guide, not a precise figure."
    ),
}
_CODED = (
    "This median is top- or bottom-coded: the Census Bureau publishes only a bound, so it has "
    "no margin of error or index."
)


@dataclass(frozen=True, slots=True)
class KpiCard:
    metric_id: str
    label: str
    estimate: float | None
    value: str  # as displayed; coded medians from their bound ("$250,000+")
    moe: str  # "± 1.6 pts"; empty when none
    index: int | None
    index_text: str | None  # "Index 128 vs Florida", or why there is none
    share_text: str | None  # counts: "1.4 % of Florida's households"
    tier: Tier  # the worse of the value's and the index's
    tier_label: str
    marker: str  # a dagger when unreliable, so the meaning never rests on color alone
    tooltip: str  # why the card is marked; empty when it is not


def cards(a: Analysis) -> list[KpiCard]:
    """The cards for ``a``'s lens: the five core ones, then the lens's own."""
    out: list[KpiCard] = []
    bench = a.benchmark.name
    for mid in a.lens.all_kpis:
        m = metrics.BY_ID[mid]
        v = a.trade.values[mid]
        idx = a.index.get(mid) if m.indexable else None
        index = idx.value if idx is not None else None
        index_text: str | None = None
        share_text: str | None = None
        tier: Tier = v.tier
        if m.indexable:
            if index is not None:
                index_text = f"Index {index} vs {bench}"
            elif v.code != "none":
                index_text = "No index (above the published range)"
            else:
                index_text = "No index"
            if idx is not None:
                tier = stats.worse_tier(tier, idx.tier)
        else:
            share = a.share_of_benchmark(mid)
            if share is not None:
                noun = _NOUNS.get(mid, m.name.lower())
                share_text = f"{share * 100:.1f} % of {bench}'s {noun}"
        tooltip = _EXPLANATION[tier]
        if v.code != "none":
            tooltip = (tooltip + " " + _CODED).strip()
        out.append(
            KpiCard(
                mid,
                m.name,
                v.estimate,
                fmt_value(m, v),
                fmt_moe(m, v),
                index,
                index_text,
                share_text,
                tier,
                TIER_LABELS[tier],
                DAGGER if tier == "unreliable" else "",
                tooltip,
            )
        )
    return out


def text_lines(a: Analysis) -> list[str]:
    """The cards as aligned plain-text lines (the CLI)."""
    lines = []
    for c in cards(a):
        extra = c.index_text or c.share_text or ""
        parts = [f"{c.label:<28}", c.value.rjust(12), c.moe.ljust(14), extra]
        lines.append("  " + " ".join(parts).rstrip())
    return lines


__all__ = ["DASH", "KpiCard", "cards", "text_lines"]
