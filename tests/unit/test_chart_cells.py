"""The registry holds every cell the Appendix D lens charts need (Phase 4 QA, DECISIONS B17).

SPEC §4.3 stores registry variables only, so "units in structure", "tenure by move-in" and
"vehicles available" need their cells in the registry. Each group of metrics must partition its
universe exactly once.
"""

from __future__ import annotations

import pytest

from zipographics import metrics as m


def num(metric_id: str) -> tuple[str, ...]:
    spec = m.BY_ID[metric_id].spec
    assert isinstance(spec, m.ShareSpec)
    return spec.num


def den(metric_id: str) -> tuple[str, ...]:
    spec = m.BY_ID[metric_id].spec
    assert isinstance(spec, m.ShareSpec)
    return spec.den


def cells(table: str, *rows: int) -> list[str]:
    return [f"{table}_{n:03d}" for n in rows]


UNITS = ["single_family", "units_2_4", "units_5_19", "units_20p", "mobile_home", "units_other"]
MOVERS = ["new_movers", "movers_2", "movers_3", "movers_4", "movers_older"]
VEHICLES = ["veh_0", "veh_1", "veh_2", "veh_3p"]


@pytest.mark.parametrize(
    ("ids", "table", "rows"),
    [
        (UNITS, "B25024", range(2, 12)),
        (MOVERS, "B25038", [*range(3, 9), *range(10, 16)]),
        (VEHICLES, "B25044", [3, *range(4, 9), 10, *range(11, 16)]),
    ],
)
def test_each_chart_group_partitions_its_table_exactly_once(
    ids: list[str], table: str, rows: object
) -> None:
    used = [c for i in ids for c in num(i)]
    assert sorted(used) == sorted(cells(table, *rows))  # every cell once, none twice, none missing
    assert len({den(i) for i in ids}) == 1  # one common denominator


def test_the_specific_buckets() -> None:
    assert num("units_2_4") == tuple(cells("B25024", 4, 5))
    assert num("units_5_19") == tuple(cells("B25024", 6, 7))
    assert num("units_20p") == tuple(cells("B25024", 8, 9))
    assert num("units_other") == ("B25024_011",)
    assert num("movers_2") == tuple(cells("B25038", 4, 11))  # owner and renter, same period
    assert num("movers_older") == tuple(cells("B25038", 7, 8, 14, 15))
    assert num("veh_1") == tuple(cells("B25044", 4, 11))
    assert num("veh_2") == tuple(cells("B25044", 5, 12))
    assert num("veh_3p") == tuple(cells("B25044", 6, 7, 8, 13, 14, 15))


def test_the_new_metrics_are_ordinary_shares_with_a_tag() -> None:
    for mid in ["units_2_4", "units_5_19", "units_20p", "units_other", "movers_2", "movers_3",
                "movers_4", "movers_older", "veh_1", "veh_2", "veh_3p"]:  # fmt: skip
        metric = m.BY_ID[mid]
        assert metric.kind == "share" and metric.unit == "percent"
        assert metric.characteristic == "proxy_other"
        assert metric.indexable


def test_movers_say_that_their_period_labels_come_from_the_data() -> None:
    # the ACS shifts these periods every vintage ("moved in 2021 or later", then "2023 or later");
    # the registry names them by recency and the UI shows the label stored in metadata.json
    assert "label" in m.BY_ID["new_movers"].help.lower()
    assert "most recent" in m.BY_ID["new_movers"].name.lower()


def test_vehicles_per_household_is_the_b25044_weighted_count_labeled_at_least() -> None:
    # B25046 (aggregate vehicles) exists at ZCTA level but is only 86 % non-null (a miscounting
    # live test once said 97 %); B25044 is complete, so SPEC §6.5's fallback is the better product
    spec = m.BY_ID["veh_per_hh"].spec
    assert isinstance(spec, m.RatioSpec)
    weights = dict(spec.num)
    assert weights["B25044_004"] == 1 and weights["B25044_011"] == 1
    assert weights["B25044_005"] == 2 and weights["B25044_008"] == 5  # "5 or more" counts as 5
    assert weights["B25044_012"] == 2 and weights["B25044_015"] == 5
    assert "B25044_003" not in weights and "B25044_010" not in weights  # no vehicle adds 0
    assert spec.den == ("B25044_001",)
    assert "at least" in m.BY_ID["veh_per_hh"].help.lower()
    assert "B25046_001" not in m.VARIABLES
