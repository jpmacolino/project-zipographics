"""Tests for zipographics.profile: trade-area aggregation, per-ZIP table, index (SPEC §6, §9.2).

Hand-calculated expectations come from the handbook formulas (see test_stats.py); each test shows
its arithmetic. Frames are synthetic (tests/synth_frame.py).
"""

from __future__ import annotations

import math

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from synth_frame import make_frame, random_frame

from zipographics import metrics, profile, stats

INF = math.inf


def val(frame, zips, metric_id, weights=None):
    return profile.build_profile(frame, zips, weights=weights, metric_ids=[metric_id]).values[
        metric_id
    ]


# ------------------------------------------------------------------------------- counts
HH = {
    "A": {"B11001_001": (1000, 100)},
    "B": {"B11001_001": (2000, 200)},
}


def test_counts_add_and_their_moes_combine_as_a_sum() -> None:
    v = val(make_frame(HH), ["A", "B"], "hh")
    assert v.estimate == 3000
    assert v.moe == pytest.approx(math.sqrt(100**2 + 200**2))  # 223.607
    assert v.source == "derived"


def test_a_single_zip_shows_the_published_count_and_moe() -> None:
    v = val(make_frame(HH), ["A"], "hh")
    assert (v.estimate, v.moe) == (1000, 100)


def test_overlap_weights_scale_counts_and_moes() -> None:
    # A is half inside the radius: 1000 * 0.5 + 2000 = 2500; MOE sqrt(50^2 + 200^2) = 206.155
    v = val(make_frame(HH), ["A", "B"], "hh", weights={"A": 0.5})
    assert v.estimate == 2500
    assert v.moe == pytest.approx(206.155, abs=0.001)


def test_a_single_weighted_zip_is_scaled() -> None:
    v = val(make_frame(HH), ["A"], "hh", weights={"A": 0.25})
    assert (v.estimate, v.moe) == (250, 25)


def test_the_full_zip_toggle_is_weights_of_one() -> None:
    frame = make_frame(HH)
    full = val(frame, ["A", "B"], "hh", weights=None)
    ones = val(frame, ["A", "B"], "hh", weights={"A": 1.0, "B": 1.0})
    assert (full.estimate, full.moe) == (ones.estimate, ones.moe)


def test_a_null_count_is_excluded_and_flagged_incomplete() -> None:
    frame = make_frame({"A": {"B11001_001": (1000, 100)}, "B": {}})
    v = val(frame, ["A", "B"], "hh")
    assert v.estimate == 1000
    assert v.incomplete


def test_all_null_counts_give_an_unknown_value() -> None:
    v = val(make_frame({"A": {}, "B": {}}), ["A", "B"], "hh")
    assert v.estimate is None and v.moe is None
    assert v.tier == "unreliable"


def test_a_missing_moe_makes_the_sum_moe_unknown_but_keeps_the_estimate() -> None:
    frame = make_frame({"A": {"B11001_001": (1000, None)}, "B": {"B11001_001": (2000, 200)}})
    v = val(frame, ["A", "B"], "hh")
    assert v.estimate == 3000 and v.moe is None
    assert v.tier == "unreliable"


# ------------------------------------------------------------------------------- shares
OWN = {
    "A": {"B25003_002": (600, 60), "B25003_001": (1000, 50)},
    "B": {"B25003_002": (500, 50), "B25003_001": (1000, 50)},
}


def test_share_is_the_ratio_of_sums_never_the_mean_of_shares() -> None:
    frame = make_frame(
        {
            "A": {"B25003_002": (10, 1), "B25003_001": (10, 1)},  # 100 %
            "B": {"B25003_002": (0, 1), "B25003_001": (90, 5)},  # 0 %
        }
    )
    assert val(frame, ["A", "B"], "owner").estimate == pytest.approx(0.10)  # not 50 %


def test_share_moe_follows_the_proportion_formula() -> None:
    # numerator 1,100 ±sqrt(60^2+50^2) = 78.102; denominator 2,000 ±70.711; P = 0.55
    # MOE = sqrt(78.102^2 - 0.55^2 * 70.711^2) / 2000 = sqrt(4587.5) / 2000 = 0.033866
    v = val(make_frame(OWN), ["A", "B"], "owner")
    assert v.estimate == pytest.approx(0.55)
    assert v.moe == pytest.approx(0.033866, abs=1e-6)
    assert v.tier == "good"  # CV = 0.033866 / 1.645 / 0.55 = 3.7 %


