"""The ranked-table view: strings, shading, toggles, restricted-mode guards (SPEC 5.5, 5.7)."""

from __future__ import annotations

import pytest
from synth_art import Z, make_artifacts

from zipographics import analysis as an
from zipographics import filters, metrics, table, ui, verticals
from zipographics.errors import RestrictedUseError
from zipographics.models import ParsedInput, Rule, UsePolicy
from zipographics.zips import parse_paste

OFF = verticals.make_policy("Retail (general & specialty)", False)
FORCED = verticals.make_policy("Insurance", None)
LIAR = UsePolicy(False, "Insurance", "No")
WORLD = {
    "02108": Z(3794, 1973, owner=0.51, kids=0.10, state="MA", county=("25025", "Suffolk County"),
              city="Boston", income=212_928),
    "33602": Z(5000, 2000, owner=0.40, kids=0.20),
    "33606": Z(8000, 3500, owner=0.70, kids=0.35, income=250_001, code="top"),
    "33603": Z(900, 280, owner=0.55, kids=0.30, extra={"B25003_002": (154.0, 200.0)}),
    "33604": Z(2500, 1200, owner=0.65, kids=0.25, income=None),
}  # fmt: skip
ART = make_artifacts(WORLD)
IDS = ["owner", "median_hh_income", "hh_kids"]


def run(policy=OFF, text="02108 33602 33606 33603 33604", **kw):  # type: ignore[no-untyped-def]
    return an.analyze(ART, parse_paste(text), policy, **kw)


def col(view: table.TableView, name: str) -> list[str]:
    return list(view.frame[name])


def test_the_default_columns_and_text_zips() -> None:
    v = table.build_view(run(), None, metric_ids=IDS)
    assert list(v.frame.columns) == [
        "ZIP", "City", "County", "State", "Population", "Households",
        "Homeowners", "Median household income", "Households with children",
    ]  # fmt: skip
    assert col(v, "ZIP") == ["02108", "33602", "33606", "33603", "33604"]  # leading zero kept
    assert col(v, "City")[0] == "Boston" and col(v, "Population")[1] == "5,000"
    assert v.zips == run().zips


def test_values_use_the_display_formats_and_coded_medians_show_their_bound() -> None:
    v = table.build_view(run(), None, metric_ids=IDS)
    assert col(v, "Median household income") == [
        "$212,928",
        "$60,000",
        "$250,000+",
        "$60,000",
        ui.DASH,
    ]
    assert col(v, "Homeowners")[1] == "40.0 %"


def test_an_unreliable_value_gets_a_dagger_and_grey_italics_a_cautious_one_muted_text() -> None:
    v = table.build_view(run(), None, metric_ids=IDS)
    own = col(v, "Homeowners")
    assert own[3].endswith(ui.DAGGER)  # 33603's share is unreliable
    assert "italic" in v.styles.loc[3, "Homeowners"]
    assert (
        "color" in v.styles.loc[2, "Median household income"]
        and ui.DAGGER not in col(v, "Median household income")[2]
    )  # a coded median is "use with caution": muted, no dagger
    assert v.styles.loc[1, "Homeowners"] == ""  # a reliable cell is unstyled


def test_the_margin_of_error_toggle_adds_a_column_per_metric() -> None:
    v = table.build_view(run(), None, metric_ids=IDS, show_moe=True)
    assert "Homeowners ±" in v.frame.columns
    assert col(v, "Homeowners ±")[1].startswith("±") or col(v, "Homeowners ±")[1] == ""
    assert col(v, "Median household income ±")[2] == ""  # coded: no margin of error


def test_the_index_toggle_shows_the_index_for_indexable_metrics_and_values_for_counts() -> None:
    v = table.build_view(run(), None, metric_ids=["owner", "pop"], index=True)
    assert "Homeowners (index)" in v.frame.columns and "Population" in v.frame.columns
    assert col(v, "Homeowners (index)")[1] == "61"  # 40 % against Florida's 66 %
    assert col(v, "Population")[1] == "5,000"


def test_sorting_follows_table_order() -> None:
    v = table.build_view(run(), None, metric_ids=IDS, sort="owner", descending=True)
    assert v.zips[0] == "33606" and col(v, "ZIP")[0] == "33606"
    assert table.build_view(run(), None, metric_ids=IDS, sort="zip").zips[0] == "02108"


