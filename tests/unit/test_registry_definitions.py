"""Table-driven registry checks from the Phase 2 QA review (MEDIUM 3): every cell is pinned.

The expectations below are transcribed from the ACS table layouts, not read from the registry,
so changing a cell range in `metrics.py` fails here.
"""

from __future__ import annotations

import re

import pytest

from zipographics import metrics as m


def c(table: str, *rows: int) -> list[str]:
    return [f"{table}_{n:03d}" for n in rows]


def rng(table: str, lo: int, hi: int) -> list[str]:
    return c(table, *range(lo, hi + 1))


INC = "B19001_001"
EXPECTED_SHARES: dict[str, tuple[list[str], list[str]]] = {
    "vacancy": (c("B25002", 3), c("B25002", 1)),
    "hh_kids": (c("B11005", 2), c("B11005", 1)),
    "poverty": (c("B17001", 2), c("B17001", 1)),
    "owner": (c("B25003", 2), c("B25003", 1)),
    "renter": (c("B25003", 3), c("B25003", 1)),
    "single_family": (c("B25024", 2, 3), c("B25024", 1)),
    "mobile_home": (c("B25024", 10), c("B25024", 1)),
    "new_movers": (c("B25038", 3, 10), c("B25038", 1)),
    "veh_0": (c("B25044", 3, 10), c("B25044", 1)),
    "veh_2p": (c("B25044", 5, 6, 7, 8, 12, 13, 14, 15), c("B25044", 1)),
    "commute_drive_alone": (c("B08301", 3), c("B08301", 1)),
    "commute_carpool": (c("B08301", 4), c("B08301", 1)),
    "commute_transit": (c("B08301", 10), c("B08301", 1)),
    "commute_walk_bike": (c("B08301", 18, 19), c("B08301", 1)),
    "wfh": (c("B08301", 21), c("B08301", 1)),
    "commute_30p": (rng("B08303", 8, 13), c("B08303", 1)),
    "lfpr": (c("B23025", 2), c("B23025", 1)),
    "unemployment": (c("B23025", 5), c("B23025", 3)),
    "hs_plus": (rng("B15003", 17, 25), c("B15003", 1)),
    "ba_plus": (rng("B15003", 22, 25), c("B15003", 1)),
    "grad": (rng("B15003", 23, 25), c("B15003", 1)),
    "spanish_home": (c("C16001", 3), c("C16001", 1)),
    "limited_english": (c("C16001", *range(5, 39, 3)), c("C16001", 1)),
    "hispanic": (c("B03003", 3), c("B03003", 1)),
    "broadband": (c("B28002", 4), c("B28002", 1)),
    "no_internet": (c("B28002", 13), c("B28002", 1)),
    "race_white": (c("B02001", 2), c("B02001", 1)),
    "race_black": (c("B02001", 3), c("B02001", 1)),
    "race_aian": (c("B02001", 4), c("B02001", 1)),
    "race_asian": (c("B02001", 5), c("B02001", 1)),
    "race_nhpi": (c("B02001", 6), c("B02001", 1)),
    "race_other": (c("B02001", 7), c("B02001", 1)),
    "race_two_plus": (c("B02001", 8), c("B02001", 1)),
    "inc_lt25": (rng("B19001", 2, 5), [INC]),
    "inc_25_50": (rng("B19001", 6, 10), [INC]),
    "inc_50_75": (rng("B19001", 11, 12), [INC]),
    "inc_75_100": (c("B19001", 13), [INC]),
    "inc_100_150": (rng("B19001", 14, 15), [INC]),
    "inc_150_200": (c("B19001", 16), [INC]),
    "inc_200p": (c("B19001", 17), [INC]),
    "inc_75p": (rng("B19001", 13, 17), [INC]),
    "inc_100p": (rng("B19001", 14, 17), [INC]),
    "inc_150p": (rng("B19001", 16, 17), [INC]),
    "built_2010p": (c("B25034", 2, 3), c("B25034", 1)),
    "built_1980_2009": (c("B25034", 4, 5, 6), c("B25034", 1)),
    "built_1960_1979": (c("B25034", 7, 8), c("B25034", 1)),
    "built_pre1960": (c("B25034", 9, 10, 11), c("B25034", 1)),
    "built_pre1980": (rng("B25034", 7, 11), c("B25034", 1)),
    "age_0_4": (c("B01001", 3, 27), c("B01001", 1)),
    "age_5_17": (c("B01001", 4, 5, 6, 28, 29, 30), c("B01001", 1)),
    "age_65p": (c("B01001", *range(20, 26), *range(44, 50)), c("B01001", 1)),
}


