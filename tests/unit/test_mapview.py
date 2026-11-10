"""The interactive map layer: data, style and restricted-mode enforcement (SPEC 5.5, 5.7).

`mapview.layer` is to the map what `filters.apply` is to selection: in restricted mode it gives the
neutral style for every metric (no choropleth, no outline, no qualifying highlight), refuses a
filter result that carries rules, and never lets a metric choose a color.
"""

from __future__ import annotations

import json
import time

import geopandas as gpd
import pytest
from shapely.geometry import box
from synth_art import Z, make_artifacts

from zipographics import analysis as an
from zipographics import filters, mapview, metrics, verticals
from zipographics.errors import RestrictedUseError
from zipographics.models import Rule, UsePolicy
from zipographics.zips import parse_paste

OFF = verticals.make_policy("Retail (general & specialty)", False)
FORCED = verticals.make_policy("Insurance", None)
ANSWERED = verticals.make_policy("Automotive sales", True)
LIAR = UsePolicy(False, "Insurance", "No")  # a restricted industry with a permissive flag

WORLD = {
    "33602": Z(5000, 2000, owner=0.40, kids=0.20),
    "33606": Z(8000, 3500, owner=0.70, kids=0.35),
    "33603": Z(900, 280, owner=0.55, kids=0.30, extra={"B25003_002": (154.0, 200.0)}),
    "33604": Z(2500, 1200, owner=0.65, kids=0.25, income=None),
    "33605": Z(4000, 1500, owner=0.20, kids=0.25, income=250_001, code="top"),
}
ART = make_artifacts(WORLD)
GEO = gpd.GeoDataFrame(
    {"zip": [*WORLD, "99999"]},  # 99999 has a polygon but is not part of the trade area
    geometry=[box(-82.5 + 0.1 * i, 27.9, -82.4 + 0.1 * i, 28.0) for i in range(6)],
    crs="EPSG:4326",
)
TEXT = "33602 33606 33603 33604 33605"


def run(policy=OFF, text: str = TEXT, **kw):  # type: ignore[no-untyped-def]
    return an.analyze(ART, parse_paste(text), policy, project_name="Map", **kw)


def features(layer: mapview.MapLayer) -> dict[str, dict]:  # type: ignore[type-arg]
    return {f["properties"]["zip"]: f for f in layer.geojson["features"]}


# ------------------------------------------------------------------------- shape of the data
def test_the_layer_has_one_feature_per_recognized_zip_with_a_polygon() -> None:
    layer = mapview.layer(run(), "owner", None, GEO)
    assert layer is not None
    assert layer.geojson["type"] == "FeatureCollection"
    assert set(features(layer)) == set(WORLD)  # 99999 is not in the trade area
    json.dumps(layer.geojson)  # serializable
    f = features(layer)["33602"]
    assert f["geometry"]["type"] in ("Polygon", "MultiPolygon")
    (south, west), (north, east) = layer.bounds
    assert south < north and west < east


def test_no_geometry_or_no_matching_polygon_gives_none() -> None:
    assert mapview.layer(run(), "owner", None, None) is None
    other = gpd.GeoDataFrame({"zip": ["99999"]}, geometry=[box(0, 0, 1, 1)], crs="EPSG:4326")
    assert mapview.layer(run(), "owner", None, other) is None


def test_zips_without_a_polygon_are_reported_not_dropped_silently() -> None:
    partial = GEO[GEO["zip"].isin(["33602", "33606"])]
    layer = mapview.layer(run(), "owner", None, partial)
    assert layer is not None and set(layer.missing) == {"33603", "33604", "33605"}
    assert layer.note and "3 of 5" in layer.note


def test_tooltips_carry_the_zip_city_and_values() -> None:
    layer = mapview.layer(run(), "owner", None, GEO)
    assert layer is not None
    tip = features(layer)["33602"]["properties"]["tooltip"]
    assert "33602" in tip and "Tampa" in tip and "Homeowners" in tip and "40.0 %" in tip
    assert "Population" in tip and "5,000" in tip


# ------------------------------------------------------------------------- choropleth
def test_unrestricted_shades_by_the_chosen_metric_in_quantile_bins() -> None:
    layer = mapview.layer(run(), "owner", None, GEO)
    assert layer is not None and layer.style == "choropleth" and layer.metric_id == "owner"
    fills = {z: f["properties"]["style"]["fillColor"] for z, f in features(layer).items()}
    assert fills["33606"] != fills["33605"]  # 70 % vs 20 % owners: different bins
    assert layer.legend and all(item.color.startswith("#") for item in layer.legend)
    assert layer.legend_title == "Homeowners"


def test_a_higher_value_is_a_darker_shade() -> None:
    layer = mapview.layer(run(), "owner", None, GEO)
    assert layer is not None
    luminance = {
        z: sum(int(f["properties"]["style"]["fillColor"][i : i + 2], 16) for i in (1, 3, 5))
        for z, f in features(layer).items()
    }
    assert luminance["33606"] < luminance["33605"]  # 33606 (70 %) is darker than 33605 (20 %)