def test_weighted_share() -> None:
    # A at 50 %: numerator 300 + 500 = 800 ±58.310; denominator 500 + 1000 = 1,500 ±55.902
    # P = 0.53333; MOE = sqrt(58.310^2 - 0.53333^2 * 55.902^2) / 1500 = sqrt(2511.1) / 1500
    v = val(make_frame(OWN), ["A", "B"], "owner", weights={"A": 0.5})
    assert v.estimate == pytest.approx(800 / 1500)
    assert v.moe == pytest.approx(0.033407, abs=1e-6)


def test_uniform_weights_leave_shares_and_their_moes_unchanged() -> None:
    frame = make_frame(OWN)
    a = val(frame, ["A", "B"], "owner")
    b = val(frame, ["A", "B"], "owner", weights={"A": 0.37, "B": 0.37})
    assert b.estimate == pytest.approx(a.estimate)
    assert b.moe == pytest.approx(a.moe)


def test_a_single_zip_share_uses_its_published_cells() -> None:
    # 600 ±60 of 1,000 ±50: P = 0.6; MOE = sqrt(60^2 - 0.36 * 50^2) / 1000 = sqrt(2700) / 1000
    v = val(make_frame(OWN), ["A"], "owner")
    assert v.estimate == pytest.approx(0.6)
    assert v.moe == pytest.approx(math.sqrt(2700) / 1000)


def test_share_with_a_missing_numerator_cell_is_incomplete() -> None:
    rows = {
        "A": {"B25003_002": (600, 60), "B25003_001": (1000, 50)},
        "B": {"B25003_001": (1000, 50)},  # numerator missing
    }
    v = val(make_frame(rows), ["A", "B"], "owner")
    assert v.incomplete
    assert v.estimate == pytest.approx(600 / 2000)


def test_share_with_an_all_null_numerator_is_unknown_not_zero() -> None:
    v = val(make_frame({"A": {"B25003_001": (1000, 50)}}), ["A"], "owner")
    assert v.estimate is None


def test_share_with_a_zero_denominator_is_unknown() -> None:
    rows = {"A": {"B25003_002": (0, 5), "B25003_001": (0, 5)}}
    assert val(make_frame(rows), ["A"], "owner").estimate is None


def test_a_zero_numerator_is_a_zero_share_with_caution() -> None:
    rows = {"A": {"B25003_002": (0, 10), "B25003_001": (1000, 50)}}
    v = val(make_frame(rows), ["A"], "owner")
    assert v.estimate == 0.0
    assert v.moe == pytest.approx(10 / 1000)
    assert v.tier == "caution"


def test_zero_population_zips_contribute_nothing() -> None:
    rows = {**OWN, "C": {"B25003_002": (0, 0), "B25003_001": (0, 0)}}
    a = val(make_frame(OWN), ["A", "B"], "owner")
    b = val(make_frame(rows), ["A", "B", "C"], "owner")
    assert b.estimate == a.estimate and b.moe == pytest.approx(a.moe)


# ------------------------------------------------------------------------------- medians
def income_rows(counts: dict[int, float], published: float, code: str = "none"):
    """A ZIP with B19001 bracket counts (MOE 10 on every bracket) and a published median."""
    cells: dict[str, tuple[float, float]] = {
        f"B19001_{n:03d}": (counts.get(n, 0.0), 10.0) for n in range(2, 18)
    }
    cells["B19013_001"] = (published, 1000.0)
    return cells, {"B19013_001": code}


def test_trade_area_median_is_interpolated_from_summed_brackets_not_averaged() -> None:
    # A: 300 households in $60-75k (published median 70,000); B: 100 in $75-100k and 100 in
    # $100-125k (published 90,000). Summed: N = 500, half = 250 -> in $60-75k:
    # 60,000 + (250 - 0) / 300 * 15,000 = 72,500. The average of the published medians is 80,000.
    a, ca = income_rows({12: 300}, 70_000)
    b, cb = income_rows({13: 100, 14: 100}, 90_000)
    frame = make_frame({"A": a, "B": b}, {"A": ca, "B": cb})
    v = val(frame, ["A", "B"], "median_hh_income")
    assert v.estimate == pytest.approx(72_500)
    assert v.estimate != 80_000
    assert v.source == "interpolated"
    assert v.code == "none"


