"""Chart data: trade area vs benchmark as shares (SPEC 5.5, Appendix D)."""

from __future__ import annotations

import pytest
from synth_art import Z, make_artifacts

from zipographics import analysis as an
from zipographics import charts, lenses, metrics
from zipographics.models import UsePolicy
from zipographics.zips import parse_paste

OFF = UsePolicy(False, "Home services (HVAC, plumbing, roofing, pest, remodeling)", "No")
ON = UsePolicy(True, "Insurance", "Yes (set by industry)")
ART = make_artifacts({"33602": Z(5000, 2000, owner=0.4), "33606": Z(8000, 3500, owner=0.7)})


def run(policy: UsePolicy = OFF, **kw):  # type: ignore[no-untyped-def]
    return an.analyze(ART, parse_paste("33602 33606"), policy, **kw)


def test_every_chart_id_a_lens_names_has_a_definition() -> None:
    known = set(charts.CHARTS)
    for lens in lenses.LENSES:
        assert set(lens.all_charts) <= known, lens.name
    assert set(lenses.MORE_DEMOGRAPHICS_CHARTS) <= known


def test_chart_categories_are_registry_metrics_and_partition_where_they_should() -> None:
    for spec in charts.CHARTS.values():
        for mid in spec.metric_ids:
            assert metrics.BY_ID[mid].unit == "percent", (spec.id, mid)
    partitions = ["income", "age", "tenure", "housing_age", "units_in_structure",
                  "tenure_by_move_in", "vehicles_available", "race"]  # fmt: skip
    for cid in partitions:
        assert len(set(charts.CHARTS[cid].metric_ids)) == len(charts.CHARTS[cid].metric_ids)
    assert charts.CHARTS["income"].metric_ids == (
        "inc_lt25",
        "inc_25_50",
        "inc_50_75",
        "inc_75_100",
        "inc_100_150",
        "inc_150_200",
        "inc_200p",
    )
    assert (
        len(charts.CHARTS["age"].metric_ids) == 8
        and len(charts.CHARTS["housing_age"].metric_ids) == 4
    )


def test_the_income_chart_compares_the_trade_area_with_the_benchmark() -> None:
    a = run()
    d = charts.chart_data(a, "income")
    assert d.rows[0].label == "Under $25k" and d.rows[-1].label == "$200k+"
    assert sum(r.trade for r in d.rows if r.trade is not None) == pytest.approx(1.0, abs=0.02)
    assert sum(r.bench for r in d.rows if r.bench is not None) == pytest.approx(1.0, abs=0.02)
    assert d.title == "Household income" and d.benchmark_name == "Florida"
    assert all(r.trade_moe is not None for r in d.rows)


def test_tenure_is_owner_and_renter() -> None:
    d = charts.chart_data(run(), "tenure")
    assert [r.label for r in d.rows] == ["Owner-occupied", "Renter-occupied"]
    assert d.rows[0].trade + d.rows[1].trade == pytest.approx(1.0)  # type: ignore[operator]
    assert d.rows[0].trade == pytest.approx((0.4 * 2000 + 0.7 * 3500) / 5500, abs=0.002)
    assert d.rows[0].bench == pytest.approx(0.66)


def test_unknown_categories_are_none_not_zero() -> None:
    d = charts.chart_data(run(), "race")  # the synthetic data has no race cells
    assert all(r.trade is None and r.bench is None for r in d.rows)


def test_the_race_chart_says_hispanic_origin_is_separate() -> None:
    d = charts.chart_data(run(), "race")
    assert "Hispanic" in d.note and "any race" in d.note
    assert "separate" in charts.chart_data(run(), "hispanic").note


def test_move_in_labels_come_from_the_data_when_present() -> None:
    art = make_artifacts({"33602": Z(5000, 2000)})
    art.metadata["variables"] = {  # type: ignore[index]
        "B25038_003": {"label": "Estimate!!Total:!!Owner occupied:!!Moved in 2023 or later"},
        "B25038_004": {"label": "Estimate!!Total:!!Owner occupied:!!Moved in 2018 to 2022"},
        "B25038_005": {"label": "Estimate!!Total:!!Owner occupied:!!Moved in 2010 to 2017"},
        "B25038_006": {"label": "Estimate!!Total:!!Owner occupied:!!Moved in 2000 to 2009"},
        "B25038_007": {"label": "Estimate!!Total:!!Owner occupied:!!Moved in 1990 to 1999"},
        "B25038_008": {"label": "Estimate!!Total:!!Owner occupied:!!Moved in 1989 or earlier"},
    }
    a = an.analyze(art, parse_paste("33602"), OFF)
    labels = [r.label for r in charts.chart_data(a, "tenure_by_move_in").rows]
    assert labels[0] == "Moved in 2023 or later" and labels[1] == "Moved in 2018 to 2022"
    assert labels[-1] == "Moved in 1990 or earlier"  # the two oldest periods are combined


def test_move_in_labels_have_a_neutral_fallback() -> None:
    labels = [r.label for r in charts.chart_data(run(), "tenure_by_move_in").rows]
    assert labels[0] == "Most recent period" and len(labels) == 5


def test_a_lens_gets_its_core_and_own_charts() -> None:
    a = run(lens="Home services")
    ids = [d.id for d in charts.charts_for(a)]
    assert ids == ["income", "age", "tenure", "housing_age", "units_in_structure"]
    assert [d.id for d in charts.more_demographics(a)] == ["race", "hispanic"]


def test_restricted_mode_still_shows_the_context_charts() -> None:
    ids = [d.id for d in charts.charts_for(run(ON))]
    assert ids == ["income", "age", "tenure", "housing_age"]


def test_unknown_chart_is_an_error() -> None:
    with pytest.raises(ValueError, match="Unknown chart"):
        charts.chart_data(run(), "pie")


# ----------------------------------------------------------------------------- app rendering data
def test_the_long_frame_has_a_row_per_category_and_series() -> None:
    d = charts.chart_data(run(), "income")
    frame = charts.to_frame(d)
    assert len(frame) == 2 * len(d.rows)
    assert set(frame["Series"]) == {"Trade area", "Florida"}
    assert list(frame["Category"].unique()) == [r.label for r in d.rows]  # order kept


def test_unknown_shares_are_null_in_the_frame_not_zero() -> None:
    frame = charts.to_frame(charts.chart_data(run(), "race"))
    assert frame["Share"].isna().all()


def test_the_altair_chart_is_a_grouped_bar_with_a_colorblind_safe_palette() -> None:
    spec = charts.altair_chart(charts.chart_data(run(), "tenure")).to_dict()
    assert spec["mark"]["type"] == "bar" or spec["mark"] == "bar"
    enc = spec["encoding"]
    assert "yOffset" in enc and enc["x"]["axis"]["format"] == "%"
    assert enc["color"]["scale"]["range"][0] != enc["color"]["scale"]["range"][1]
    assert enc["y"]["sort"] == ["Owner-occupied", "Renter-occupied"]


def test_the_text_alternative_table_has_the_numbers() -> None:
    t = charts.table_frame(charts.chart_data(run(), "tenure"))
    assert list(t.columns) == ["Category", "Trade area", "Florida", "Margin of error"]
    assert t.loc[0, "Category"] == "Owner-occupied" and t.loc[0, "Florida"] == "66.0 %"
    race = charts.table_frame(charts.chart_data(run(), "race"))
    assert set(race["Trade area"]) == {"\N{EM DASH}"}
