"""Filters and table ordering, policy-enforced in the library (SPEC 5.5, 5.7)."""

from __future__ import annotations

import math

import pytest
from synth_art import Z, make_artifacts

from zipographics import analysis as an
from zipographics import filters, metrics, table
from zipographics.errors import RestrictedUseError
from zipographics.models import Rule, UsePolicy
from zipographics.zips import parse_paste

OFF = UsePolicy(False, "Retail (general & specialty)", "No")
ON = UsePolicy(True, "Insurance", "Yes (set by industry)")
ON_ANSWERED = UsePolicy(True, "Automotive sales", "Yes")

WORLD = {
    "33602": Z(5000, 2000, owner=0.40, kids=0.20),
    "33606": Z(8000, 3500, owner=0.70, kids=0.35),
    # an owner count far less certain than its denominator: an unreliable share
    "33603": Z(900, 280, owner=0.55, kids=0.30, extra={"B25003_002": (154.0, 200.0)}),
    "33604": Z(2500, 1200, owner=0.65, kids=0.25, income=None),  # no published median income
}
ART = make_artifacts(WORLD)
CODED = make_artifacts(
    {
        "99001": Z(4000, 1500, income=250_001, code="top"),
        "99002": Z(3000, 1000, income=2_499, code="bottom"),
        "99003": Z(3500, 1300, income=90_000),
    }
)


def run(art=ART, text="33602 33606 33603 33604", policy=OFF):  # type: ignore[no-untyped-def]
    return an.analyze(art, parse_paste(text), policy)


SHARED = run()  # built once: the every-metric tests below only read it


def rule(metric: str, op: str, value: float, basis: str = "value") -> Rule:
    return Rule(metric, op, value, basis)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------- rules
def test_a_value_rule_selects_matching_zips_in_input_order() -> None:
    r = filters.apply(run(), [rule("owner", ">=", 0.60)], OFF)
    assert r.qualifying == ("33606", "33604")
    assert r.active and r.matches["33602"].qualifies is False


def test_rules_are_anded() -> None:
    r = filters.apply(run(), [rule("owner", ">=", 0.60), rule("hh_kids", "<=", 0.30)], OFF)
    assert r.qualifying == ("33604",)


def test_an_index_rule_compares_the_zip_index_to_the_benchmark() -> None:
    # Florida: 27 % of households have children; 0.35 / 0.27 = 130, 0.30 / 0.27 = 111
    r = filters.apply(run(), [rule("hh_kids", ">=", 115, "index")], OFF)
    assert r.qualifying == ("33606",)


def test_a_null_value_never_qualifies_even_when_the_comparison_is_trivial() -> None:
    r = filters.apply(run(), [rule("median_hh_income", ">=", 0)], OFF)
    assert "33604" not in r.qualifying and set(r.qualifying) == {"33602", "33606", "33603"}
    r = filters.apply(run(), [rule("median_hh_income", "<=", 10**9)], OFF)
    assert "33604" not in r.qualifying


def test_a_zip_that_qualifies_only_on_an_unreliable_estimate_is_marked() -> None:
    r = filters.apply(run(), [rule("owner", "<=", 0.60)], OFF)
    assert "33603" in r.qualifying and r.matches["33603"].on_unreliable
    assert not r.matches["33602"].on_unreliable
    assert r.unreliable_matches == ("33603",)


def test_exclude_unreliable_drops_those_matches_but_reports_them() -> None:
    r = filters.apply(run(), [rule("owner", "<=", 0.60)], OFF, exclude_unreliable=True)
    assert r.qualifying == ("33602",)
    assert r.unreliable_matches == ("33603",)
    assert r.matches["33603"].qualifies is False and r.matches["33603"].on_unreliable


def test_a_top_coded_median_compares_as_a_bound() -> None:
    a = run(CODED, "99001 99002 99003")
    assert filters.apply(a, [rule("median_hh_income", ">=", 200_000)], OFF).qualifying == ("99001",)
    r = filters.apply(a, [rule("median_hh_income", "<=", 300_000)], OFF)
    assert r.qualifying == ("99002", "99003")  # "$250,000+" might be above 300,000: uncertain
    assert r.matches["99001"].uncertain == ("median_hh_income",)
    # certainly not at or below 200,000, so it is a plain miss rather than uncertain
    r2 = filters.apply(a, [rule("median_hh_income", "<=", 200_000)], OFF)
    assert "99001" not in r2.qualifying and r2.matches["99001"].uncertain == ()


def test_a_bottom_coded_median_compares_as_a_bound() -> None:
    a = run(CODED, "99001 99002 99003")
    assert "99002" in filters.apply(a, [rule("median_hh_income", "<=", 5_000)], OFF).qualifying
    r = filters.apply(a, [rule("median_hh_income", ">=", 1_000)], OFF)
    assert "99002" not in r.qualifying and r.matches["99002"].uncertain == ("median_hh_income",)
    assert "99002" not in filters.apply(a, [rule("median_hh_income", ">=", 10_000)], OFF).qualifying


def test_a_coded_median_has_no_index_so_an_index_rule_never_matches_it() -> None:
    a = run(CODED, "99001 99002 99003")
    r = filters.apply(a, [rule("median_hh_income", ">=", 50, "index")], OFF)
    assert r.qualifying == ("99003",)