def test_trade_area_median_moe_comes_from_the_bracket_moes() -> None:
    a, ca = income_rows({12: 300}, 70_000)
    b, cb = income_rows({13: 100, 14: 100}, 90_000)
    frame = make_frame({"A": a, "B": b}, {"A": ca, "B": cb})
    v = val(frame, ["A", "B"], "median_hh_income")
    spec = metrics.BY_ID["median_hh_income"].spec
    assert isinstance(spec, metrics.MedianSpec)
    counts = [0.0] * 16
    counts[10], counts[11], counts[12] = 300, 100, 100  # B19001 rows 12, 13, 14 -> indexes 10-12
    moes = [math.sqrt(10**2 + 10**2)] * 16  # every bracket has two ZIPs, each with MOE 10
    expected = stats.median_moe(counts, moes, [(b.lo, b.hi) for b in spec.brackets])
    assert expected is not None and v.moe == pytest.approx(expected)


def test_single_zip_median_is_the_published_value_with_its_published_moe() -> None:
    a, ca = income_rows({12: 300}, 70_000)
    v = val(make_frame({"A": a}, {"A": ca}), ["A"], "median_hh_income")
    assert (v.estimate, v.moe, v.code, v.source) == (70_000, 1000, "none", "published")


def test_single_zip_with_weights_is_still_the_published_median() -> None:
    a, ca = income_rows({12: 300}, 70_000)
    v = val(make_frame({"A": a}, {"A": ca}), ["A"], "median_hh_income", weights={"A": 0.3})
    assert v.estimate == 70_000 and v.moe == 1000


def test_published_top_coded_median_keeps_its_code_and_is_caution() -> None:
    a, ca = income_rows({17: 300}, 250_001, code="top")
    v = val(make_frame({"A": a}, {"A": ca}), ["A"], "median_hh_income")
    assert v.estimate == 250_001 and v.code == "top"
    assert v.tier == "caution"


def test_a_null_published_median_is_unknown() -> None:
    a, ca = income_rows({12: 300}, 70_000)
    a["B19013_001"] = (None, None)
    v = val(make_frame({"A": a}, {"A": ca}), ["A"], "median_hh_income")
    assert v.estimate is None and v.tier == "unreliable"


def test_trade_area_median_in_the_open_top_bracket_is_a_bound() -> None:
    a, ca = income_rows({17: 300}, 250_001, "top")
    b, cb = income_rows({17: 100, 16: 10}, 250_001, "top")
    v = val(make_frame({"A": a, "B": b}, {"A": ca, "B": cb}), ["A", "B"], "median_hh_income")
    assert v.estimate == 200_000
    assert v.code == "top" and v.moe is None
    assert v.tier == "caution"


def test_trade_area_median_with_no_households_is_unknown() -> None:
    a, ca = income_rows({}, 70_000)
    b, cb = income_rows({}, 90_000)
    v = val(make_frame({"A": a, "B": b}, {"A": ca, "B": cb}), ["A", "B"], "median_hh_income")
    assert v.estimate is None


def test_trade_area_median_with_a_missing_bracket_is_flagged() -> None:
    a, ca = income_rows({12: 300}, 70_000)
    b, cb = income_rows({13: 100}, 90_000)
    b["B19001_005"] = (None, None)
    v = val(make_frame({"A": a, "B": b}, {"A": ca, "B": cb}), ["A", "B"], "median_hh_income")
    assert v.incomplete and v.estimate is not None
    assert v.moe is not None  # the missing cell is excluded, not propagated


def test_weights_do_not_change_a_trade_area_median_when_uniform() -> None:
    a, ca = income_rows({12: 300}, 70_000)
    b, cb = income_rows({13: 100, 14: 100}, 90_000)
    frame = make_frame({"A": a, "B": b}, {"A": ca, "B": cb})
    base = val(frame, ["A", "B"], "median_hh_income")
    scaled = val(frame, ["A", "B"], "median_hh_income", weights={"A": 0.4, "B": 0.4})
    assert scaled.estimate == pytest.approx(base.estimate)


