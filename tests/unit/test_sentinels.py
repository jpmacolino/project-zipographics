"""Tests for zipographics.sentinels: ACS annotation values become nulls (SPEC §6.1, §9.2)."""

from __future__ import annotations

import math

import pandas as pd
import pytest
from hypothesis import given
from hypothesis import strategies as st

from zipographics.sentinels import (
    ALL_SENTINELS,
    UnknownSentinelError,
    clean_frame,
    clean_pair,
    median_code,
)

EST_NULL = [-666666666, -999999999, -888888888]
MOE_NULL = [-222222222, -333333333]
CONTROLLED = -555555555


def s(*values: object) -> pd.Series:
    return pd.Series(list(values), dtype="object")


# -------------------------------------------------------------------- estimate column
@pytest.mark.parametrize("sentinel", ALL_SENTINELS)
def test_a_sentinel_in_the_estimate_column_is_null_and_nulls_its_moe(sentinel: int) -> None:
    est, moe, _ = clean_pair(s(sentinel, 100), s(50, 7))
    assert math.isnan(est[0]) and math.isnan(moe[0])
    assert est[1] == 100 and moe[1] == 7


def test_ordinary_values_pass_through_as_floats() -> None:
    est, moe, counts = clean_pair(s(0, 12.5, 250000), s(0, 3.25, 1000))
    assert list(est) == [0.0, 12.5, 250000.0]
    assert list(moe) == [0.0, 3.25, 1000.0]
    assert counts == {}
    assert est.dtype == "float64" and moe.dtype == "float64"


def test_strings_from_the_api_are_parsed_and_missing_values_are_null() -> None:
    est, moe, _ = clean_pair(s("1234", None, "", "null", "NaN"), s("56", "7", None, "", "x"))
    assert est[0] == 1234.0 and moe[0] == 56.0
    assert math.isnan(est[1]) and math.isnan(moe[1])  # a null estimate has no MOE
    assert math.isnan(est[2]) and math.isnan(est[3]) and math.isnan(est[4])


def test_a_null_estimate_always_has_a_null_moe() -> None:
    est, moe, _ = clean_pair(s(None, 5), s(10, 10))
    assert math.isnan(est[0]) and math.isnan(moe[0])
    assert est[1] == 5 and moe[1] == 10


# -------------------------------------------------------------------- MOE column
@pytest.mark.parametrize("sentinel", MOE_NULL)
def test_moe_not_computable_nulls_the_moe_and_keeps_the_estimate(sentinel: int) -> None:
    est, moe, _ = clean_pair(s(100), s(sentinel))
    assert est[0] == 100
    assert math.isnan(moe[0])


def test_controlled_estimate_moe_is_zero() -> None:
    est, moe, _ = clean_pair(s(100), s(CONTROLLED))
    assert est[0] == 100
    assert moe[0] == 0.0


@pytest.mark.parametrize("sentinel", EST_NULL)
def test_estimate_sentinels_in_the_moe_column_null_the_moe_only(sentinel: int) -> None:
    est, moe, _ = clean_pair(s(100), s(sentinel))
    assert est[0] == 100
    assert math.isnan(moe[0])


# -------------------------------------------------------------------- unknown large negatives
@pytest.mark.parametrize("bad", [-123456789, -100000001, -2147483648, -999999998])
def test_an_unknown_large_negative_value_fails_the_build(bad: int) -> None:
    with pytest.raises(UnknownSentinelError, match=str(bad)):
        clean_pair(s(bad), s(1))
    with pytest.raises(UnknownSentinelError, match=str(bad)):
        clean_pair(s(1), s(bad))


@pytest.mark.parametrize("fine", [-100000000, -99999, -1, 0])
def test_other_negative_values_are_not_sentinels(fine: int) -> None:
    est, _, _ = clean_pair(s(fine), s(1))
    assert est[0] == fine


# -------------------------------------------------------------------- counts for metadata
def test_sentinel_counts_are_reported_by_column_and_code() -> None:
    _, _, counts = clean_pair(s(-666666666, -666666666, 5, -999999999), s(1, 2, -555555555, 3))
    assert counts == {
        "estimate:-666666666": 2,
        "estimate:-999999999": 1,
        "moe:-555555555": 1,
    }


# -------------------------------------------------------------------- median codes
@pytest.mark.parametrize(
    ("annotation", "expected"),
    [
        ("median+", "top"),
        ("median-", "bottom"),
        ("250000+", "top"),
        ("250,000+", "top"),
        ("3500+", "top"),
        ("2,500-", "bottom"),
        ("-", "none"),  # the annotation of an uncomputable estimate, not a code
        ("N", "none"),
        ("(X)", "none"),
        ("", "none"),
        (None, "none"),
        ("100", "none"),
    ],
)
def test_median_code_from_the_estimate_annotation(annotation: str | None, expected: str) -> None:
    assert list(median_code(pd.Series([annotation], dtype="object"))) == [expected]


# -------------------------------------------------------------------- whole frames
def test_clean_frame_renames_columns_and_adds_codes_for_medians() -> None:
    raw = pd.DataFrame(
        {
            "zip code tabulation area": ["02108", "00601", "33602"],  # never numbers
            "B19013_001E": ["250001", "-666666666", "60000"],
            "B19013_001M": ["-333333333", "-555555555", "5000"],
            "B19013_001EA": ["250000+", "-", None],
            "B01003_001E": ["3600", "17000", "-888888888"],
            "B01003_001M": ["400", "900", "-888888888"],
        }
    )
    out, counts = clean_frame(
        raw, key="zip code tabulation area", variables={"B19013_001": True, "B01003_001": False}
    )
    assert list(out.index) == ["02108", "00601", "33602"]
    assert out.index.name == "zip"
    assert list(out["B19013_001_e"].fillna(-1)) == [250001.0, -1.0, 60000.0]
    assert out["B19013_001_m"].isna().tolist() == [True, True, False]
    assert list(out["B19013_001_code"]) == ["top", "none", "none"]
    assert "B01003_001_code" not in out.columns
    assert out["B01003_001_e"].isna().tolist() == [False, False, True]
    assert counts["estimate:-666666666"] == 1
    assert counts["moe:-333333333"] == 1


def test_clean_frame_keeps_zip_strings_with_leading_zeros() -> None:
    raw = pd.DataFrame(
        {"zcta": ["00501", "02108"], "B01003_001E": ["1", "2"], "B01003_001M": ["1", "1"]}
    )
    out, _ = clean_frame(raw, key="zcta", variables={"B01003_001": False})
    assert list(out.index) == ["00501", "02108"]
    assert all(isinstance(z, str) for z in out.index)


# -------------------------------------------------------------------- property
_value = st.one_of(
    st.sampled_from(ALL_SENTINELS),
    st.integers(0, 10**7),
    st.floats(0, 1e7, allow_nan=False),
    st.none(),
)


@given(st.lists(st.tuples(_value, _value), min_size=1, max_size=40))
def test_no_sentinel_survives_in_any_output(pairs: list[tuple[object, object]]) -> None:
    est, moe, _ = clean_pair(s(*[p[0] for p in pairs]), s(*[p[1] for p in pairs]))
    for series in (est, moe):
        assert not series.isin(ALL_SENTINELS).any()
        assert (series.dropna() >= 0).all()
    assert (est.isna() <= moe.isna()).all()  # a null estimate never has a MOE
