"""Tests for zipographics.stats: MOE formulas, CV tiers, index, interpolated medians.

Expected values are the official worked examples (ACS General Handbook 2020 ch. 8; PUMS Accuracy
2020-2024, "Medians") or hand calculations with the arithmetic shown. See DECISIONS "Phase 2".
"""

from __future__ import annotations

import math

import pytest
from hypothesis import given
from hypothesis import strategies as st

from zipographics import stats

INF = math.inf


# ------------------------------------------------------------------------------ SE and sums
def test_se_is_moe_over_1_645() -> None:
    assert stats.se(3860) == pytest.approx(2346.5, abs=0.1)  # handbook: 2,347
    assert stats.se(2642) == pytest.approx(1606.1, abs=0.1)  # 1,606
    assert stats.se(1957) == pytest.approx(1189.7, abs=0.1)  # 1,190
    assert stats.se(None) is None


def test_sum_moe_handbook_example_1() -> None:
    # Fairfax ±3,860, Arlington ±2,642, Alexandria ±1,957 -> published ±5,070
    # sqrt(3860^2 + 2642^2 + 1957^2) = sqrt(14,899,600 + 6,980,164 + 3,829,849) = sqrt(25,709,613)
    assert stats.moe_sum([3860, 2642, 1957]) == pytest.approx(5070.46, abs=0.01)
    assert round(stats.moe_sum([3860, 2642, 1957])) == 5070


def test_sum_moe_handbook_table_8_2_subgroups() -> None:
    assert round(stats.moe_sum([743, 722])) == 1036
    assert round(stats.moe_sum([685, 631])) == 931
    assert round(stats.moe_sum([1007, 647, 996])) == 1557


def test_sum_moe_of_one_component_is_that_component() -> None:
    assert stats.moe_sum([123.0]) == 123.0


def test_sum_moe_with_weights_scales_each_component() -> None:
    # sqrt((2*10)^2 + (3*20)^2) = sqrt(400 + 3600) = sqrt(4000)
    assert stats.moe_sum([10, 20], weights=[2, 3]) == pytest.approx(math.sqrt(4000))


def test_sum_moe_is_unknown_if_any_component_is_unknown() -> None:
    assert stats.moe_sum([10, None, 5]) is None
    assert stats.moe_sum([]) is None


# ------------------------------------------------------------------------------ proportion
def test_proportion_moe_handbook_example_3() -> None:
    # X = 203,119 ±5,070 never-married females; Y = 630,498 ±831 all females.
    # P = 0.3222; MOE(P) = sqrt(5070^2 - 0.3222^2 * 831^2) / 630,498
    #   = sqrt(25,704,900 - 0.10379 * 690,561) / 630,498 = sqrt(25,633,226) / 630,498 = 0.008030
    # Published: 0.8 % (SE 0.488 %).
    moe = stats.moe_proportion(203_119, 5070, 630_498, 831)
    assert moe is not None
    assert moe * 100 == pytest.approx(0.803, abs=0.001)
    assert round(moe * 100, 1) == 0.8
    assert stats.se(moe * 100) == pytest.approx(0.488, abs=0.001)


def test_proportion_moe_falls_back_to_the_ratio_formula_when_the_radicand_is_negative() -> None:
    # X = 90 ±1, Y = 100 ±50: P = 0.9, MOE(X)^2 = 1 < P^2 MOE(Y)^2 = 0.81 * 2500 = 2025
    # "substitute a plus": sqrt(1 + 2025) / 100 = 0.45011
    assert stats.moe_proportion(90, 1, 100, 50) == pytest.approx(math.sqrt(2026) / 100)


def test_proportion_moe_unknown_inputs() -> None:
    assert stats.moe_proportion(None, 1, 100, 1) is None
    assert stats.moe_proportion(1, None, 100, 1) is None
    assert stats.moe_proportion(1, 1, 100, None) is None
    assert stats.moe_proportion(1, 1, 0, 1) is None  # empty denominator


