"""Tests for the benchmark choice in zipographics.profile (SPEC §5.5, §6.8, §9.2)."""

from __future__ import annotations

import pytest
from synth_facts import make_facts

from zipographics import profile
from zipographics.facts import STATE_FIPS, STATE_NAMES

HILLS = ("12057", "Hillsborough County")
PINELLAS = ("12103", "Pinellas County")
FULTON = ("13121", "Fulton County")
CLAY = ("29047", "Clay County")
WYANDOTTE = ("20209", "Wyandotte County")
JACKSON = ("29095", "Jackson County")

FACTS = make_facts(
    {
        "33602": ("FL", 5000, 2000),
        "33603": ("FL", 6000, 2500),
        "33701": ("FL", 9000, 4000),
        "30301": ("GA", 4000, 1500),
        "66101": ("KS", 8000, 3000),
        "66102": ("KS", 3000, 1000),
        "64105": ("MO", 5000, 2000),
        "64106": ("MO", 4000, 1500),
        "00601": ("PR", 17000, 6000),
        "00603": ("PR", 40000, 15000),
    },
    {
        "33602": HILLS,
        "33603": HILLS,
        "33701": PINELLAS,
        "30301": FULTON,
        "66101": WYANDOTTE,
        "66102": WYANDOTTE,
        "64105": JACKSON,
        "64106": JACKSON,
    },
)


def test_state_fips_and_names_agree() -> None:
    assert set(STATE_FIPS) == set(STATE_NAMES)
    assert STATE_FIPS["FL"] == "12" and STATE_FIPS["MA"] == "25" and STATE_FIPS["PR"] == "72"
    assert len(set(STATE_FIPS.values())) == 52


def test_single_state_default_is_that_state() -> None:
    opts = profile.benchmark_options(["33602", "33603"], FACTS)
    assert opts.default == profile.BenchmarkRef("state", "12", "Florida")
    assert [r.name for r in opts.states] == ["Florida"]
    assert opts.us == profile.BenchmarkRef("us", "1", "United States")
    assert opts.puerto_rico_note is None


def test_multi_state_default_is_the_state_with_the_most_input_population() -> None:
    # Kansas City: Kansas 8,000 + 3,000 = 11,000 vs Missouri 5,000 + 4,000 = 9,000 -> Kansas
    opts = profile.benchmark_options(["66101", "66102", "64105", "64106"], FACTS)
    assert opts.default == profile.BenchmarkRef("state", "20", "Kansas")
    assert [r.name for r in opts.states] == ["Kansas", "Missouri"]  # largest first


def test_the_default_state_tie_goes_to_the_first_zip() -> None:
    facts = make_facts({"33602": ("FL", 100, 1), "30301": ("GA", 100, 1)})
    assert profile.benchmark_options(["30301", "33602"], facts).default.name == "Georgia"
    assert profile.benchmark_options(["33602", "30301"], facts).default.name == "Florida"


def test_default_county_is_the_primary_county_with_the_most_input_population() -> None:
    # Hillsborough 5,000 + 6,000 = 11,000 vs Pinellas 9,000
    opts = profile.benchmark_options(["33602", "33603", "33701"], FACTS)
    assert opts.default_county == profile.BenchmarkRef("county", "12057", "Hillsborough County")
    assert [r.geo_id for r in opts.counties] == ["12057", "12103"]


def test_county_default_can_differ_from_the_state_default_ordering() -> None:
    # Kansas City: Jackson MO (9,000) vs Wyandotte KS (11,000) -> Wyandotte, in the dominant state
    opts = profile.benchmark_options(["66101", "66102", "64105", "64106"], FACTS)
    assert opts.default_county is not None and opts.default_county.geo_id == "20209"
    assert {r.geo_id for r in opts.counties} == {"20209", "29095"}


def test_county_ids_are_five_digit_strings() -> None:
    opts = profile.benchmark_options(["33602"], FACTS)
    assert opts.default_county is not None
    assert isinstance(opts.default_county.geo_id, str) and len(opts.default_county.geo_id) == 5


def test_without_county_columns_there_is_no_county_option() -> None:
    plain = make_facts({"33602": ("FL", 5000, 2000)})
    opts = profile.benchmark_options(["33602"], plain)
    assert opts.default_county is None and opts.counties == ()


def test_puerto_rico_input_gets_the_state_benchmark_and_the_national_note() -> None:
    opts = profile.benchmark_options(["00601", "00603"], FACTS)
    assert opts.default == profile.BenchmarkRef("state", "72", "Puerto Rico")
    assert opts.puerto_rico_note is not None
    assert "50 states and DC" in opts.puerto_rico_note


def test_a_mixed_input_with_one_pr_zip_still_gets_the_note() -> None:
    opts = profile.benchmark_options(["33602", "00601"], FACTS)
    assert opts.puerto_rico_note is not None


def test_no_recognized_zips_is_an_error() -> None:
    with pytest.raises(ValueError, match="no recognized"):
        profile.benchmark_options(["99999"], FACTS)
