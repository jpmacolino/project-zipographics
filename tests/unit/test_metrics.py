"""Tests for zipographics.metrics: the registry matches SPEC Appendix B/C (SPEC §4.2, §9.2)."""

from __future__ import annotations

import itertools
import math
import re

import pytest

from zipographics import metrics as m

# Transcribed from SPEC Appendix C (id -> (kind, tag)); Appendix B gives the tag meanings.
EXPECTED: dict[str, tuple[str, str | None]] = {
    "pop": ("count", None),
    "hh": ("count", None),
    "units": ("count", None),
    "vacancy": ("share", None),
    **{
        k: ("share", "age")
        for k in [
            "age_0_17",
            "age_18_24",
            "age_25_34",
            "age_35_44",
            "age_45_54",
            "age_55_64",
            "age_65_74",
            "age_75p",
            "age_18_34",
            "age_18_44",
            "age_65p",
        ]
    },
    "age_0_4": ("share", "familial_status"),
    "age_5_17": ("share", "familial_status"),
    "median_age": ("median", "age"),
    "hh_kids": ("share", "familial_status"),
    "working_parents_u6": ("share", "familial_status"),
    **{
        k: ("share", "income")
        for k in [
            "inc_lt25",
            "inc_25_50",
            "inc_50_75",
            "inc_75_100",
            "inc_100_150",
            "inc_150_200",
            "inc_200p",
            "inc_75p",
            "inc_100p",
            "inc_150p",
        ]
    },
    "median_hh_income": ("median", "income"),
    "mean_hh_income": ("mean", "income"),
    "per_capita_income": ("mean", "income"),
    "poverty": ("share", "income"),
    "owner": ("share", "proxy_other"),
    "renter": ("share", "proxy_other"),
    "median_value": ("median", "proxy_other"),
    "median_rent": ("median", "proxy_other"),
    **{
        k: ("share", "proxy_other")
        for k in [
            "built_2010p",
            "built_1980_2009",
            "built_1960_1979",
            "built_pre1960",
            "built_pre1980",
        ]
    },
    "median_year_built": ("median", "proxy_other"),
    "single_family": ("share", "proxy_other"),
    "mobile_home": ("share", "proxy_other"),
    "new_movers": ("share", "proxy_other"),
    "veh_per_hh": ("ratio", "proxy_other"),
    "veh_0": ("share", "proxy_other"),
    "veh_2p": ("share", "proxy_other"),
    **{
        k: ("share", "proxy_other")
        for k in [
            "commute_drive_alone",
            "commute_carpool",
            "commute_transit",
            "commute_walk_bike",
            "wfh",
            "commute_30p",
            "lfpr",
            "unemployment",
            "hs_plus",
            "ba_plus",
            "grad",
        ]
    },
    "spanish_home": ("share", "national_origin"),
    "limited_english": ("share", "national_origin"),
    "hispanic": ("share", "national_origin"),
    **{
        k: ("share", "race_color")
        for k in [
            "race_white",
            "race_black",
            "race_aian",
            "race_asian",
            "race_nhpi",
            "race_other",
            "race_two_plus",
        ]
    },
    "broadband": ("share", "proxy_other"),
    "no_internet": ("share", "proxy_other"),
    "uninsured": ("share", "proxy_other"),
}

PUBLISHED_MEDIANS = {"B19013_001", "B25077_001", "B25064_001", "B01002_001", "B25035_001"}


def test_the_registry_has_exactly_the_appendix_c_metrics() -> None:
    ids = [x.id for x in m.REGISTRY]
    assert len(ids) == len(set(ids)), "duplicate metric id"
    assert set(ids) == set(EXPECTED)
    assert len(ids) == 74  # counted from the Appendix C table


def test_kinds_and_tags_match_appendices_b_and_c() -> None:
    for metric in m.REGISTRY:
        kind, tag = EXPECTED[metric.id]
        assert metric.kind == kind, metric.id
        assert metric.characteristic == tag, metric.id


def test_every_metric_has_a_decision_about_its_tag() -> None:
    # a metric added without a tag decision fails here (SPEC §9.2)
    allowed = {
        None,
        "race_color",
        "national_origin",
        "familial_status",
        "age",
        "income",
        "proxy_other",
    }
    assert {x.characteristic for x in m.REGISTRY} <= allowed
    assert all(hasattr(x, "characteristic") for x in m.REGISTRY)


def test_only_counts_are_not_indexable() -> None:
    for metric in m.REGISTRY:
        assert metric.indexable == (metric.kind != "count"), metric.id


def test_text_fields_are_filled_in() -> None:
    for metric in m.REGISTRY:
        assert metric.name.strip(), metric.id
        assert metric.universe.strip(), metric.id
        assert len(metric.help) >= 15, metric.id
        assert metric.unit in {"count", "percent", "dollars", "years", "year", "ratio"}, metric.id