def test_proportion_of_zero_numerator() -> None:
    # P = 0: MOE = MOE(X) / Y
    assert stats.moe_proportion(0, 12, 400, 30) == pytest.approx(12 / 400)


# ------------------------------------------------------------------------------ ratio, product
def test_ratio_moe_handbook_example_4() -> None:
    # men 226,840 ±5,556.5 (sqrt(4222^2+2819^2+2259^2)); women 203,119 ±5,070; R = 1.11678
    # MOE(R) = sqrt(5556.5^2 + 1.11678^2 * 5070^2) / 203,119 = sqrt(62,947,...) / 203,119 = 0.03906
    men = stats.moe_sum([4222, 2819, 2259])
    assert men == pytest.approx(5556.54, abs=0.01)
    moe = stats.moe_ratio(226_840, men, 203_119, 5070)
    assert moe == pytest.approx(0.0391, abs=0.0001)
    assert round(moe, 3) == 0.039  # published
    assert stats.se(moe) / (226_840 / 203_119) * 100 == pytest.approx(2.1, abs=0.05)  # CV 2.1 %


def test_ratio_moe_unknown_inputs() -> None:
    assert stats.moe_ratio(1, None, 2, 1) is None
    assert stats.moe_ratio(1, 1, 0, 1) is None


def test_product_moe_handbook_example() -> None:
    # 74,506,512 ±228,238 owner units x 0.824 ±0.001 -> 61,393,366 ±202,289
    # sqrt((74,506,512 * 0.001)^2 + (0.824 * 228,238)^2) = sqrt(5.5512e9 + 3.5370e10) = 202,289
    moe = stats.moe_product(74_506_512, 228_238, 0.824, 0.001)
    assert moe == pytest.approx(202_289, abs=1)
    assert stats.moe_product(1, None, 2, 3) is None


# ------------------------------------------------------------------------------ CV and tiers
def test_cv_is_se_over_estimate_in_percent() -> None:
    # handbook: CV(Subgroup 1) = 630 / 3,497 * 100 = 18.0; MOE 1,036 -> SE 629.8
    assert stats.cv(3497, 1036) == pytest.approx(18.0, abs=0.05)


def test_cv_unknown_cases() -> None:
    assert stats.cv(None, 5) is None
    assert stats.cv(5, None) is None
    assert stats.cv(0, 5) is None  # undefined for a zero estimate


@pytest.mark.parametrize(
    ("cv_target", "expected"),
    [
        (0.0, "good"),
        (14.99, "good"),
        (15.0, "good"),  # boundary: <= 15 is good
        (15.01, "caution"),
        (30.0, "caution"),  # boundary: <= 30 is use with caution
        (30.01, "unreliable"),
        (100.0, "unreliable"),
    ],
)
def test_tiers_at_the_boundaries(cv_target: float, expected: str) -> None:
    est = 1000.0
    moe = cv_target / 100 * est * 1.645  # CV = SE / est * 100
    assert stats.tier(est, moe) == expected


def test_tier_zero_estimate_is_caution_unknown_moe_is_unreliable() -> None:
    assert stats.tier(0, 7) == "caution"
    assert stats.tier(0, 0) == "caution"
    assert stats.tier(None, 5) == "unreliable"
    assert stats.tier(5, None) == "unreliable"


def test_tier_of_a_coded_median_is_caution_whatever_its_moe() -> None:
    assert stats.tier(250_000, None, coded=True) == "caution"
    assert stats.tier(250_000, 1, coded=True) == "caution"


def test_worse_tier() -> None:
    assert stats.worse_tier("good", "caution") == "caution"
    assert stats.worse_tier("unreliable", "good") == "unreliable"
    assert stats.worse_tier("caution", "unreliable") == "unreliable"
    assert stats.worse_tier("good", "good") == "good"


