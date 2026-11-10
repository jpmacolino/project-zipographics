"""Chart data: trade area vs benchmark, as shares (SPEC §5.5, Appendix D).

This module holds the tested data; rendering (Altair in the app, matplotlib SVG in the report) is
thin and lives elsewhere. Every category is a registry share metric, so the numbers, margins of
error and reliability tiers are the engine's own.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass

import altair as alt
import pandas as pd

from zipographics import metrics
from zipographics.analysis import Analysis
from zipographics.lenses import CORE_CHARTS, MORE_DEMOGRAPHICS_CHARTS
from zipographics.stats import Tier
from zipographics.ui import fmt_number


@dataclass(frozen=True, slots=True)
class ChartSpec:
    id: str
    title: str
    metric_ids: tuple[str, ...]
    labels: tuple[str, ...]
    note: str = ""


@dataclass(frozen=True, slots=True)
class ChartRow:
    label: str
    metric_id: str
    trade: float | None
    trade_moe: float | None
    bench: float | None
    tier: Tier


@dataclass(frozen=True)
class ChartData:
    id: str
    title: str
    note: str
    rows: tuple[ChartRow, ...]
    benchmark_name: str


_RACE_NOTE = (
    "Race and Hispanic origin are separate Census questions: Hispanic people can be of any race, "
    "so the Hispanic share is shown separately and these shares sum to 100 % on their own."
)

_SPECS = (
    ChartSpec(
        "income",
        "Household income",
        (
            "inc_lt25",
            "inc_25_50",
            "inc_50_75",
            "inc_75_100",
            "inc_100_150",
            "inc_150_200",
            "inc_200p",
        ),
        ("Under $25k", "$25-50k", "$50-75k", "$75-100k", "$100-150k", "$150-200k", "$200k+"),
    ),
    ChartSpec(
        "age",
        "Age",
        (
            "age_0_17",
            "age_18_24",
            "age_25_34",
            "age_35_44",
            "age_45_54",
            "age_55_64",
            "age_65_74",
            "age_75p",
        ),
        ("Under 18", "18-24", "25-34", "35-44", "45-54", "55-64", "65-74", "75+"),
    ),
    ChartSpec(
        "tenure", "Owner vs renter", ("owner", "renter"), ("Owner-occupied", "Renter-occupied")
    ),
    ChartSpec(
        "housing_age",
        "Age of housing",
        ("built_2010p", "built_1980_2009", "built_1960_1979", "built_pre1960"),
        ("2010 or later", "1980-2009", "1960-1979", "Before 1960"),
    ),
    ChartSpec(
        "units_in_structure",
        "Units in structure",
        ("single_family", "units_2_4", "units_5_19", "units_20p", "mobile_home", "units_other"),
        ("Single-family", "2-4 units", "5-19 units", "20+ units", "Mobile home", "Boat, RV, van"),
    ),
    ChartSpec(
        "tenure_by_move_in",
        "When households moved in",
        ("new_movers", "movers_2", "movers_3", "movers_4", "movers_older"),
        ("Most recent period", "Second period", "Third period", "Fourth period", "Earlier periods"),
        "Periods are the Census Bureau's and shift with each ACS release.",
    ),
    ChartSpec(
        "commute_mode",
        "How workers get to work",
        ("commute_drive_alone", "commute_carpool", "commute_transit", "commute_walk_bike", "wfh"),
        ("Drive alone", "Carpool", "Public transit", "Walk or bike", "Work from home"),
    ),
    ChartSpec(
        "vehicles_available",
        "Vehicles available",
        ("veh_0", "veh_1", "veh_2", "veh_3p"),
        ("None", "1 vehicle", "2 vehicles", "3 or more"),
    ),
    ChartSpec(
        "education",
        "Education (adults 25+, cumulative)",
        ("hs_plus", "ba_plus", "grad"),
        ("High school or higher", "Bachelor's or higher", "Graduate degree"),
        "Cumulative: each group includes the ones after it.",
    ),
    ChartSpec(
        "race",
        "Race",
        (
            "race_white",
            "race_black",
            "race_aian",
            "race_asian",
            "race_nhpi",
            "race_other",
            "race_two_plus",
        ),
        (
            "White",
            "Black or African American",
            "American Indian and Alaska Native",
            "Asian",
            "Native Hawaiian and Other Pacific Islander",
            "Some other race",
            "Two or more races",
        ),
        _RACE_NOTE,
    ),
    ChartSpec(
        "hispanic",
        "Hispanic or Latino origin",
        ("hispanic",),
        ("Hispanic or Latino",),
        "Hispanic origin is a separate Census question; Hispanic or Latino people can be "
        "of any race.",
    ),
)
CHARTS: dict[str, ChartSpec] = {s.id: s for s in _SPECS}

_MOVE_CELLS = ("B25038_003", "B25038_004", "B25038_005", "B25038_006", "B25038_007")


def _last_segment(label: str) -> str:
    return label.split("!!")[-1].rstrip(":").strip()


def move_in_labels(metadata: Mapping[str, object]) -> list[str] | None:
    """The five period labels from the build metadata, or None when it does not carry them.

    The two oldest ACS periods are combined into one ("Moved in 1990 or earlier").
    """
    variables = metadata.get("variables")
    if not isinstance(variables, Mapping):
        return None
    out: list[str] = []
    for key in _MOVE_CELLS:
        info = variables.get(key)
        label = info.get("label") if isinstance(info, Mapping) else None
        if not isinstance(label, str):
            return None
        out.append(_last_segment(label))
    start = re.search(r"(\d{4})", out[4])
    out[4] = f"Moved in {start.group(1)} or earlier" if start else "Moved in an earlier period"
    return out


def chart_data(a: Analysis, chart_id: str) -> ChartData:
    """Trade-area and benchmark shares for each category of one chart."""
    if chart_id not in CHARTS:
        raise ValueError(f"Unknown chart: {chart_id!r}")
    spec = CHARTS[chart_id]
    labels = list(spec.labels)
    if chart_id == "tenure_by_move_in":
        labels = move_in_labels(a.metadata) or labels
    rows = []
    for mid, label in zip(spec.metric_ids, labels, strict=True):
        t, b = a.trade.values[mid], a.bench.values[mid]
        rows.append(ChartRow(label, mid, t.estimate, t.moe, b.estimate, t.tier))
    return ChartData(spec.id, spec.title, spec.note, tuple(rows), a.benchmark.name)


def charts_for(a: Analysis) -> list[ChartData]:
    """The core charts plus the lens's own (Context adds none)."""
    return [chart_data(a, cid) for cid in a.lens.all_charts]