def test_units_follow_the_kind() -> None:
    for metric in m.REGISTRY:
        if metric.kind == "share":
            assert metric.unit == "percent", metric.id
        if metric.kind == "count":
            assert metric.unit == "count", metric.id
    assert m.BY_ID["median_hh_income"].unit == "dollars"
    assert m.BY_ID["median_age"].unit == "years"
    assert m.BY_ID["median_year_built"].unit == "year"
    assert m.BY_ID["veh_per_hh"].unit == "ratio"


def test_every_referenced_variable_is_defined_and_none_is_orphaned() -> None:
    used = set()
    for metric in m.REGISTRY:
        used |= set(m.variable_keys(metric))
    assert used <= set(m.VARIABLES), sorted(used - set(m.VARIABLES))
    assert set(m.VARIABLES) <= used, sorted(set(m.VARIABLES) - used)


def test_published_medians_are_flagged_so_their_annotations_are_fetched() -> None:
    flagged = {k for k, v in m.VARIABLES.items() if v.is_median}
    assert flagged == PUBLISHED_MEDIANS


def test_variable_keys_are_census_ids_or_resolved_by_label() -> None:
    by_label = [v for v in m.VARIABLES.values() if v.resolve == "label"]
    assert by_label, "the Data Profile items are resolved by label"
    for v in m.VARIABLES.values():
        if v.resolve == "id":
            assert re.fullmatch(r"[BC]\d{5}_\d{3}", v.key), v.key
            assert v.table == v.key.split("_")[0]
        else:
            assert v.table.startswith("DP03") and v.label, v.key
            assert v.dataset == "profile"


def test_registry_variable_count_is_in_the_expected_range() -> None:
    # one request carries at most 50 names; the build chunks these (SPEC §4.5)
    assert 200 < len(m.VARIABLES) < 400


def test_tables_in_use_match_spec_4_2() -> None:
    tables = {v.table for v in m.VARIABLES.values()}
    expected = {
        "B01003",
        "B01001",
        "B01002",
        "B11001",
        "B11005",
        "DP03",
        "B19001",
        "B19013",
        "B19025",
        "B19301",
        "B17001",
        "B25001",
        "B25002",
        "B25003",
        "B25024",
        "B25034",
        "B25035",
        "B25038",
        "B25044",
        "B25046",
        "B25063",
        "B25064",
        "B25075",
        "B25077",
        "B08301",
        "B08303",
        "B23025",
        "B15003",
        "C16001",
        "B03003",
        "B02001",
        "B28002",
    }
    assert tables == expected


# ----------------------------------------------------------------------- brackets
EXPECTED_BRACKET_COUNTS = {
    "median_hh_income": 16,
    "median_value": 26,
    "median_rent": 24,
    "median_year_built": 10,
    "median_age": 23,
}


@pytest.mark.parametrize("metric_id", sorted(EXPECTED_BRACKET_COUNTS))
def test_median_brackets_are_ordered_contiguous_and_complete(metric_id: str) -> None:
    spec = m.BY_ID[metric_id].spec
    assert isinstance(spec, m.MedianSpec)
    brackets = spec.brackets
    assert len(brackets) == EXPECTED_BRACKET_COUNTS[metric_id]
    for a, b in itertools.pairwise(brackets):
        assert a.hi == b.lo, (metric_id, a, b)  # contiguous and ascending
    assert math.isinf(brackets[-1].hi)  # every distribution has an open top bracket
    all_keys = [k for b in brackets for k in b.keys]
    assert len(all_keys) == len(set(all_keys))
    assert spec.published in m.VARIABLES


def test_income_brackets_match_b19001() -> None:
    spec = m.BY_ID["median_hh_income"].spec
    assert isinstance(spec, m.MedianSpec)
    bounds = [(b.lo, b.hi) for b in spec.brackets]
    assert bounds[0] == (0, 10_000)  # open lowest bracket uses 0 (SPEC §6.4 assumption)
    assert bounds[9] == (50_000, 60_000)
    assert bounds[10] == (60_000, 75_000)
    assert bounds[-1] == (200_000, math.inf)
    assert [b.keys[0] for b in spec.brackets] == [f"B19001_{n:03d}" for n in range(2, 18)]


def test_rent_brackets_exclude_no_cash_rent_and_with_cash_rent() -> None:
    spec = m.BY_ID["median_rent"].spec
    assert isinstance(spec, m.MedianSpec)
    keys = [b.keys[0] for b in spec.brackets]
    assert keys == [f"B25063_{n:03d}" for n in range(3, 27)]
    assert "B25063_027" not in keys and "B25063_002" not in keys


def test_age_brackets_sum_male_and_female_cells() -> None:
    spec = m.BY_ID["median_age"].spec
    assert isinstance(spec, m.MedianSpec)
    first, last = spec.brackets[0], spec.brackets[-1]
    assert first.keys == ("B01001_003", "B01001_027") and (first.lo, first.hi) == (0, 5)
    assert last.keys == ("B01001_025", "B01001_049") and (last.lo, last.hi) == (85, math.inf)