def test_unknown_and_coded_values_are_drawn_neutral() -> None:
    layer = mapview.layer(run(), "median_hh_income", None, GEO)
    assert layer is not None
    fills = {z: f["properties"]["style"]["fillColor"] for z, f in features(layer).items()}
    assert fills["33604"] == mapview.NEUTRAL  # no published median
    assert fills["33605"] == mapview.NEUTRAL  # top-coded: a bound, not an exact value
    assert fills["33602"] != mapview.NEUTRAL
    assert (
        "250,001" not in json.dumps(layer.geojson)
        and "$250,000+" in features(layer)["33605"]["properties"]["tooltip"]
    )


def test_all_equal_values_make_one_bin() -> None:
    world = {z: Z(1000, 400, owner=0.5) for z in ("33602", "33606")}
    art = make_artifacts(world)
    a = an.analyze(art, parse_paste("33602 33606"), OFF)
    layer = mapview.layer(a, "owner", None, GEO)
    assert layer is not None and len(layer.legend) == 1


def test_qualifying_zips_are_outlined_more_heavily() -> None:
    a = run()
    result = filters.apply(a, [Rule("owner", ">=", 0.6)])
    layer = mapview.layer(a, "owner", result, GEO)
    assert layer is not None
    st = {z: f["properties"]["style"] for z, f in features(layer).items()}
    assert (
        st["33606"]["weight"] > st["33602"]["weight"]
        and st["33605"]["weight"] == st["33602"]["weight"]
    )
    assert features(layer)["33606"]["properties"]["qualifies"] is True


def test_an_unreliable_value_is_dashed_and_the_tooltip_says_so() -> None:
    layer = mapview.layer(run(), "owner", None, GEO)
    assert layer is not None
    st = features(layer)["33603"]["properties"]
    assert st["style"]["dashArray"] and "Unreliable" in st["tooltip"]
    assert not features(layer)["33602"]["properties"]["style"]["dashArray"]


def test_a_count_metric_is_shaded_by_its_value() -> None:
    layer = mapview.layer(run(), "pop", None, GEO)
    assert layer is not None and layer.style == "choropleth"


def test_an_unknown_metric_is_an_error() -> None:
    with pytest.raises(ValueError, match="Unknown metric"):
        mapview.layer(run(), "nope", None, GEO)


# ------------------------------------------------------------------------- restricted mode
@pytest.mark.parametrize("policy", [FORCED, ANSWERED, LIAR])
@pytest.mark.parametrize("metric", [m.id for m in metrics.REGISTRY])
def test_restricted_mode_returns_the_neutral_style_for_every_metric(metric: str, policy) -> None:  # type: ignore[no-untyped-def]
    a = RESTRICTED_ANALYSES[policy]
    layer = mapview.layer(a, metric, None, GEO)
    assert layer is not None
    assert layer.style == "neutral" and layer.metric_id is None and layer.legend == ()
    fills = {f["properties"]["style"]["fillColor"] for f in layer.geojson["features"]}
    assert fills == {mapview.NEUTRAL}
    weights = {f["properties"]["style"]["weight"] for f in layer.geojson["features"]}
    assert len(weights) == 1  # no outline highlight
    assert not any("qualifies" in f["properties"] for f in layer.geojson["features"])


RESTRICTED_ANALYSES = {p: run(p) for p in (FORCED, ANSWERED, LIAR)}


@pytest.mark.parametrize("policy", [FORCED, ANSWERED, LIAR])
def test_restricted_mode_refuses_a_filter_result_with_rules(policy) -> None:  # type: ignore[no-untyped-def]
    result = filters.apply(run(OFF), [Rule("owner", ">=", 0.6)])
    with pytest.raises(RestrictedUseError):
        mapview.layer(run(policy), "owner", result, GEO)


@pytest.mark.parametrize("policy", [FORCED, ANSWERED, LIAR])
def test_restricted_tooltips_still_show_values_as_context(policy) -> None:  # type: ignore[no-untyped-def]
    layer = mapview.layer(run(policy), "owner", None, GEO)
    assert layer is not None
    tip = features(layer)["33602"]["properties"]["tooltip"]
    assert "Population" in tip and "5,000" in tip and "33602" in tip


def test_the_neutral_layer_is_the_same_whatever_metric_is_asked() -> None:
    a = run(FORCED)
    one = mapview.layer(a, "owner", None, GEO)
    two = mapview.layer(a, "median_hh_income", None, GEO)
    assert one is not None and two is not None and one.geojson == two.geojson


# ------------------------------------------------------------------------- budget
def test_a_thousand_zips_prepare_quickly() -> None:
    world = {
        f"{10000 + i:05d}": Z(1000 + i, 400 + i, owner=0.3 + (i % 50) / 100) for i in range(1000)
    }
    art = make_artifacts(world)
    geo = gpd.GeoDataFrame(
        {"zip": list(world)},
        geometry=[box(-100 + (i % 40) * 0.05, 30 + (i // 40) * 0.05, -99.96 + (i % 40) * 0.05,
                      30.04 + (i // 40) * 0.05) for i in range(1000)],
        crs="EPSG:4326",
    )  # fmt: skip
    from zipographics.models import ParsedInput

    a = an.analyze(art, ParsedInput(zips=tuple(world)), OFF)
    start = time.perf_counter()
    layer = mapview.layer(a, "owner", None, geo)
    assert layer is not None and len(layer.geojson["features"]) == 1000
    assert time.perf_counter() - start < 2.0  # SPEC 7: 1 s on the target laptop; CI slack