# ------------------------------------------------------------------------------ index
@pytest.mark.parametrize(
    ("value", "bench", "expected"),
    [
        (50, 50, 100),
        (64.2, 50, 128),  # 128.4 -> 128
        (64.25, 50, 129),  # 128.5 rounds up (not banker's rounding)
        (0, 50, 0),
        (150, 100, 150),
    ],
)
def test_index(value: float, bench: float, expected: int) -> None:
    assert stats.index_value(value, bench) == expected


def test_index_is_unknown_for_null_or_zero_benchmark() -> None:
    assert stats.index_value(None, 50) is None
    assert stats.index_value(50, None) is None
    assert stats.index_value(50, 0) is None


# ------------------------------------------------------------------------------ interpolation
def test_median_in_the_first_bracket() -> None:
    # counts [10, 2, 2], bounds [0,10) [10,20) [20,30): N=14, half=7 -> 0 + 7/10 * 10 = 7
    m = stats.median_from_counts([10, 2, 2], [(0, 10), (10, 20), (20, 30)])
    assert m is not None and m.value == pytest.approx(7.0) and m.code == "none"


def test_median_in_a_middle_bracket() -> None:
    # [100, 200, 100]: N=400, half=200, C=100, f=200 -> 10 + (200-100)/200 * 10 = 15
    m = stats.median_from_counts([100, 200, 100], [(0, 10), (10, 20), (20, 30)])
    assert m is not None and m.value == pytest.approx(15.0) and m.index == 1


def test_median_in_the_last_finite_bracket() -> None:
    # [1, 1, 8]: N=10, half=5, C=2, f=8 -> 20 + 3/8 * 10 = 23.75
    m = stats.median_from_counts([1, 1, 8], [(0, 10), (10, 20), (20, 30)])
    assert m is not None and m.value == pytest.approx(23.75)


def test_median_in_the_open_top_bracket_is_a_bound_not_an_estimate() -> None:
    m = stats.median_from_counts([1, 1, 8], [(0, 10), (10, 20), (20, INF)])
    assert m is not None
    assert m.value == 20 and m.code == "top"


def test_median_in_the_open_bottom_bracket_is_a_bound() -> None:
    m = stats.median_from_counts([8, 1, 1], [(-INF, 1940), (1940, 1950), (1950, 1960)])
    assert m is not None
    assert m.value == 1940 and m.code == "bottom"


def test_median_with_an_even_total_on_a_bracket_boundary() -> None:
    # [5, 5]: half = 5 lies exactly at the boundary -> 10 (the shared bound)
    m = stats.median_from_counts([5, 5], [(0, 10), (10, 20)])
    assert m is not None and m.value == pytest.approx(10.0)


def test_median_with_an_odd_total() -> None:
    # [3, 4]: N=7, half=3.5, C=3, f=4 -> 10 + 0.5/4 * 10 = 11.25
    m = stats.median_from_counts([3, 4], [(0, 10), (10, 20)])
    assert m is not None and m.value == pytest.approx(11.25)


def test_median_skips_an_empty_middle_bracket() -> None:
    # [4, 0, 4]: N=8, half=4 -> boundary of bracket 0 -> 10
    m = stats.median_from_counts([4, 0, 4], [(0, 10), (10, 20), (20, 30)])
    assert m is not None and m.value == pytest.approx(10.0)
    # [3, 0, 5]: half=4, C=3 through the empty bracket, f=5 -> 20 + 1/5 * 10 = 22
    m = stats.median_from_counts([3, 0, 5], [(0, 10), (10, 20), (20, 30)])
    assert m is not None and m.value == pytest.approx(22.0) and m.index == 2


def test_median_of_an_all_zero_distribution_is_null() -> None:
    assert stats.median_from_counts([0, 0, 0], [(0, 10), (10, 20), (20, 30)]) is None
    assert stats.median_from_counts([], []) is None