def more_demographics(a: Analysis) -> list[ChartData]:
    """The "More demographics" expander: race and Hispanic origin, as context."""
    return [chart_data(a, cid) for cid in MORE_DEMOGRAPHICS_CHARTS]


__all__ = [
    "CHARTS",
    "CORE_CHARTS",
    "ChartData",
    "ChartRow",
    "ChartSpec",
    "altair_chart",
    "chart_data",
    "charts_for",
    "more_demographics",
    "move_in_labels",
    "table_frame",
    "to_frame",
]


# ----------------------------------------------------------------------------- rendering data
_TRADE_COLOR, _BENCH_COLOR = (
    "#1f4e79",
    "#a3acb8",
)  # dark blue vs light grey: also differ in lightness


#: Pixels per category band (two bars and a label); a Step height cannot collapse the plot.
ROW_STEP = 44


def to_frame(d: ChartData) -> pd.DataFrame:
    """Long frame (Category, Series, Share) for a grouped bar chart; unknown shares stay null."""
    rows = []
    for r in d.rows:
        rows.append({"Category": r.label, "Series": "Trade area", "Share": r.trade})
        rows.append({"Category": r.label, "Series": d.benchmark_name, "Share": r.bench})
    return pd.DataFrame(rows, columns=["Category", "Series", "Share"])


def altair_chart(d: ChartData) -> alt.Chart:
    """Trade area vs benchmark as grouped horizontal bars, shares in percent."""
    order = [r.label for r in d.rows]
    series = ["Trade area", d.benchmark_name]
    chart: alt.Chart = (
        alt.Chart(to_frame(d))
        .mark_bar()
        .encode(
            y=alt.Y("Category:N", sort=order, title=None),
            yOffset=alt.YOffset("Series:N", sort=series),
            x=alt.X("Share:Q", axis=alt.Axis(format="%"), title="Share"),
            color=alt.Color(
                "Series:N",
                scale=alt.Scale(domain=series, range=[_TRADE_COLOR, _BENCH_COLOR]),
                legend=alt.Legend(orient="bottom", title=None),
            ),
            tooltip=["Category:N", "Series:N", alt.Tooltip("Share:Q", format=".1%")],
        )
        .properties(title=d.title, height=alt.Step(ROW_STEP))
    )
    return chart


def table_frame(d: ChartData) -> pd.DataFrame:
    """The chart's numbers as text, for the expander under it (a text alternative)."""
    moe_metric = metrics.BY_ID
    rows = []
    for r in d.rows:
        m = moe_metric[r.metric_id]
        rows.append(
            {
                "Category": r.label,
                "Trade area": fmt_number(m, r.trade),
                d.benchmark_name: fmt_number(m, r.bench),
                "Margin of error": ""
                if r.trade_moe is None
                else f"\N{PLUS-MINUS SIGN} {r.trade_moe * 100:.1f} pts",
            }
        )
    return pd.DataFrame(
        rows, columns=["Category", "Trade area", d.benchmark_name, "Margin of error"]
    )
