"""Regression tests from the Phase 2 independent QA review (see docs/QA_REPORT.md, Phase 2)."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest
from synth_facts import make_facts
from synth_frame import make_frame

from zipographics import profile, stats, vstats
from zipographics.sentinels import clean_frame

HH = {"A": {"B11001_001": (1000, 100)}, "B": {"B11001_001": (2000, 200)}}


def val(frame, zips, metric_id, weights=None):  # type: ignore[no-untyped-def]
    return profile.build_profile(frame, zips, weights=weights, metric_ids=[metric_id]).values[
        metric_id
    ]


def income_rows(counts: dict[int, float], published: float, code: str = "none"):  # type: ignore[no-untyped-def]
    cells: dict[str, tuple[float, float]] = {
        f"B19001_{n:03d}": (counts.get(n, 0.0), 10.0) for n in range(2, 18)
    }
    cells["B19013_001"] = (published, 1000.0)
    return cells, {"B19013_001": code}


# ------------------------------------------------------------------ M1: median codes fail closed
def test_a_published_median_without_its_code_column_is_rejected() -> None:
    a, ca = income_rows({17: 300}, 250_001, "top")
    frame = make_frame({"A": a}, {"A": ca}).drop(columns=["B19013_001_code"])
    with pytest.raises(ValueError, match="B19013_001_code"):
        profile.build_profile(frame, ["A"], metric_ids=["median_hh_income"])


def test_an_unknown_median_code_is_rejected() -> None:
    a, ca = income_rows({17: 300}, 250_001, "median+")
    frame = make_frame({"A": a}, {"A": ca})
    with pytest.raises(ValueError, match="median code"):
        profile.build_profile(frame, ["A"], metric_ids=["median_hh_income"])


def test_a_coded_published_median_has_no_index_in_the_per_zip_column() -> None:
    top, c1 = income_rows({17: 300}, 250_001, "top")
    ok, c2 = income_rows({12: 300}, 70_000)
    frame = make_frame({"A": top, "B": ok}, {"A": c1, "B": c2})
    table = profile.zip_table(frame, ["A", "B"], metric_ids=["median_hh_income"])
    assert table.index_column("median_hh_income", 60_000) == [None, 117]


def test_a_median_variable_without_its_annotation_column_is_an_error() -> None:
    raw = pd.DataFrame(
        {"zcta": ["02108"], "B19013_001E": ["250001"], "B19013_001M": ["-333333333"]}
    )
    with pytest.raises(ValueError, match="B19013_001EA"):
        clean_frame(raw, key="zcta", variables={"B19013_001": True})


# ------------------------------------------------------------------ M2: profile refuses sentinels
@pytest.mark.parametrize("bad", [-666666666, -999999999, -555555555, -222222222, -123456789])
def test_a_sentinel_that_reaches_the_frame_is_rejected(bad: int) -> None:
    for cell in ((bad, 5), (5, bad)):
        frame = make_frame({"A": {"B11001_001": cell}})
        with pytest.raises(ValueError, match="sentinel"):
            profile.build_profile(frame, ["A"], metric_ids=["hh"])


def test_a_negative_numerator_is_clamped_to_a_zero_share_and_flagged() -> None:
    rows = {"A": {"B25003_002": (-5, 1), "B25003_001": (100, 5)}}
    v = val(make_frame(rows), ["A"], "owner")
    assert v.estimate == 0.0 and v.incomplete


def test_a_share_above_one_is_clamped_and_flagged() -> None:
    rows = {"A": {"B25003_002": (150, 10), "B25003_001": (100, 10)}}
    v = val(make_frame(rows), ["A"], "owner")
    assert v.estimate == 1.0 and v.incomplete


def test_share_of_a_zero_denominator_is_unknown_even_with_a_positive_numerator() -> None:
    rows = {"A": {"B25003_002": (5, 1), "B25003_001": (0, 0)}}
    assert val(make_frame(rows), ["A"], "owner").estimate is None


# ------------------------------------------------------------------ M4: untested branches
def test_vectorized_proportion_plus_form_fallback() -> None:
    # X = 90 ±1 of Y = 100 ±50: the minus radicand is negative, so sqrt(1 + 0.81 * 2500) / 100
    arr = lambda v: np.array([float(v)])  # noqa: E731
    got = vstats.moe_proportion(arr(90), arr(1), arr(100), arr(50))
    assert float(got[0]) == pytest.approx(math.sqrt(2026) / 100)


def test_share_moe_uses_the_plus_form_when_the_numerator_moe_is_small() -> None:
    # X = 10 ±1 of Y = 100 ±50: P = 0.1, 1 - 0.01 * 2500 < 0 -> plus form: sqrt(1 + 25) / 100
    rows = {"A": {"B25003_002": (10, 1), "B25003_001": (100, 50)}}
    v = val(make_frame(rows), ["A"], "owner")
    assert v.moe == pytest.approx(math.sqrt(26) / 100)


def test_a_bracket_null_in_every_zip_is_flagged_but_the_median_still_computes() -> None:
    a, ca = income_rows({12: 300}, 70_000)
    b, cb = income_rows({13: 100, 14: 100}, 90_000)
    a["B19001_005"] = (None, None)  # type: ignore[assignment]
    b["B19001_005"] = (None, None)  # type: ignore[assignment]
    v = val(make_frame({"A": a, "B": b}, {"A": ca, "B": cb}), ["A", "B"], "median_hh_income")
    assert v.incomplete and v.estimate == pytest.approx(72_500)


def test_median_moe_with_leading_and_trailing_empty_brackets() -> None:
    bounds = [(0, 10), (10, 20), (20, 30), (30, 40)]
    moe = stats.median_moe([0, 50, 50, 0], [5, 300, 300, 5], bounds)
    assert moe is not None and math.isfinite(moe) and moe > 0


# ------------------------------------------------------------------ M5: geography keys stay strings
def test_numeric_geography_keys_are_rejected_not_stringified() -> None:
    raw = pd.DataFrame({"zcta": [2108, 601], "B01003_001E": [1, 2], "B01003_001M": [1, 1]})
    with pytest.raises(ValueError, match="string"):
        clean_frame(raw, key="zcta", variables={"B01003_001": False})


# ------------------------------------------------------------------ LOW 2: index rounding
@pytest.mark.parametrize(
    ("value", "expected"), [(0.145, 15), (0.285, 29), (0.125, 13), (1.005, 101), (0.144, 14)]
)
def test_index_rounds_exact_halves_up_despite_float_noise(value: float, expected: int) -> None:
    # 100 * 0.145 / 1 + 0.5 is 14.999999999999998 in floats; the index must still be 15
    assert stats.index_value(value, 1.0) == expected
    got = vstats.index_values(np.array([value]), 1.0)
    assert int(got[0]) == expected


# ------------------------------------------------------------------ LOW 4, 5: inputs
def test_a_scaled_single_count_is_not_labeled_published() -> None:
    frame = make_frame(HH)
    assert val(frame, ["A"], "hh").source == "published"
    assert val(frame, ["A"], "hh", weights={"A": 1.0}).source == "published"
    assert val(frame, ["A"], "hh", weights={"A": 0.25}).source == "derived"


def test_duplicate_zips_are_rejected_instead_of_double_counted() -> None:
    with pytest.raises(ValueError, match="duplicate"):
        profile.build_profile(make_frame(HH), ["A", "A"], metric_ids=["hh"])
    with pytest.raises(ValueError, match="duplicate"):
        profile.zip_table(make_frame(HH), ["A", "A"], metric_ids=["hh"])


@pytest.mark.parametrize("bad", [0.0, -0.5, 1.5, float("inf"), float("nan")])
def test_weights_must_be_in_zero_one(bad: float) -> None:
    with pytest.raises(ValueError, match="weight"):
        profile.build_profile(make_frame(HH), ["A", "B"], weights={"A": bad}, metric_ids=["hh"])


# ------------------------------------------------------------------ LOW 6: benchmark robustness
def test_states_outside_the_acs_geography_are_ignored() -> None:
    facts = make_facts({"33602": ("FL", 100, 1), "96910": ("GU", 500, 1)})
    opts = profile.benchmark_options(["33602", "96910"], facts)
    assert opts.default.name == "Florida"
    assert [r.name for r in opts.states] == ["Florida"]
    with pytest.raises(ValueError, match="no recognized"):
        profile.benchmark_options(["96910"], facts)


def test_county_ids_must_be_five_digits_and_missing_names_fall_back() -> None:
    facts = make_facts(
        {"33602": ("FL", 100, 1), "33603": ("FL", 90, 1), "33604": ("FL", 80, 1)},
        {
            "33602": ("12057", "Hillsborough County"),
            "33603": ("057", "Short"),
            "33604": ("12103", ""),
        },
    )
    opts = profile.benchmark_options(["33602", "33603", "33604"], facts)
    assert [r.geo_id for r in opts.counties] == ["12057", "12103"]  # "057" is ignored
    assert opts.counties[1].name == "12103"  # a blank name falls back to the id, never "nan"


def test_a_zero_radicand_is_zero_on_both_sides_of_float_noise() -> None:
    # Hypothesis found x=41199 ±41199 of y=53289 ±53289 (equal relative MOEs): the true radicand is
    # 0, floats give ±1e-16, so the result was 9e-9 under one scaling and exactly 0 under another.
    arr = lambda v: np.array([float(v)])  # noqa: E731
    for w in (1.0, 0.01, 3.0, 0.37):
        scalar = stats.moe_proportion(41199 * w, 41199 * w, 53289 * w, 53289 * w)
        vector = vstats.moe_proportion(
            arr(41199 * w), arr(41199 * w), arr(53289 * w), arr(53289 * w)
        )
        assert scalar == 0.0
        assert float(vector[0]) == 0.0


def test_overflow_in_the_proportion_formula_is_unknown_in_both_implementations() -> None:
    # Hypothesis: x=1, y=6e-163 makes p^2 overflow; the scalar said None, the vector said 0.0
    arr = lambda v: np.array([float(v)])  # noqa: E731
    assert stats.moe_proportion(1.0, 0.0, 6.379018478957434e-163, 1.0) is None
    got = vstats.moe_proportion(arr(1.0), arr(0.0), arr(6.379018478957434e-163), arr(1.0))
    assert np.isnan(got[0])


def test_an_absurd_index_is_unknown_in_both_implementations() -> None:
    # est=2e-16 against a denormal benchmark gave ~1e301 with different float rounding in each
    assert stats.index_value(2.220446049250313e-16, 2.2250738585e-313) is None
    got = vstats.index_values(np.array([2.220446049250313e-16]), 2.2250738585e-313)
    assert np.isnan(got[0])
    assert stats.index_value(5.0, 1.0) == 500  # ordinary values are unaffected


@pytest.mark.parametrize("y", [5e-324, 2.225073858507e-311, 1.1125369292536007e-308, 6e-163])
def test_a_tiny_denominator_is_unknown_in_both_implementations(y: float) -> None:
    # p = x / y overflows to inf; the scalar's noise clamp used to turn -inf into 0.0
    arr = lambda v: np.array([float(v)])  # noqa: E731
    for x in (1.0, 2.0, 4.0):
        assert stats.moe_proportion(x, 0.0, y, 1.0) is None
        assert np.isnan(vstats.moe_proportion(arr(x), arr(0.0), arr(y), arr(1.0))[0])