def test_median_pums_example_3_massachusetts_income() -> None:
    # PUMS Accuracy 2020-2024, Example 3 (Table 1): median in $60,000-$74,999.
    # half = 1,274,858; C = 1,139,123; f = 231,284 -> 60,000 + 135,735/231,284 * 15,000 = 68,803.14
    counts = [153739, 130852, 113550, 105230, 95824, 102957, 90972, 87818, 83793, 174388,
              231284, 318700, 244795, 178104, 202797, 234913]  # fmt: skip
    bounds = [(0, 10e3), (10e3, 15e3), (15e3, 20e3), (20e3, 25e3), (25e3, 30e3), (30e3, 35e3),
              (35e3, 40e3), (40e3, 45e3), (45e3, 50e3), (50e3, 60e3), (60e3, 75e3), (75e3, 100e3),
              (100e3, 125e3), (125e3, 150e3), (150e3, 200e3), (200e3, INF)]  # fmt: skip
    m = stats.median_from_counts(counts, bounds)
    assert m is not None
    assert m.value == pytest.approx(68_803.14, abs=0.01)
    assert m.index == 10
    # the same document's interval: p = 49.80 % and 50.20 % -> 68,467.48 and 69,129.00 from its
    # two-decimal cumulative percents; from exact counts they are 68,472.41 and 69,133.86, whose
    # half-difference is 330.73 (published SE(median) = 330.76)
    lo = stats.value_at_proportion(0.4980, counts, bounds)
    hi = stats.value_at_proportion(0.5020, counts, bounds)
    assert lo is not None and hi is not None
    assert lo[0] == pytest.approx(68_467.48, abs=10)
    assert hi[0] == pytest.approx(69_129.00, abs=10)
    assert (hi[0] - lo[0]) / 2 == pytest.approx(330.76, abs=0.1 * 330.76 / 100)


def test_value_at_proportion_reports_open_brackets() -> None:
    res = stats.value_at_proportion(0.95, [1, 1, 8], [(0, 10), (10, 20), (20, INF)])
    assert res == (20, "top")


# ------------------------------------------------------------------------------ median MOE
def test_median_moe_hand_calculation() -> None:
    # counts [100, 200, 100] with MOEs [20, 30, 20]; bounds [0,10) [10,20) [20,30)
    #   N = 400; MOE_N = sqrt(400 + 900 + 400) = 41.2311
    #   median bracket k = 2nd; X = 300 with MOE_X = sqrt(400 + 900) = 36.0555
    #   SE(p) = sqrt(MOE_X^2 - 0.25 * MOE_N^2) / N / 1.645 = sqrt(1300 - 425) / 400 / 1.645 = 0.044955
    #   p_lo = 0.455045, p_hi = 0.544955; values: 10 + (p*400 - 100)/200 * 10 = 14.10090, 15.89910
    #   SE(median) = (15.89910 - 14.10090) / 2 = 0.89910; MOE = 1.645 * SE = 1.47902
    moe = stats.median_moe([100, 200, 100], [20, 30, 20], [(0, 10), (10, 20), (20, 30)])
    assert moe == pytest.approx(1.47902, abs=1e-4)


def test_median_moe_unknown_when_a_bracket_moe_is_unknown() -> None:
    assert stats.median_moe([100, 200, 100], [20, None, 20], [(0, 10), (10, 20), (20, 30)]) is None


def test_median_moe_unknown_when_the_median_or_its_interval_is_in_an_open_bracket() -> None:
    assert stats.median_moe([1, 1, 8], [1, 1, 3], [(0, 10), (10, 20), (20, INF)]) is None
    # median in a finite bracket but the interval's upper end spills into the open top bracket
    assert stats.median_moe([40, 10, 50], [9, 4, 9], [(0, 10), (10, 20), (20, INF)]) is None