# ------------------------------------------------------------------------------- means
def test_mean_household_income_is_aggregate_over_households() -> None:
    # (100M + 200M) / (1,000 + 2,000) = 100,000 ; MOE by the ratio formula
    # sqrt(9.434e6^2 + 100000^2 * 180.278^2) / 3000 = 6,782.3
    rows = {
        "A": {"B19025_001": (100e6, 5e6), "B11001_001": (1000, 100)},
        "B": {"B19025_001": (200e6, 8e6), "B11001_001": (2000, 150)},
    }
    v = val(make_frame(rows), ["A", "B"], "mean_hh_income")
    assert v.estimate == pytest.approx(100_000)
    assert v.moe == pytest.approx(6782.33, abs=0.01)


def test_per_capita_income_is_weighted_by_population_not_averaged() -> None:
    # rates 30,000 (pop 1,000) and 50,000 (pop 3,000): (30M + 150M) / 4,000 = 45,000 (not 40,000)
    # N MOE = sqrt(3,162,278^2 + 16,155,494^2) = 16,462,078 (product formula per ZIP);
    # D = 4,000 ±316.228; MOE = sqrt(16,462,078^2 + 45,000^2 * 316.228^2) / 4,000 = 5,440.01
    rows = {
        "A": {"B19301_001": (30_000, 1000), "B01003_001": (1000, 100)},
        "B": {"B19301_001": (50_000, 2000), "B01003_001": (3000, 300)},
    }
    v = val(make_frame(rows), ["A", "B"], "per_capita_income")
    assert v.estimate == pytest.approx(45_000)
    assert v.moe == pytest.approx(5440.01, abs=0.01)


def test_per_capita_income_with_overlap_weights() -> None:
    # A at 50 %: (30,000 * 500 + 50,000 * 3,000) / 3,500 = 47,142.86 ; MOE 6,188.05
    rows = {
        "A": {"B19301_001": (30_000, 1000), "B01003_001": (1000, 100)},
        "B": {"B19301_001": (50_000, 2000), "B01003_001": (3000, 300)},
    }
    v = val(make_frame(rows), ["A", "B"], "per_capita_income", weights={"A": 0.5})
    assert v.estimate == pytest.approx(47_142.857, abs=0.001)
    assert v.moe == pytest.approx(6188.05, abs=0.01)


def test_single_zip_per_capita_income_is_published() -> None:
    rows = {"A": {"B19301_001": (30_000, 1000), "B01003_001": (1000, 100)}}
    v = val(make_frame(rows), ["A"], "per_capita_income", weights={"A": 0.5})
    assert (v.estimate, v.moe) == (30_000, 1000)


def test_per_capita_income_skips_a_zip_without_a_rate_in_both_numerator_and_base() -> None:
    rows = {
        "A": {"B19301_001": (30_000, 1000), "B01003_001": (1000, 100)},
        "B": {"B01003_001": (3000, 300)},  # no rate: must not dilute the mean
    }
    v = val(make_frame(rows), ["A", "B"], "per_capita_income")
    assert v.estimate == pytest.approx(30_000)
    assert v.incomplete


def test_vehicles_per_household_is_aggregate_vehicles_over_households() -> None:
    # 130 vehicles ±10 over 100 occupied units ±5: 1.30; MOE = sqrt(10^2 + 1.3^2 * 5^2) / 100
    #   = sqrt(100 + 42.25) / 100 = 0.11927
    cells = {"B25046_001": (130, 10), "B25044_001": (100, 5)}
    v = val(make_frame({"A": cells}), ["A"], "veh_per_hh")
    assert v.estimate == pytest.approx(1.3)
    assert v.moe == pytest.approx(0.119269, abs=1e-5)


def test_vehicles_per_household_combines_zips_by_summing_vehicles_and_units() -> None:
    rows = {
        "A": {"B25046_001": (130, 10), "B25044_001": (100, 5)},
        "B": {"B25046_001": (300, 20), "B25044_001": (200, 9)},
    }
    v = val(make_frame(rows), ["A", "B"], "veh_per_hh")
    assert v.estimate == pytest.approx(430 / 300)  # not the mean of 1.3 and 1.5


# ------------------------------------------------------------------------------- bad input
def test_unknown_zips_and_empty_lists_are_errors() -> None:
    frame = make_frame(HH)
    with pytest.raises(KeyError):
        profile.build_profile(frame, ["A", "Z"], metric_ids=["hh"])
    with pytest.raises(ValueError, match="no ZIPs"):
        profile.build_profile(frame, [], metric_ids=["hh"])