def test_the_summary_counts_zips_and_households() -> None:
    r = filters.apply(run(), [rule("owner", ">=", 0.60)], OFF)
    assert r.matching_households == 3500 + 1200
    assert r.total_households == 2000 + 3500 + 280 + 1200
    assert r.summary_line() == "2 of 4 ZIPs match (households: 4,700 of 6,980)"


def test_no_rules_means_no_filtering() -> None:
    a = run()
    r = filters.apply(a, [], OFF)
    assert not r.active and r.qualifying == a.zips and r.summary_line() is None
    # an empty rule list selects nothing, so it is allowed even in restricted mode
    assert filters.apply(a, [], ON).qualifying == a.zips


def test_invalid_rules_are_rejected() -> None:
    a = run()
    with pytest.raises(ValueError, match="at most 6"):
        filters.apply(a, [rule("owner", ">=", 0.1)] * 7, OFF)
    with pytest.raises(ValueError, match="Unknown metric"):
        filters.apply(a, [rule("nope", ">=", 1)], OFF)
    with pytest.raises(ValueError, match="count"):
        filters.apply(a, [rule("pop", ">=", 100, "index")], OFF)  # counts have no index
    with pytest.raises(ValueError, match="comparison"):
        filters.apply(a, [rule("owner", "==", 0.5)], OFF)
    with pytest.raises(ValueError, match="basis"):
        filters.apply(a, [rule("owner", ">=", 0.5, "rank")], OFF)
    with pytest.raises(ValueError, match="finite"):
        filters.apply(a, [rule("owner", ">=", math.nan)], OFF)
    with pytest.raises(ValueError, match="fraction"):
        filters.apply(a, [rule("owner", ">=", 60)], OFF)  # shares are 0-1, not percent


def test_a_rule_on_a_count_by_value_is_allowed() -> None:
    assert filters.apply(run(), [rule("pop", ">=", 4000)], OFF).qualifying == ("33602", "33606")


def test_rules_read_naturally() -> None:
    assert filters.describe(rule("owner", ">=", 0.6)) == "Homeowners ≥ 60 %"
    assert filters.describe(rule("hh_kids", ">=", 115, "index")) == (
        "Households with children, index ≥ 115"
    )
    assert filters.describe(rule("median_hh_income", "<=", 75_000)) == (
        "Median household income ≤ $75,000"
    )


# ---------------------------------------------------------------------------- restricted mode
@pytest.mark.parametrize("policy", [ON, ON_ANSWERED, None])
@pytest.mark.parametrize("metric", [m.id for m in metrics.REGISTRY])
def test_restricted_mode_refuses_a_rule_on_every_metric(
    metric: str, policy: UsePolicy | None
) -> None:
    a = SHARED
    basis = "index" if metrics.BY_ID[metric].indexable else "value"
    for b in ("value", basis):
        with pytest.raises(RestrictedUseError):
            filters.apply(a, [rule(metric, ">=", 0.0, b)], policy)


def test_the_policy_is_checked_before_the_rule_is_validated() -> None:
    with pytest.raises(RestrictedUseError):
        filters.apply(run(), [rule("nope", "==", math.nan)], ON)


def test_a_restricted_run_never_returns_a_subset() -> None:
    a = run(policy=ON)
    for rules in ([], [rule("owner", ">=", 0.6)]):
        try:
            r = filters.apply(a, rules, a.policy)
        except RestrictedUseError:
            continue
        assert r.qualifying == a.zips


# ---------------------------------------------------------------------------- ordering
def test_input_and_zip_order_are_always_allowed() -> None:
    a = run(text="33606 33602 33604 33603")
    for policy in (OFF, ON, None):
        assert table.order(a, "input", policy) == a.zips
        assert table.order(a, "zip", policy) == tuple(sorted(a.zips))
    assert table.order(a, "zip", OFF, descending=True) == tuple(sorted(a.zips, reverse=True))


def test_ordering_by_a_metric_sorts_by_value_with_nulls_last() -> None:
    a = run()
    assert table.order(a, "owner", OFF) == ("33602", "33603", "33604", "33606")
    assert table.order(a, "owner", OFF, descending=True) == ("33606", "33604", "33603", "33602")
    by_income = table.order(a, "median_hh_income", OFF, descending=True)
    assert by_income[-1] == "33604"  # no income: last in both directions
    assert table.order(a, "median_hh_income", OFF)[-1] == "33604"


def test_ordering_by_index_uses_the_index_column() -> None:
    a = run()
    assert table.order(a, "hh_kids", OFF, index=True, descending=True)[0] == "33606"


def test_ordering_is_stable_for_ties() -> None:
    a = an.analyze(
        make_artifacts({"11111": Z(100, 50), "22222": Z(100, 50), "33333": Z(100, 50)}),
        parse_paste("33333 11111 22222"),
        OFF,
    )
    assert table.order(a, "pop", OFF) == ("33333", "11111", "22222")


@pytest.mark.parametrize("policy", [ON, ON_ANSWERED, None])
@pytest.mark.parametrize("metric", [m.id for m in metrics.REGISTRY])
def test_restricted_mode_refuses_ordering_by_every_metric(
    metric: str, policy: UsePolicy | None
) -> None:
    a = SHARED
    with pytest.raises(RestrictedUseError):
        table.order(a, metric, policy)
    with pytest.raises(RestrictedUseError):
        table.order(a, metric, policy, index=True, descending=True)


def test_an_unknown_order_key_is_an_error() -> None:
    with pytest.raises(ValueError, match="Unknown order key"):
        table.order(run(), "nope", OFF)