def test_median_moe_uses_the_ratio_form_when_the_radicand_is_negative() -> None:
    # tiny cumulative MOE against a large total MOE: MOE_X^2 < 0.25 MOE_N^2
    moe = stats.median_moe([100, 100, 100], [1, 1, 80], [(0, 10), (10, 20), (20, 30)])
    # median bracket is the 2nd (X = 200 through bracket 2, MOE_X = sqrt(1 + 1) = 1.41421)
    # MOE_N = sqrt(1 + 1 + 6400) = 80.0125; radicand = 2 - 0.25 * 6402 = -1598.5 < 0,
    # so use the plus form: 2 + 1600.5 = 1602.5
    # SE(p) = sqrt(1602.5) / 300 / 1.645 = 40.0312 / 493.5 = 0.081117 -> p in [0.418883, 0.581117]
    # values: 10 + (p * 300 - 100) / 100 * 10 -> 12.56649 and 17.43351
    # SE(median) = (17.43351 - 12.56649) / 2 = 2.43351; MOE = 1.645 * 2.43351 = 4.00312
    assert moe == pytest.approx(4.00312, abs=1e-4)


# ------------------------------------------------------------------------------ properties
_counts = st.lists(st.integers(0, 10_000), min_size=1, max_size=12)


@given(_counts)
def test_interpolated_median_lies_within_its_bracket(counts: list[int]) -> None:
    bounds = [(10.0 * i, 10.0 * (i + 1)) for i in range(len(counts))]
    m = stats.median_from_counts([float(c) for c in counts], bounds)
    if sum(counts) == 0:
        assert m is None
        return
    assert m is not None
    lo, hi = bounds[m.index]
    assert lo <= m.value <= hi
    assert counts[m.index] > 0 or sum(counts) == 0


@given(_counts, st.floats(0.01, 100.0))
def test_scaling_all_counts_leaves_the_median_unchanged(counts: list[int], w: float) -> None:
    bounds = [(10.0 * i, 10.0 * (i + 1)) for i in range(len(counts))]
    a = stats.median_from_counts([float(c) for c in counts], bounds)
    b = stats.median_from_counts([c * w for c in counts], bounds)
    if a is None:
        assert b is None
    else:
        assert b is not None and b.value == pytest.approx(a.value, rel=1e-9, abs=1e-9)


@given(st.lists(st.floats(0.0, 1e6), min_size=1, max_size=20))
def test_sum_moe_is_at_least_the_largest_component(moes: list[float]) -> None:
    total = stats.moe_sum(moes)
    assert total is not None
    assert total >= max(moes) - 1e-9


@given(st.lists(st.floats(0.0, 1e6), min_size=1, max_size=20), st.floats(0.001, 100.0))
def test_scaling_components_by_w_scales_the_sum_moe_by_w(moes: list[float], w: float) -> None:
    base = stats.moe_sum(moes)
    scaled = stats.moe_sum([m * w for m in moes])
    assert base is not None and scaled is not None
    assert scaled == pytest.approx(base * w, rel=1e-9, abs=1e-9)


@given(
    st.floats(0.0, 1e6),
    st.floats(0.0, 1e5),
    st.floats(1.0, 1e6),
    st.floats(0.0, 1e5),
    st.floats(0.01, 100.0),
)
def test_proportion_moe_is_unchanged_by_uniform_weighting(
    x: float, mx: float, y: float, my: float, w: float
) -> None:
    # SPEC §9.2: scaling all counts by w scales MOEs by w and leaves shares unchanged. The MOE of
    # a share is in share units, so uniform scaling of numerator and denominator cancels.
    y = max(y, x)  # numerator is a subset of the denominator
    a = stats.moe_proportion(x, mx, y, my)
    b = stats.moe_proportion(x * w, mx * w, y * w, my * w)
    assert a is not None and b is not None
    assert b == pytest.approx(a, rel=1e-6, abs=1e-9)
    assert a >= 0 and math.isfinite(a)
