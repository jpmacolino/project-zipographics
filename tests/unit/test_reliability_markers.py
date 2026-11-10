"""Use-with-caution gets a non-colour marker (DECISIONS P14) and the filter summary follows the
In-radius / Full toggle (P15)."""

from __future__ import annotations

from datetime import UTC, datetime

import geopandas as gpd
import pytest
from shapely.geometry import box
from synth_art import Z, make_artifacts

from zipographics import analysis as an
from zipographics import filters, kpis, mapview, report, table, ui, verticals
from zipographics.models import ParsedInput, Rule
from zipographics.zips import parse_paste

OFF = verticals.make_policy("Retail (general & specialty)", False)
NOW = datetime(2026, 11, 10, 14, 30, tzinfo=UTC)
#: owner share 50 % with a margin that puts its CV at about 18 %: "use with caution"
CAUTION = {"B25003_002": (500.0, 150.0), "B25003_001": (1000.0, 50.0)}
WORLD = {
    "33602": Z(3000, 1000, owner=0.5, extra=CAUTION),
    "33606": Z(8000, 3500, owner=0.70),
    "33603": Z(900, 280, owner=0.55, extra={"B25003_002": (154.0, 200.0)}),  # unreliable
    "33605": Z(4000, 1500, income=250_001, code="top"),  # a coded median
}
ART = make_artifacts(WORLD)
GEO = gpd.GeoDataFrame(
    {"zip": list(WORLD)},
    geometry=[box(-82.5 + 0.1 * i, 27.9, -82.4 + 0.1 * i, 28.0) for i in range(4)],
    crs="EPSG:4326",
)


def run(text: str = "33602 33606 33603 33605", **kw):  # type: ignore[no-untyped-def]
    return an.analyze(ART, parse_paste(text), OFF, project_name="x", **kw)


def test_the_marker_table() -> None:
    assert ui.TIER_MARK == {"good": "", "caution": "~", "unreliable": "\N{DAGGER}"}
    assert ui.marker_for("caution") == "~" and ui.marker_for("unreliable") == "\N{DAGGER}"
    assert ui.marker_for("good") == ""
    assert ui.marker_for("caution", coded=True) == ""  # a coded median already says it is a bound
    assert ui.marker_for("unreliable", known=False) == ""  # an unknown value is a dash


def test_the_example_zip_really_is_use_with_caution() -> None:
    a = run()
    assert a.value("33602", "owner").tier == "caution"
    assert a.value("33603", "owner").tier == "unreliable"
    assert a.value("33606", "owner").tier == "good"


def test_the_table_marks_caution_with_a_tilde_and_unreliable_with_a_dagger() -> None:
    v = table.build_view(run(), None, metric_ids=["owner", "median_hh_income"])
    cells = dict(zip(v.frame["ZIP"], v.frame["Homeowners"], strict=True))
    assert cells["33602"] == "50.0 % ~"
    assert cells["33603"].endswith("\N{DAGGER}") and "~" not in cells["33603"]
    assert cells["33606"] == "70.0 %"  # reliable: no marker
    income = dict(zip(v.frame["ZIP"], v.frame["Median household income"], strict=True))
    assert income["33605"] == "$250,000+"  # coded: no tilde


def test_the_index_columns_are_marked_too() -> None:
    v = table.build_view(run(), None, metric_ids=["owner"], index=True)
    cells = dict(zip(v.frame["ZIP"], v.frame["Homeowners (index)"], strict=True))
    assert cells["33602"].endswith("~") or cells["33602"].endswith("\N{DAGGER}")
    assert not cells["33606"].endswith(("~", "\N{DAGGER}"))


def test_map_tooltips_name_the_tier_and_carry_its_marker() -> None:
    layer = mapview.layer(run(), "owner", None, GEO)
    assert layer is not None
    tips = {f["properties"]["zip"]: f["properties"]["tooltip"] for f in layer.geojson["features"]}
    assert "(Use with caution ~)" in tips["33602"]
    assert "(Unreliable \N{DAGGER})" in tips["33603"]
    assert "(Use with caution" not in tips["33606"] and "(Unreliable" not in tips["33606"]


def test_the_report_marks_caution_cells_and_explains_the_tilde() -> None:
    a = run()
    page = report.render(a, filters.apply(a, []), geo=None, now=NOW, version="1")
    assert "50.0 % ~<" in page
    assert "~ means use with caution" in page and "\N{DAGGER} marks an unreliable estimate" in page


def test_kpi_cards_carry_the_marker_for_their_tier() -> None:
    art = make_artifacts({"33602": Z(3000, 1000, owner=0.5, extra=CAUTION)})
    a = an.analyze(art, parse_paste("33602"), OFF)
    card = next(c for c in kpis.cards(a) if c.metric_id == "owner")
    assert card.tier in ("caution", "unreliable") and card.marker in ("~", "\N{DAGGER}")
    assert next(c for c in kpis.cards(a) if c.metric_id == "hh").marker == ""


# ------------------------------------------------------------------ P15: the filter summary basis
def zipcator() -> an.Analysis:
    parsed = ParsedInput(
        zips=("33602", "33606"), overlaps={"33602": 50.0, "33606": 25.0}, source="zipcator"
    )
    return an.analyze(ART, parsed, OFF)


def test_the_filter_summary_counts_in_radius_households_when_in_radius_is_on() -> None:
    a = zipcator()
    r = filters.apply(a, [Rule("owner", ">=", 0.6)])  # only 33606 qualifies
    in_radius = 1000 * 0.5 + 3500 * 0.25
    assert r.total_households == pytest.approx(in_radius)
    assert r.total_households == pytest.approx(a.trade.values["hh"].estimate)  # = the KPI card
    assert r.matching_households == pytest.approx(3500 * 0.25)
    assert r.summary_line() == "1 of 2 ZIPs match (households: 875 of 1,375)"


def test_the_filter_summary_counts_full_zip_households_in_full_mode() -> None:
    a = an.analyze(
        ART,
        ParsedInput(
            zips=("33602", "33606"), overlaps={"33602": 50.0, "33606": 25.0}, source="zipcator"
        ),
        OFF,
        mode="full",
    )
    r = filters.apply(a, [Rule("owner", ">=", 0.6)])
    assert r.total_households == pytest.approx(4500) and r.matching_households == pytest.approx(
        3500
    )
    assert r.total_households == pytest.approx(a.trade.values["hh"].estimate)


def test_a_blank_overlap_zip_counts_in_full_in_the_summary() -> None:
    parsed = ParsedInput(
        zips=("33602", "33606"),
        overlaps={"33602": 50.0},
        blank_overlap=("33606",),
        source="zipcator",
    )
    a = an.analyze(ART, parsed, OFF)
    r = filters.apply(a, [Rule("owner", ">=", 0.6)])
    assert (
        r.total_households
        == pytest.approx(500 + 3500)
        == pytest.approx(a.trade.values["hh"].estimate)
    )