@pytest.mark.parametrize("metric_id", sorted(EXPECTED_SHARES))
def test_share_numerator_and_denominator_cells(metric_id: str) -> None:
    spec = m.BY_ID[metric_id].spec
    assert isinstance(spec, m.ShareSpec)
    num, den = EXPECTED_SHARES[metric_id]
    assert sorted(spec.num) == sorted(num), metric_id
    assert sorted(spec.den) == sorted(den), metric_id


# ----------------------------------------------------------------------------- label guard
def bracket_cells() -> set[str]:
    cells: set[str] = set()
    for metric in m.REGISTRY:
        if isinstance(metric.spec, m.MedianSpec):
            cells |= {k for b in metric.spec.brackets for k in b.keys}
    return cells


def test_every_single_cell_carries_a_label_pattern() -> None:
    # bracket cells are verified by their parsed bounds; every other variable needs a label regex
    cells = bracket_cells()
    unlabeled = [k for k, v in m.VARIABLES.items() if v.label is None and k not in cells]
    assert unlabeled == []
    for var in m.VARIABLES.values():
        if var.label is not None:
            re.compile(var.label)


SAMPLE_LABELS = {
    "B25002_003": "Estimate!!Total:!!Vacant",
    "B25003_002": "Estimate!!Total:!!Owner occupied",
    "B23025_005": "Estimate!!Total:!!In labor force:!!Civilian labor force:!!Unemployed",
    "B23025_003": "Estimate!!Total:!!In labor force:!!Civilian labor force:",
    "B08303_008": "Estimate!!Total:!!30 to 34 minutes",
    "B15003_022": "Estimate!!Total:!!Bachelor's degree",
    "B02001_005": "Estimate!!Total:!!Asian alone",
    "B28002_013": "Estimate!!Total:!!No Internet access",
    "B28002_004": "Estimate!!Total:!!With an Internet subscription:!!Broadband of any type",
    "C16001_003": "Estimate!!Total:!!Spanish:",
    "B03003_003": "Estimate!!Total:!!Hispanic or Latino",
    "B25044_005": "Estimate!!Total:!!Owner occupied:!!2 vehicles available",
    "B25044_012": "Estimate!!Total:!!Renter occupied:!!2 vehicles available",
    "B25046_001": "Estimate!!Aggregate number of vehicles available:",
    "B08301_021": "Estimate!!Total:!!Worked from home",
    "B01003_001": "Estimate!!Total",
}


@pytest.mark.parametrize(("key", "label"), sorted(SAMPLE_LABELS.items()))
def test_label_patterns_match_a_realistic_acs_label(key: str, label: str) -> None:
    pattern = m.VARIABLES[key].label
    assert pattern is not None
    assert re.search(pattern, label, re.IGNORECASE), (key, pattern)


@pytest.mark.parametrize(
    ("key", "wrong"),
    [
        ("B25002_003", "Estimate!!Total:!!Occupied"),
        ("B25003_002", "Estimate!!Total:!!Renter occupied"),
        ("B28002_013", "Estimate!!Total:!!With an Internet subscription:!!Broadband of any type"),
        ("B25044_005", "Estimate!!Total:!!Renter occupied:!!2 vehicles available"),
        ("B25046_001", "Estimate!!Aggregate number of vehicles available:!!Owner occupied"),
        ("B23025_005", "Estimate!!Total:!!In labor force:!!Civilian labor force:!!Employed"),
    ],
)
def test_label_patterns_reject_the_neighbouring_cell(key: str, wrong: str) -> None:
    pattern = m.VARIABLES[key].label
    assert pattern is not None
    assert not re.search(pattern, wrong, re.IGNORECASE), (key, pattern)


def test_data_profile_patterns_only_match_estimate_labels() -> None:
    # QA LOW 8: DP variables also have Percent!!, Margin of Error!! and Percent Margin of Error!!
    # labels with the same tail; the pattern must be anchored to the Estimate!! form
    for key, var in m.VARIABLES.items():
        if var.resolve != "label":
            continue
        assert var.label is not None and var.label.startswith("^estimate!!"), key
        tail = var.label.removeprefix("^estimate!!")
        sample = tail.replace(".*", " x ").rstrip("$").replace("\\", "")
        for prefix in ("Percent!!", "Margin of Error!!", "Percent Margin of Error!!"):
            assert not re.search(var.label, prefix + sample, re.IGNORECASE), (key, prefix)