def test_a_frame_missing_a_registry_column_is_rejected() -> None:
    frame = make_frame(HH).drop(columns=["B11001_001_m"])
    with pytest.raises(ValueError, match="B11001_001_m"):
        profile.build_profile(frame, ["A"], metric_ids=["hh"])


def test_every_metric_computes_on_a_random_frame() -> None:
    frame = random_frame(30, seed=3)
    p = profile.build_profile(frame, list(frame.index)[:12])
    assert set(p.values) == {m.id for m in metrics.REGISTRY}
    assert p.zips == tuple(frame.index[:12])
    assert not p.weighted
    p2 = profile.build_profile(frame, list(frame.index)[:12], weights={frame.index[0]: 0.5})
    assert p2.weighted


# ------------------------------------------------------------------------------- per-ZIP table
def test_zip_table_matches_the_single_zip_profile_for_every_metric() -> None:
    # the vectorized per-ZIP path and the trade-area path must agree on single ZIPs
    frame = random_frame(40, seed=11)
    zips = list(frame.index)
    table = profile.zip_table(frame, zips)
    for z in zips[:15]:
        single = profile.build_profile(frame, [z]).values
        for metric_id, expected in single.items():
            got = table.value(z, metric_id)
            where = (z, metric_id)
            if expected.estimate is None:
                assert got.estimate is None, where
            else:
                assert got.estimate == pytest.approx(expected.estimate), where
            assert (got.moe is None) == (expected.moe is None), where
            if expected.moe is not None and got.moe is not None:
                assert got.moe == pytest.approx(expected.moe), where
            assert got.tier == expected.tier, where
            assert got.code == expected.code, where
            assert got.incomplete == expected.incomplete, where


def test_zip_table_order_and_lookup() -> None:
    frame = make_frame(HH)
    table = profile.zip_table(frame, ["B", "A"], metric_ids=["hh"])
    assert table.zips == ("B", "A")
    assert table.value("A", "hh").estimate == 1000
    assert table.value("B", "hh").estimate == 2000
    with pytest.raises(KeyError):
        table.value("Z", "hh")


def test_zip_table_index_column() -> None:
    frame = make_frame(OWN)
    table = profile.zip_table(frame, ["A", "B"], metric_ids=["owner"])
    # shares 0.6 and 0.5 against a benchmark of 0.5 -> 120 and 100
    idx = table.index_column("owner", 0.5)
    assert idx == [120, 100]


# ------------------------------------------------------------------------------- index
def mv(est, moe=None, tier=None, code="none"):
    return profile.MetricValue(
        metric_id="owner",
        estimate=est,
        moe=moe,
        tier=tier or stats.tier(est, moe, coded=code != "none"),
        code=code,
    )


def test_index_is_trade_area_over_benchmark_times_100() -> None:
    iv = profile.index_of(mv(0.55, 0.02), mv(0.50, 0.001))
    assert iv.value == 110
    assert iv.tier == "good"


def test_index_tier_is_the_worse_of_the_two_inputs() -> None:
    iv = profile.index_of(mv(0.55, 0.02), mv(0.50, 0.30))
    assert iv.tier == "unreliable"
    iv = profile.index_of(mv(0.55, 0.30), mv(0.50, 0.001))
    assert iv.tier == "unreliable"


@pytest.mark.parametrize(
    ("trade", "bench"),
    [
        (mv(None), mv(0.5, 0.01)),
        (mv(0.5, 0.01), mv(None)),
        (mv(0.5, 0.01), mv(0.0, 0.01)),  # zero benchmark
        (mv(250_001, None, code="top"), mv(60_000, 100)),  # top-coded trade area
        (mv(60_000, 100), mv(250_001, None, code="bottom")),  # coded benchmark
    ],
)
def test_index_is_null_when_either_side_is_unusable(trade, bench) -> None:
    assert profile.index_of(trade, bench).value is None


def test_index_profile_skips_counts() -> None:
    frame = make_frame({**OWN, "T": {"B25003_002": (50, 5), "B25003_001": (100, 5), **HH["A"]}})
    trade = profile.build_profile(frame, ["A", "B"], metric_ids=["owner", "hh"])
    bench = profile.build_profile(frame, ["T"], metric_ids=["owner", "hh"])
    idx = profile.index_profile(trade, bench)
    assert set(idx) == {"owner"}  # counts get share_of instead
    assert idx["owner"].value == 110  # 0.55 / 0.50


