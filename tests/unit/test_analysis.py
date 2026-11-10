"""The shared analysis object behind the app, exports, report and CLI (SPEC 5.4-5.5, 6.7-6.8)."""

from __future__ import annotations

import pytest
from synth_art import Z, make_artifacts

from zipographics import analysis as an
from zipographics import profile
from zipographics.models import ParsedInput, UsePolicy
from zipographics.zips import parse_paste

OFF = UsePolicy(False, "Retail (general & specialty)", "No")
ON = UsePolicy(True, "Mortgage & lending", "Yes (set by industry)")

WORLD = {
    "33602": Z(5000, 2000, owner=0.40, kids=0.20),
    "33606": Z(8000, 3500, owner=0.70, kids=0.35),
    # small population, and an owner count much less certain than its denominator
    "33603": Z(900, 280, owner=0.55, kids=0.30, rel_moe=0.6, extra={"B25003_002": (154.0, 120.0)}),
    "30301": Z(
        3000, 1200, owner=0.50, state="GA", county=("13121", "Fulton County"), city="Atlanta"
    ),
}
ART = make_artifacts(WORLD)


def run(text: str = "33602 33606 33603", policy: UsePolicy = OFF, **kw):  # type: ignore[no-untyped-def]
    return an.analyze(ART, parse_paste(text), policy, **kw)


def test_the_analysis_profiles_the_recognized_zips_in_input_order() -> None:
    a = run("33606 99999 33602")
    assert a.zips == ("33606", "33602")
    assert a.summary.not_found == ("99999",)
    t = a.trade.values
    assert t["pop"].estimate == pytest.approx(13_000)
    assert t["hh"].estimate == pytest.approx(5_500)
    assert t["owner"].estimate == pytest.approx((0.7 * 3500 + 0.4 * 2000) / 5500, abs=1e-3)
    assert not a.weighted and a.mode == "full" and a.weights is None


def test_the_default_benchmark_is_the_dominant_state_and_the_index_is_against_it() -> None:
    a = run()
    assert (a.benchmark.level, a.benchmark.name) == ("state", "Florida")
    owner = a.trade.values["owner"].estimate
    assert owner is not None
    assert a.index["owner"].value == round(100 * owner / 0.66)
    assert a.bench.values["owner"].estimate == pytest.approx(0.66)
    assert "pop" not in a.index  # counts have no index (they show a share of the benchmark)
    assert a.share_of_benchmark("hh") == pytest.approx(a.trade.values["hh"].estimate / 9e6)


def test_the_benchmark_can_be_switched_to_county_or_nation() -> None:
    a = run()
    county = run(benchmark=a.options.default_county)
    assert county.benchmark.level == "county" and county.benchmark.name == "Hillsborough County"
    us = run(benchmark=a.options.us)
    assert us.benchmark.level == "us"
    assert us.index["owner"].value != a.index["owner"].value


def test_a_benchmark_that_is_not_in_the_data_is_rejected() -> None:
    from zipographics.profile import BenchmarkRef

    with pytest.raises(ValueError, match="benchmark"):
        run(benchmark=BenchmarkRef("state", "99", "Nowhere"))


def test_multi_state_input_defaults_to_the_state_with_most_population() -> None:
    a = run("33602 33606 30301")
    assert a.benchmark.name == "Florida"
    assert {s.name for s in a.options.states} == {"Florida", "Georgia"}
    b = run("30301 33603")  # 3,000 in GA beats 900 in FL
    assert b.benchmark.name == "Georgia"


def test_zipcator_input_defaults_to_in_radius_estimates() -> None:
    parsed = ParsedInput(
        zips=("33602", "33606"), overlaps={"33602": 50.0, "33606": 25.0}, source="zipcator"
    )
    a = an.analyze(ART, parsed, OFF)
    assert a.mode == "in_radius" and a.weighted
    assert a.weights == {"33602": 0.5, "33606": 0.25}
    assert a.trade.values["pop"].estimate == pytest.approx(5000 * 0.5 + 8000 * 0.25)
    assert a.in_radius("33602", "hh") == pytest.approx(1000)
    assert a.in_radius("33606", "hh") == pytest.approx(3500 * 0.25)
    full = an.analyze(ART, parsed, OFF, mode="full")
    assert full.mode == "full" and full.weights is None
    assert full.trade.values["pop"].estimate == pytest.approx(13_000)
    assert full.in_radius("33602", "hh") is None


def test_a_zip_with_a_blank_overlap_counts_in_full_when_in_radius_is_on() -> None:
    parsed = ParsedInput(
        zips=("33602", "33606"),
        overlaps={"33602": 50.0},
        blank_overlap=("33606",),
        source="zipcator",
    )
    a = an.analyze(ART, parsed, OFF)
    assert a.trade.values["pop"].estimate == pytest.approx(2500 + 8000)


def test_in_radius_needs_overlaps() -> None:
    with pytest.raises(ValueError, match="overlap"):
        run(mode="in_radius")


def test_blocking_problems_stop_the_analysis() -> None:
    with pytest.raises(ValueError, match="No ZIPs were recognized"):
        run("99999")
    with pytest.raises(ValueError, match="No ZIPs"):
        run("")


def test_the_lens_follows_the_vertical_and_restricted_mode_forces_context() -> None:
    assert run(policy=UsePolicy(False, "Automotive sales", "No")).lens.name == "Auto sales"
    assert (
        run(policy=UsePolicy(False, "Automotive sales", "No"), lens="Retail").lens.name == "Retail"
    )
    assert run(policy=ON).lens.name == "Context"
    assert run(policy=ON, lens="Retail").lens.name == "Context"


def test_the_vintage_label_is_derived_from_the_metadata() -> None:
    assert run().vintage_label == "ACS 2020-2024 5-year estimates"


def test_per_zip_index_carries_the_worse_of_the_two_tiers() -> None:
    a = run()
    col = a.zip_index("owner")
    assert col[0].value == round(100 * 0.40 / 0.66)
    # 33603 has 60 % relative MOEs on its counts: its share is not "good"
    assert col[2].tier in ("caution", "unreliable")
    assert col[0].tier == "good"


def test_per_zip_values_come_from_the_full_zip_table() -> None:
    a = run()
    assert a.value("33606", "owner").estimate == pytest.approx(0.70, abs=1e-3)
    assert a.value("33606", "pop").estimate == pytest.approx(8000)


def test_facts_for_the_table_rows() -> None:
    a = run("33602 30301")
    assert a.row_facts("30301") == {
        "city": "Atlanta", "county": "Fulton County", "state": "GA",
    }  # fmt: skip


def test_the_trade_area_equals_the_engine_directly() -> None:
    a = run()
    direct = profile.build_profile(ART.profile, list(a.zips))
    assert a.trade.values["owner"] == direct.values["owner"]


def test_unrestricted_and_restricted_runs_compute_the_same_numbers() -> None:
    assert run(policy=OFF).trade.values["hh_kids"] == run(policy=ON).trade.values["hh_kids"]
