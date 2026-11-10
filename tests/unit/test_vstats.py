"""The vectorized formulas must agree with the scalar ones verified against the handbook."""

from __future__ import annotations

import math

import numpy as np
import pytest
from hypothesis import given
from hypothesis import strategies as st

from zipographics import stats, vstats

_est = st.one_of(st.none(), st.floats(0, 1e6))
_pos = st.one_of(st.none(), st.floats(0, 1e6))


def arr(v: float | None) -> np.ndarray:
    return np.array([np.nan if v is None else v])


def back(a: np.ndarray) -> float | None:
    return None if np.isnan(a[0]) else float(a[0])


def same(a: float | None, b: float | None) -> None:
    if a is None or b is None:
        assert a is None and b is None
    else:
        assert a == pytest.approx(b, rel=1e-9, abs=1e-12)


@given(_est, _est, _pos, _pos)
def test_proportion_agrees_with_the_scalar_formula(x, mx, y, my) -> None:  # type: ignore[no-untyped-def]
    same(
        back(vstats.moe_proportion(arr(x), arr(mx), arr(y), arr(my))),
        stats.moe_proportion(x, mx, y, my),
    )


@given(_est, _est, _pos, _pos)
def test_ratio_agrees_with_the_scalar_formula(x, mx, y, my) -> None:  # type: ignore[no-untyped-def]
    same(back(vstats.moe_ratio(arr(x), arr(mx), arr(y), arr(my))), stats.moe_ratio(x, mx, y, my))


@given(_est, _est, _pos, _pos)
def test_product_agrees_with_the_scalar_formula(a, ma, b, mb) -> None:  # type: ignore[no-untyped-def]
    same(
        back(vstats.moe_product(arr(a), arr(ma), arr(b), arr(mb))), stats.moe_product(a, ma, b, mb)
    )


@given(_est, _est, st.booleans())
def test_tier_agrees_with_the_scalar_rule(est, moe, coded) -> None:  # type: ignore[no-untyped-def]
    got = vstats.tier(arr(est), arr(moe), np.array([coded]))
    assert got[0] == stats.tier(est, moe, coded=coded)


@pytest.mark.parametrize("cv_target", [0.0, 14.99, 15.0, 15.01, 30.0, 30.01, 100.0])
def test_tier_boundaries(cv_target: float) -> None:
    moe = cv_target / 100 * 1000.0 * 1.645
    assert vstats.tier(arr(1000.0), arr(moe), np.array([False]))[0] == stats.tier(1000.0, moe)


@given(st.floats(0, 1e6), st.one_of(st.none(), st.floats(0, 1e6)))
def test_index_agrees_with_the_scalar_rule(est: float, bench: float | None) -> None:
    got = vstats.index_values(arr(est), bench)
    expected = stats.index_value(est, bench)
    assert (None if np.isnan(got[0]) else int(got[0])) == expected


def test_handbook_proportion_example_vectorized() -> None:
    got = vstats.moe_proportion(arr(203_119), arr(5070), arr(630_498), arr(831))
    assert round(float(got[0]) * 100, 1) == 0.8
    assert math.isclose(float(got[0]) * 100, 0.803, abs_tol=0.001)


def test_vectorized_proportion_has_the_same_noise_and_overflow_behavior() -> None:
    for w in (1.0, 3.0, 0.37, 100.0):
        got = vstats.moe_proportion(arr(1 * w), arr(1 * w), arr(41.5 * w), arr(41.5 * w))
        assert float(got[0]) == pytest.approx(0.0, abs=1e-6)
    tiny = vstats.moe_proportion(arr(1.0), arr(0.0), arr(2.225073858507203e-309), arr(0.0))
    assert np.isnan(tiny[0])
