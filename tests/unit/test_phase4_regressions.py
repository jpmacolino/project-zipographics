"""Regression tests from the Phase 4 independent QA review (see docs/QA_REPORT.md, Phase 4)."""

from __future__ import annotations

import pytest
from synth_frame import make_frame

from zipographics import profile


def val(frame, zips, metric_id, weights=None):  # type: ignore[no-untyped-def]
    return profile.build_profile(frame, zips, weights=weights, metric_ids=[metric_id]).values[
        metric_id
    ]


OWN_A = {"B25003_002": (600, 60), "B25003_001": (1000, 50)}


# ----------------------------------------------------- ratios stay consistent across ZIPs
def test_a_zip_without_a_numerator_is_left_out_of_the_denominator_too() -> None:
    # Real data: 14 % of ZCTAs had no value for one variable while its denominator was present.
    # Adding such a ZIP's denominator but not its numerator biased trade-area shares low
    # (600 / 2,000 = 0.30 instead of 600 / 1,000 = 0.60). The ZIP must drop out of both.
    rows = {"A": OWN_A, "B": {"B25003_001": (1000, 50)}}
    v = val(make_frame(rows), ["A", "B"], "owner")
    assert v.estimate == pytest.approx(0.60)
    assert v.incomplete  # and the user is told a ZIP was left out


def test_a_zip_without_a_denominator_is_left_out_of_the_numerator_too() -> None:
    rows = {"A": OWN_A, "B": {"B25003_002": (500, 50)}}
    v = val(make_frame(rows), ["A", "B"], "owner")
    assert v.estimate == pytest.approx(0.60) and v.incomplete


def test_the_moe_of_a_share_uses_only_the_zips_that_count() -> None:
    rows = {"A": OWN_A, "B": {"B25003_001": (1000, 50)}}
    both = val(make_frame(rows), ["A", "B"], "owner")
    alone = val(make_frame({"A": OWN_A}), ["A"], "owner")
    assert both.moe == pytest.approx(alone.moe)


def test_overlap_weights_of_a_left_out_zip_do_not_matter() -> None:
    rows = {"A": OWN_A, "B": {"B25003_001": (1000, 50)}}
    a = val(make_frame(rows), ["A", "B"], "owner", weights={"A": 0.5, "B": 0.1})
    b = val(make_frame(rows), ["A", "B"], "owner", weights={"A": 0.5, "B": 1.0})
    assert a.estimate == pytest.approx(b.estimate) == pytest.approx(0.60)


def test_a_zip_with_only_some_numerator_cells_still_counts_and_is_flagged() -> None:
    # single_family = B25024_002 + B25024_003 over B25024_001; ZIP B lacks the attached cell
    rows = {
        "A": {"B25024_002": (60, 5), "B25024_003": (20, 4), "B25024_001": (100, 6)},
        "B": {"B25024_002": (30, 5), "B25024_001": (100, 6)},
    }
    v = val(make_frame(rows), ["A", "B"], "single_family")
    assert v.estimate == pytest.approx((60 + 20 + 30) / 200)
    assert v.incomplete


def test_a_ratio_leaves_out_a_zip_missing_its_numerator_too() -> None:
    rows = {
        "A": {"B19025_001": (100e6, 5e6), "B11001_001": (1000, 100)},
        "B": {"B11001_001": (2000, 150)},  # no aggregate income
    }
    v = val(make_frame(rows), ["A", "B"], "mean_hh_income")
    assert v.estimate == pytest.approx(100_000)  # 100M / 1,000, not 100M / 3,000
    assert v.incomplete


def test_per_zip_values_are_unchanged() -> None:
    rows = {"A": OWN_A, "B": {"B25003_001": (1000, 50)}}
    table = profile.zip_table(make_frame(rows), ["A", "B"], metric_ids=["owner"])
    assert table.value("A", "owner").estimate == pytest.approx(0.6)
    assert table.value("B", "owner").estimate is None


def test_complete_data_is_unaffected() -> None:
    rows = {"A": OWN_A, "B": {"B25003_002": (500, 50), "B25003_001": (1000, 50)}}
    v = val(make_frame(rows), ["A", "B"], "owner")
    assert v.estimate == pytest.approx(1100 / 2000) and not v.incomplete
