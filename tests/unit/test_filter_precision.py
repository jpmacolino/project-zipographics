"""Filters compare at the precision the table displays (DECISIONS P10).

A value shown as "25.0 %" must qualify for ">= 25 %" even if its true share is 0.2496, and a value
shown as "$75,000" must qualify for ">= $75,000" even if it is 74,999.6. The property below checks
that for any value, a threshold equal to what is displayed always qualifies, in both directions.
"""

from __future__ import annotations

import math

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from synth_art import Z, make_artifacts

from zipographics import analysis as an
from zipographics import filters, metrics, ui, verticals
from zipographics.models import Rule
from zipographics.zips import parse_paste

OFF = verticals.make_policy("Retail (general & specialty)", False)


def analysis_of(**z):  # type: ignore[no-untyped-def]
    art = make_artifacts({"33602": Z(20_000, 10_000, **z)})
    ids = ["pop", "hh", "owner", "hh_kids", "median_hh_income", "median_age"]
    return an.analyze(art, parse_paste("33602"), OFF, metric_ids=ids)


def qualifies(a: an.Analysis, metric: str, op: str, value: float) -> bool:
    r = filters.apply(a, [Rule(metric, op, value)])  # type: ignore[arg-type]
    return "33602" in r.qualifying


# ----------------------------------------------------------------------------- the examples
@pytest.mark.parametrize(
    ("owner", "shown", "ge_25_or_50", "le"),
    [
        (0.4997, "50.0 %", True, True),
        (0.4994, "49.9 %", False, True),
        (0.5004, "50.0 %", True, True),
    ],
)
def test_a_share_is_compared_as_displayed(
    owner: float, shown: str, ge_25_or_50: bool, le: bool
) -> None:
    a = analysis_of(owner=owner)
    assert ui.fmt_value(metrics.BY_ID["owner"], a.value("33602", "owner")) == shown
    assert qualifies(a, "owner", ">=", 0.5) is ge_25_or_50
    assert qualifies(a, "owner", "<=", 0.5) is le


def test_a_share_that_displays_as_25_percent_meets_the_premium_style_threshold() -> None:
    a = analysis_of(owner=0.2496)
    assert ui.fmt_value(metrics.BY_ID["owner"], a.value("33602", "owner")) == "25.0 %"
    assert qualifies(a, "owner", ">=", 0.25) and qualifies(a, "owner", "<=", 0.25)
    assert not qualifies(a, "owner", ">=", 0.251)  # displayed 25.0 % is below 25.1 %


def test_dollars_are_compared_as_whole_dollars() -> None:
    a = analysis_of(income=74_999.6)
    assert (
        ui.fmt_value(metrics.BY_ID["median_hh_income"], a.value("33602", "median_hh_income"))
        == "$75,000"
    )
    assert qualifies(a, "median_hh_income", ">=", 75_000)
    assert not qualifies(a, "median_hh_income", ">=", 75_001)
    b = analysis_of(income=74_999.4)  # displays $74,999
    assert not qualifies(b, "median_hh_income", ">=", 75_000)
    assert qualifies(b, "median_hh_income", "<=", 74_999)


def test_a_median_age_is_compared_to_one_decimal() -> None:
    a = analysis_of(extra={"B01002_001": (37.96, 1.0)})
    assert ui.fmt_value(metrics.BY_ID["median_age"], a.value("33602", "median_age")) == "38.0"
    assert qualifies(a, "median_age", ">=", 38.0)
    assert not qualifies(a, "median_age", ">=", 38.1)


def test_an_index_is_already_a_whole_number() -> None:
    a = analysis_of(owner=0.4)  # round(100 * 0.40 / 0.66) = 61
    r = filters.apply(a, [Rule("owner", ">=", 61, "index")])
    assert "33602" in r.qualifying
    assert "33602" not in filters.apply(a, [Rule("owner", ">=", 62, "index")]).qualifying


def test_counts_are_compared_as_whole_numbers() -> None:
    art = make_artifacts({"33602": Z(5000, 2000, extra={"B01003_001": (4999.6, 100.0)})})
    a = an.analyze(art, parse_paste("33602"), OFF)
    assert ui.fmt_value(metrics.BY_ID["pop"], a.value("33602", "pop")) == "5,000"
    assert qualifies(a, "pop", ">=", 5000)


# ----------------------------------------------------------------------------- the property
def test_displayed_value_matches_the_text_for_every_unit() -> None:
    for m in metrics.REGISTRY:
        for v in (0.0, 0.0004, 0.2496, 0.5, 0.99996, 37.96, 74_999.6, 1_234_567.49):
            text = ui.fmt_number(m, v)
            digits = "".join(ch for ch in text if ch.isdigit() or ch in ".")
            assert math.isclose(
                ui.displayed_value(m, v) * ui.scale_of(m), float(digits), abs_tol=1e-9
            )


@settings(max_examples=150, deadline=None)
@given(share=st.integers(min_value=0, max_value=10_000))
def test_a_displayed_share_always_meets_a_threshold_equal_to_it(share: int) -> None:
    owner = share / 10_000  # a share of 10,000 households, so the estimate is exactly this
    a = analysis_of(owner=owner)
    m = metrics.BY_ID["owner"]
    est = a.value("33602", "owner").estimate
    assert est is not None
    shown = ui.displayed_value(m, est)  # what the table shows, as a fraction
    assert qualifies(a, "owner", ">=", shown)
    assert qualifies(a, "owner", "<=", shown)
    # and the threshold typed the way a user would type it from the displayed text
    typed = float(ui.fmt_number(m, est).split()[0]) / 100
    assert qualifies(a, "owner", ">=", typed) and qualifies(a, "owner", "<=", typed)


@settings(max_examples=100, deadline=None)
@given(income=st.floats(min_value=10_000, max_value=240_000, allow_nan=False))
def test_a_displayed_dollar_amount_always_meets_a_threshold_equal_to_it(income: float) -> None:
    a = analysis_of(income=income)
    m = metrics.BY_ID["median_hh_income"]
    shown = float(
        ui.fmt_value(m, a.value("33602", "median_hh_income")).replace("$", "").replace(",", "")
    )
    assert qualifies(a, "median_hh_income", ">=", shown)
    assert qualifies(a, "median_hh_income", "<=", shown)