def test_a_count_shows_its_share_of_the_benchmark_total() -> None:
    # 3,000 households of 200,000 in the benchmark: 1.5 %
    got = profile.share_of(mv(3000, 223), mv(200_000, 1000))
    assert got == pytest.approx(0.015)
    assert profile.share_of(mv(None), mv(200_000, 1000)) is None
    assert profile.share_of(mv(3000, 223), mv(0, 1)) is None


# ------------------------------------------------------------------------------- benchmarks
def test_benchmark_profile_uses_published_values_for_one_geography() -> None:
    import pandas as pd

    bench = make_frame({"FL": {"B25003_002": (4_000_000, 9000), "B25003_001": (8_000_000, 9000)}})
    bench = bench.reset_index(drop=True)
    bench["geo_level"] = "state"
    bench["geo_id"] = "12"
    bench["name"] = "Florida"
    us = bench.copy()
    us["geo_level"], us["geo_id"], us["name"] = "us", "1", "United States"
    us["B25003_002_e"] = 1.0
    table = pd.concat([bench, us], ignore_index=True)
    p = profile.benchmark_profile(table, "state", "12", metric_ids=["owner"])
    assert p.values["owner"].estimate == pytest.approx(0.5)
    assert p.zips == ("12",)
    with pytest.raises(KeyError):
        profile.benchmark_profile(table, "state", "99", metric_ids=["owner"])


# ------------------------------------------------------------------------------- properties
@settings(max_examples=25, deadline=None)
@given(st.integers(0, 10_000), st.floats(0.01, 1.0))
def test_shares_stay_in_zero_one_and_scale_invariants_hold(seed: int, w: float) -> None:
    frame = random_frame(8, seed=seed)
    zips = list(frame.index)
    base = profile.build_profile(frame, zips)
    scaled = profile.build_profile(frame, zips, weights={z: w for z in zips})
    for metric in metrics.REGISTRY:
        a, b = base.values[metric.id], scaled.values[metric.id]
        if metric.kind == "share" and a.estimate is not None:
            assert 0.0 <= a.estimate <= 1.0, metric.id
        if metric.kind == "count":
            if a.estimate is not None and b.estimate is not None:
                assert b.estimate == pytest.approx(a.estimate * w, rel=1e-9, abs=1e-9)
            if a.moe is not None and b.moe is not None:
                assert b.moe == pytest.approx(a.moe * w, rel=1e-9, abs=1e-9)
        if metric.kind in ("share", "median", "mean", "ratio") and a.estimate is not None:
            assert b.estimate is not None, metric.id
            assert b.estimate == pytest.approx(a.estimate, rel=1e-6, abs=1e-9), metric.id


# ------------------------------------------------------------------------------- performance
@pytest.mark.slow
def test_profile_and_table_for_1000_zips_fit_the_one_second_budget() -> None:
    import time

    frame = random_frame(1000, seed=5)
    zips = list(frame.index)
    bench = profile.build_profile(frame, zips[:1])
    start = time.perf_counter()
    trade = profile.build_profile(frame, zips, weights={z: 0.8 for z in zips})
    table = profile.zip_table(frame, zips)
    idx = profile.index_profile(trade, bench)
    for metric in metrics.REGISTRY:
        table.index_column(metric.id, 0.5)
    elapsed = time.perf_counter() - start
    assert len(table.zips) == 1000 and idx
    assert np.isfinite(elapsed) and elapsed <= 1.0, f"took {elapsed:.2f}s (budget 1s)"


# ------------------------------------------------------------------------------- bracket_median
def test_bracket_median_interpolates_even_for_one_zip_and_ignores_the_published_value() -> None:
    # 300 households in $60-75k: 60,000 + (150 / 300) * 15,000 = 67,500, while the ZIP's
    # published median says 70,000 (the gap SPEC §6.4 asks us to measure on real data)
    a, ca = income_rows({12: 300}, 70_000)
    frame = make_frame({"A": a}, {"A": ca})
    got = profile.bracket_median(frame, ["A"], "median_hh_income")
    assert got.estimate == pytest.approx(67_500)
    assert got.source == "interpolated" and got.code == "none"
    assert val(frame, ["A"], "median_hh_income").estimate == 70_000  # build_profile is unchanged


def test_bracket_median_rejects_metrics_that_are_not_medians() -> None:
    frame = make_frame(HH)
    with pytest.raises(ValueError, match="not a median"):
        profile.bracket_median(frame, ["A"], "hh")