def test_filter_matches_are_marked_and_can_be_shown_alone() -> None:
    a = run()
    r = filters.apply(a, [Rule("owner", ">=", 0.6)])
    v = table.build_view(a, r, metric_ids=IDS)
    assert "Matches" in v.frame.columns
    assert dict(zip(col(v, "ZIP"), col(v, "Matches"), strict=True)) == {
        "02108": "", "33602": "", "33606": "\N{CHECK MARK}", "33603": "", "33604": "\N{CHECK MARK}",
    }  # fmt: skip
    assert "font-weight" in v.styles.loc[2, "ZIP"]
    only = table.build_view(a, r, metric_ids=IDS, only_matching=True)
    assert only.zips == ("33606", "33604") and col(only, "ZIP") == ["33606", "33604"]


def test_no_active_filter_means_no_matches_column() -> None:
    a = run()
    assert "Matches" not in table.build_view(a, filters.apply(a, []), metric_ids=IDS).frame.columns
    assert table.build_view(a, None, metric_ids=IDS, only_matching=True).zips == a.zips


def test_in_radius_columns_for_zipcator_input() -> None:
    parsed = ParsedInput(
        zips=("33602", "33606"),
        overlaps={"33602": 50.0},
        blank_overlap=("33606",),
        source="zipcator",
    )
    a = an.analyze(ART, parsed, OFF)
    v = table.build_view(a, None, metric_ids=["owner"])
    assert col(v, "Overlap %") == ["50", "100"]
    assert col(v, "In-radius households") == ["1,000", "3,500"]


def test_column_help_explains_each_metric() -> None:
    v = table.build_view(run(), None, metric_ids=IDS)
    assert v.help.get("Homeowners")
    assert "ZIP" in v.help


def test_the_unreliable_cells_are_listed_with_their_numbers() -> None:
    cells = table.unreliable_cells(run(), IDS)
    owner = next(c for c in cells if c.zip == "33603" and c.metric_id == "owner")
    assert owner.estimate == "55.0 %" and owner.moe and owner.cv and owner.cv > 30
    assert all(c.zip != "33602" for c in cells if c.metric_id == "owner")


# ----------------------------------------------------------------------------- restricted mode
@pytest.mark.parametrize("policy", [FORCED, LIAR])
def test_restricted_mode_has_no_index_toggle_no_sort_by_metric_no_filtering(policy) -> None:  # type: ignore[no-untyped-def]
    a = run(policy)
    with pytest.raises(RestrictedUseError):
        table.build_view(a, None, metric_ids=IDS, index=True)
    for key in [m.id for m in metrics.REGISTRY]:
        with pytest.raises(RestrictedUseError):
            table.build_view(a, None, metric_ids=IDS, sort=key)
    result = filters.apply(run(OFF), [Rule("owner", ">=", 0.5)])
    with pytest.raises(RestrictedUseError):
        table.build_view(a, result, metric_ids=IDS)
    with pytest.raises(RestrictedUseError):
        table.build_view(a, result, metric_ids=IDS, only_matching=True)


@pytest.mark.parametrize("policy", [FORCED, LIAR])
def test_restricted_mode_shows_values_and_margins_in_input_or_zip_order(policy) -> None:  # type: ignore[no-untyped-def]
    a = run(policy)
    v = table.build_view(a, None, metric_ids=IDS, show_moe=True)
    assert col(v, "ZIP") == list(a.zips) and "Homeowners (index)" not in v.frame.columns
    assert "Matches" not in v.frame.columns
    assert col(table.build_view(a, None, metric_ids=IDS, sort="zip"), "ZIP")[0] == "02108"
    assert (
        col(table.build_view(a, None, metric_ids=IDS, sort="zip", descending=True), "ZIP")[0]
        == "33606"
    )


def test_unknown_metric_ids_are_rejected() -> None:
    with pytest.raises(ValueError, match="Unknown metric"):
        table.build_view(run(), None, metric_ids=["nope"])


def test_overlaps_in_the_table_are_rounded_for_display() -> None:
    parsed = ParsedInput(
        zips=("33602", "33606"),
        overlaps={"33602": 96.0737},
        blank_overlap=("33606",),
        source="zipcator",
    )
    v = table.build_view(an.analyze(ART, parsed, OFF), None, metric_ids=["owner"])
    assert col(v, "Overlap %") == ["96.1", "100"]


def test_duplicate_metric_ids_are_rejected_not_a_styler_crash() -> None:
    with pytest.raises(ValueError, match="twice"):
        table.build_view(run(), None, metric_ids=["owner", "owner"])