def test_year_built_brackets_run_oldest_to_newest_with_open_ends() -> None:
    spec = m.BY_ID["median_year_built"].spec
    assert isinstance(spec, m.MedianSpec)
    assert spec.brackets[0].lo == -math.inf and spec.brackets[0].hi == 1940
    assert spec.brackets[0].keys == ("B25034_011",)
    assert spec.brackets[-1].lo == 2020 and math.isinf(spec.brackets[-1].hi)


# ----------------------------------------------------------------------- shares
def test_age_bands_cover_every_age_exactly_once() -> None:
    cells: list[str] = []
    for mid in [
        "age_0_17",
        "age_18_24",
        "age_25_34",
        "age_35_44",
        "age_45_54",
        "age_55_64",
        "age_65_74",
        "age_75p",
    ]:
        spec = m.BY_ID[mid].spec
        assert isinstance(spec, m.ShareSpec)
        cells += spec.num
    male_and_female = [f"B01001_{n:03d}" for n in [*range(3, 26), *range(27, 50)]]
    assert sorted(cells) == sorted(male_and_female)


def test_derived_age_groups_are_unions_of_the_bands() -> None:
    def cells(mid: str) -> set[str]:
        spec = m.BY_ID[mid].spec
        assert isinstance(spec, m.ShareSpec)
        return set(spec.num)

    assert cells("age_18_34") == cells("age_18_24") | cells("age_25_34")
    assert cells("age_18_44") == cells("age_18_34") | cells("age_35_44")
    assert cells("age_65p") == cells("age_65_74") | cells("age_75p")
    assert cells("age_0_4") | cells("age_5_17") == cells("age_0_17")
    assert cells("age_0_4").isdisjoint(cells("age_5_17"))


def test_income_bands_cover_all_sixteen_brackets_once() -> None:
    cells: list[str] = []
    for mid in [
        "inc_lt25",
        "inc_25_50",
        "inc_50_75",
        "inc_75_100",
        "inc_100_150",
        "inc_150_200",
        "inc_200p",
    ]:
        spec = m.BY_ID[mid].spec
        assert isinstance(spec, m.ShareSpec)
        cells += spec.num
    assert sorted(cells) == [f"B19001_{n:03d}" for n in range(2, 18)]
    p75 = m.BY_ID["inc_75p"].spec
    assert isinstance(p75, m.ShareSpec) and p75.num == tuple(
        f"B19001_{n:03d}" for n in range(13, 18)
    )


def test_housing_age_bands_partition_the_units() -> None:
    cells: list[str] = []
    for mid in ["built_2010p", "built_1980_2009", "built_1960_1979", "built_pre1960"]:
        spec = m.BY_ID[mid].spec
        assert isinstance(spec, m.ShareSpec)
        cells += spec.num
    assert sorted(cells) == [f"B25034_{n:03d}" for n in range(2, 12)]
    pre80 = m.BY_ID["built_pre1980"].spec
    assert isinstance(pre80, m.ShareSpec)
    assert pre80.num == tuple(f"B25034_{n:03d}" for n in range(7, 12))  # 1970-79 and older


def test_race_shares_partition_the_population() -> None:
    cells: list[str] = []
    for mid in [
        "race_white",
        "race_black",
        "race_aian",
        "race_asian",
        "race_nhpi",
        "race_other",
        "race_two_plus",
    ]:
        spec = m.BY_ID[mid].spec
        assert isinstance(spec, m.ShareSpec)
        assert spec.den == ("B02001_001",)
        cells += spec.num
    assert sorted(cells) == [f"B02001_{n:03d}" for n in range(2, 9)]


def test_vehicles_per_household_uses_the_aggregate_vehicles_table() -> None:
    # B25046 (aggregate vehicles) is at ZCTA level (Phase 4 check), so SPEC §6.5 prefers it
    # to counting B25044's "5 or more" as 5: the result is exact, not an "at least"
    spec = m.BY_ID["veh_per_hh"].spec
    assert isinstance(spec, m.RatioSpec)
    assert spec.num == (("B25046_001", 1.0),)
    assert spec.den == ("B25044_001",)
    assert "aggregate" in m.BY_ID["veh_per_hh"].help.lower()
    assert "B25044_004" not in m.VARIABLES and "B25044_011" not in m.VARIABLES  # no longer needed


def test_mean_incomes() -> None:
    mean = m.BY_ID["mean_hh_income"].spec
    assert isinstance(mean, m.RatioSpec)
    assert mean.num == (("B19025_001", 1.0),) and mean.den == ("B11001_001",)
    pc = m.BY_ID["per_capita_income"].spec
    assert isinstance(pc, m.ProductMeanSpec)
    assert (pc.rate, pc.base) == ("B19301_001", "B01003_001")


def test_data_profile_items_are_resolved_by_label() -> None:
    wp = m.BY_ID["working_parents_u6"].spec
    un = m.BY_ID["uninsured"].spec
    assert isinstance(wp, m.ShareSpec) and isinstance(un, m.ShareSpec)
    for key in (*wp.num, *wp.den, *un.num, *un.den):
        assert m.VARIABLES[key].resolve == "label"
