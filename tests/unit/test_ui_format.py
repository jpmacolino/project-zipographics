"""Display formatting shared by the table, exports and report (SPEC 5.5, 6.2)."""

from __future__ import annotations

import pytest

from zipographics import metrics, stats, ui
from zipographics.profile import IndexValue, MetricValue


def mv(metric: str, est: float | None, moe: float | None = None, code: str = "none") -> MetricValue:
    tier = stats.tier(est, moe, coded=code != "none")
    return MetricValue(metric, est, moe, tier, code)  # type: ignore[arg-type]


def test_plain_values_use_the_metric_unit() -> None:
    m = metrics.BY_ID
    assert ui.fmt_value(m["owner"], mv("owner", 0.4678)) == "46.8 %"
    assert ui.fmt_value(m["pop"], mv("pop", 12345.4)) == "12,345"
    assert ui.fmt_value(m["median_hh_income"], mv("median_hh_income", 75250)) == "$75,250"
    assert ui.fmt_value(m["median_age"], mv("median_age", 38.46)) == "38.5"
    assert ui.fmt_value(m["veh_per_hh"], mv("veh_per_hh", 1.8349)) == "1.83"


def test_unknown_is_an_em_dash() -> None:
    assert ui.fmt_value(metrics.BY_ID["owner"], mv("owner", None)) == ui.DASH == "\N{EM DASH}"
    assert ui.fmt_number(metrics.BY_ID["owner"], float("nan")) == ui.DASH


def test_coded_medians_show_their_published_bound() -> None:
    inc = metrics.BY_ID["median_hh_income"]
    assert ui.fmt_value(inc, mv("median_hh_income", 250_001, None, "top")) == "$250,000+"
    assert ui.fmt_value(inc, mv("median_hh_income", 2_499, None, "bottom")) == "$2,500 or less"
    val = metrics.BY_ID["median_value"]
    assert ui.fmt_value(val, mv("median_value", 2_000_001, None, "top")) == "$2,000,000+"
    year = metrics.BY_ID["median_year_built"]
    assert ui.fmt_value(year, mv("median_year_built", 1938, None, "bottom")) == "1939 or earlier"
    assert ui.fmt_value(year, mv("median_year_built", 2021, None, "top")) == "2020 or later"


def test_margins_of_error() -> None:
    assert (
        ui.fmt_moe(metrics.BY_ID["owner"], mv("owner", 0.5, 0.0312))
        == "\N{PLUS-MINUS SIGN} 3.1 pts"
    )
    assert ui.fmt_moe(metrics.BY_ID["pop"], mv("pop", 1000, 120)) == "\N{PLUS-MINUS SIGN} 120"
    assert ui.fmt_moe(metrics.BY_ID["pop"], mv("pop", 1000, None)) == ""
    assert ui.fmt_moe(metrics.BY_ID["pop"], mv("pop", None, 5)) == ""


def test_index_and_thresholds() -> None:
    assert ui.fmt_index(IndexValue(128, "good")) == "128" and ui.fmt_index(None) == ui.DASH
    assert ui.fmt_index(IndexValue(None, "good")) == ui.DASH and ui.fmt_index(95) == "95"
    inc = metrics.BY_ID["median_hh_income"]
    assert ui.fmt_threshold(inc, 75_000, "value") == "$75,000"
    assert ui.fmt_threshold(metrics.BY_ID["owner"], 0.625, "value") == "62.5 %"
    assert ui.fmt_threshold(metrics.BY_ID["owner"], 115, "index") == "115"
    assert ui.fmt_threshold(metrics.BY_ID["pop"], 4000, "value") == "4,000"


@pytest.mark.parametrize(
    ("tier", "label", "mark"),
    [
        ("good", "Reliable", ""),
        ("caution", "Use with caution", ""),
        ("unreliable", "Unreliable", "\N{DAGGER}"),
    ],
)
def test_reliability_is_text_plus_a_marker_not_color(tier: str, label: str, mark: str) -> None:
    assert ui.reliability_text(tier) == label  # type: ignore[arg-type]
    assert ui.TIER_MARK[tier] == mark  # type: ignore[index]


def test_coded_bound_convention() -> None:
    assert stats.coded_bound(250_001, "top") == 250_000
    assert stats.coded_bound(2_499, "bottom") == 2_500
    assert stats.coded_bound(42.0, "none") == 42.0


def test_overlap_percentages_show_one_decimal_at_most() -> None:
    # Visual QA: the table showed 96.0737; an overlap is shown as 96.1 (and 100, not 100.0)
    assert [ui.fmt_overlap(x) for x in (100.0, 96.0737, 76.1523, 50.0, 0.0065, 99.96)] == [
        "100", "96.1", "76.2", "50", "<0.1", "100",
    ]  # fmt: skip
