"""Hardening of the build validation, loader and map reader (Phase 4 QA findings 3, 5, 7, 8, 10).

The reviewer mutated the real artifacts and `validate_artifacts` still passed: all-null variables,
an all-null national benchmark, swapped columns, a relabelled map CRS. These tests pin the checks
that now catch them.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import GeometryCollection, MultiPolygon, Point, Polygon, box
from synth_acs import (
    COUNTIES,
    REGISTRY,
    ZCTA_COUNTY,
    ZCTAS,
    FakeClient,
    FileSession,
)

from zipographics import config, data
from zipographics.data import DataNotBuiltError
from zipographics.data_build import (
    DEFAULT_SOURCES,
    BuildError,
    acs_artifacts,
    build,
    geometry_problems,
    validate_artifacts,
)
from zipographics.geo_build import assemble_geometry, read_county_relationship, read_geonames
from zipographics.sentinels import clean_pair


def clones(tmp_path: Path, n: int = 100) -> tuple[pd.DataFrame, pd.DataFrame, Any]:
    art = acs_artifacts(
        FakeClient(),
        2024,
        REGISTRY,
        FileSession(tmp_path),
        tmp_path / "raw",
        False,
        DEFAULT_SOURCES,
    )
    base = art.profile
    big = pd.concat([base.iloc[[i % len(base)]] for i in range(n)])
    big.index = pd.Index([f"{10000 + i}" for i in range(n)], name="zip")
    return big, art.benchmarks.copy(), art.resolved


def check(big: pd.DataFrame, bench: pd.DataFrame, resolved: Any, **kw: Any) -> list[str]:
    return validate_artifacts(big, bench, resolved, REGISTRY, min_rows=5, **kw)[0]


# ------------------------------------------------------------------------- every variable
def test_every_variable_needs_some_coverage_not_only_the_core_ones(tmp_path: Path) -> None:
    big, bench, resolved = clones(tmp_path)
    assert config.VARIABLE_COVERAGE_FLOOR == 0.5
    big.iloc[:60, big.columns.get_loc("DP03_UNINS_e")] = np.nan  # 40 % present
    problems = check(big, bench, resolved)
    assert any("DP03_UNINS" in p and "50%" in p for p in problems)


def test_a_variable_at_the_floor_passes(tmp_path: Path) -> None:
    big, bench, resolved = clones(tmp_path)
    big.iloc[:50, big.columns.get_loc("DP03_UNINS_e")] = np.nan  # 50 % present
    assert check(big, bench, resolved) == []


def test_a_wholly_null_variable_fails(tmp_path: Path) -> None:
    big, bench, resolved = clones(tmp_path)
    big["DP03_CIVNONINST_e"] = np.nan
    assert any("DP03_CIVNONINST" in p for p in check(big, bench, resolved))


# ------------------------------------------------------------------------- benchmarks
def test_the_national_benchmark_needs_a_value_for_every_variable(tmp_path: Path) -> None:
    big, bench, resolved = clones(tmp_path)
    us = bench["geo_level"] == "us"
    bench.loc[us, "B25003_002_e"] = np.nan
    problems = check(big, bench, resolved)
    assert any("national benchmark" in p and "B25003_002" in p for p in problems)


def test_every_state_benchmark_needs_its_values(tmp_path: Path) -> None:
    big, bench, resolved = clones(tmp_path)
    bench.loc[bench["geo_level"] == "state", "B01003_001_e"] = np.nan
    assert any("state benchmark" in p and "B01003_001" in p for p in check(big, bench, resolved))


def test_a_county_benchmark_may_have_gaps(tmp_path: Path) -> None:
    big, bench, resolved = clones(tmp_path)
    bench.loc[bench["geo_level"] == "county", "B25003_002_e"] = np.nan  # small counties: suppressed
    assert check(big, bench, resolved) == []


# ------------------------------------------------------------------------- cross-table totals
def test_tables_that_must_agree_are_checked(tmp_path: Path) -> None:
    # B11001_001 (households) and B25003_001 (occupied units) are the same count (SPEC §6.5)
    big, bench, resolved = clones(tmp_path)
    big.iloc[:10, big.columns.get_loc("B25003_001_e")] += 50  # 10 % disagree
    problems = check(big, bench, resolved)
    assert any("B11001_001" in p and "B25003_001" in p and "disagree" in p for p in problems)


def test_a_few_rounding_disagreements_are_tolerated(tmp_path: Path) -> None:
    big, bench, resolved = clones(tmp_path, n=2000)
    big.iloc[:1, big.columns.get_loc("B25003_001_e")] += 1  # 1 in 2,000 (0.05 %)
    assert check(big, bench, resolved) == []


# --------------------------------------------------------------- county gaps: Connecticut only
def gap_session(tmp_path: Path) -> FileSession:
    cols = [
        "GEOID_ZCTA5_20",
        "GEOID_COUNTY_20",
        "NAMELSAD_COUNTY_20",
        "AREALAND_PART",
        "AREAWATER_PART",
    ]
    lines = ["|".join(cols)]
    for z, c in {**ZCTA_COUNTY, "33603": "12999"}.items():
        lines.append(
            "|".join([z, c, COUNTIES.get(c, "Old County, State").split(",")[0], "1000", "10"])
        )
    session = FileSession(tmp_path)
    session.files[DEFAULT_SOURCES.county_rel_url] = ("\n".join(lines) + "\n").encode("utf-8")
    return session


def test_a_county_gap_outside_connecticut_fails_even_under_the_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(config, "COUNTY_GAP_LIMIT", 0.5)
    assert config.COUNTY_GAP_STATES == ("CT",)
    with pytest.raises(BuildError, match="outside Connecticut"):
        build(tmp_path / "data", client=FakeClient(), session=gap_session(tmp_path),
              registry=REGISTRY, min_rows=5, tolerance=0.002)  # fmt: skip


def test_the_same_gap_in_connecticut_is_allowed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(config, "COUNTY_GAP_LIMIT", 0.5)
    monkeypatch.setattr(
        config, "COUNTY_GAP_STATES", ("FL",)
    )  # stand-in for CT in the synthetic data
    build(tmp_path / "data", client=FakeClient(), session=gap_session(tmp_path),
          registry=REGISTRY, min_rows=5, tolerance=0.002)  # fmt: skip


# ------------------------------------------------------------------------- the map
def geo_for(zips: list[str]) -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        {"zip": zips}, geometry=[box(i, 0, i + 1, 1) for i, _ in enumerate(zips)], crs="EPSG:4326"
    )


def test_the_map_must_be_in_wgs84() -> None:
    wrong = geo_for(["02108", "02109"]).set_crs("EPSG:3857", allow_override=True)
    assert any("EPSG:4326" in p for p in geometry_problems(wrong, None))
    assert geometry_problems(geo_for(["02108"]), None) == []
    assert any(
        "EPSG:4326" in p
        for p in geometry_problems(geo_for(["02108"]).set_crs(None, allow_override=True), None)
    )


def test_the_map_must_have_text_zips() -> None:
    geo = geo_for(["02108"])
    geo["zip"] = [2108]
    assert any("text" in p for p in geometry_problems(geo, None))


# ------------------------------------------------------------------------- null counts and metadata
def test_json_nulls_are_counted_separately_from_sentinels() -> None:
    s = lambda *v: pd.Series(list(v), dtype="object")  # noqa: E731
    est, _, counts = clean_pair(s("12,345", "(X)", None, "", "null", "NaN", 7), s(*[1] * 7))
    assert est.isna().sum() == 6 and est[6] == 7
    assert counts == {"estimate:non_numeric": 2, "estimate:null": 4}


def test_a_moe_that_is_null_because_its_estimate_is_null_is_not_double_counted() -> None:
    s = lambda *v: pd.Series(list(v), dtype="object")  # noqa: E731
    _, moe, counts = clean_pair(s(None, 5), s(None, 2))
    assert counts == {"estimate:null": 1, "moe:null": 1}
    assert np.isnan(moe[0]) and moe[1] == 2


def test_the_metadata_states_its_coverage_basis_and_the_map_simplification(tmp_path: Path) -> None:
    build(tmp_path / "data", client=FakeClient(), session=FileSession(tmp_path), registry=REGISTRY,
          min_rows=5, tolerance=0.002)  # fmt: skip
    meta = json.loads((tmp_path / "data" / "metadata.json").read_text(encoding="utf-8"))
    assert meta["coverage_basis"] == {"zctas_with_population": 6, "zctas_total": 6}
    assert "simplified" in meta["geometry"]["note"].lower()
    assert "indicative" in meta["geometry"]["note"].lower()


# ------------------------------------------------------------------------- loader schema checks
@pytest.fixture
def built(tmp_path: Path) -> Path:
    build(tmp_path / "data", client=FakeClient(), session=FileSession(tmp_path), registry=REGISTRY,
          min_rows=5, tolerance=0.002)  # fmt: skip
    return tmp_path / "data"


def test_benchmark_ids_must_be_text(built: Path) -> None:
    path = built / "benchmarks.parquet"
    frame = pd.read_parquet(path)
    frame["geo_id"] = [1] * len(frame)
    frame.to_parquet(path)
    with pytest.raises(DataNotBuiltError, match="geo_id"):
        data.load(built, registry=REGISTRY)


def test_profile_state_ids_must_be_text(built: Path) -> None:
    path = built / "zcta_profile.parquet"
    frame = pd.read_parquet(path)
    frame["state_fips"] = [12.0] * len(frame)
    frame.to_parquet(path)
    with pytest.raises(DataNotBuiltError, match="state_fips"):
        data.load(built, registry=REGISTRY)


def test_profile_zips_must_be_five_characters(built: Path) -> None:
    path = built / "zcta_profile.parquet"
    frame = pd.read_parquet(path)
    frame["zip"] = ["2108", *frame["zip"][1:]]
    frame.to_parquet(path)
    with pytest.raises(DataNotBuiltError, match="5-character"):
        data.load(built, registry=REGISTRY)


# ------------------------------------------------------------------------- geo_build edge cases
def test_a_geometry_collection_keeps_only_its_polygons() -> None:
    mixed = GeometryCollection([box(0, 0, 1, 1), Point(5, 5), box(2, 0, 3, 1)])
    gdf = gpd.GeoDataFrame({"zip": ["02108"]}, geometry=[mixed], crs="EPSG:4326")
    out = assemble_geometry(gdf, tolerance=0).geometry.iloc[0]
    assert isinstance(out, MultiPolygon) and len(out.geoms) == 2 and out.is_valid


def test_a_collection_with_one_polygon_becomes_that_polygon() -> None:
    gdf = gpd.GeoDataFrame(
        {"zip": ["02108"]},
        geometry=[GeometryCollection([box(0, 0, 1, 1), Point(5, 5)])],
        crs="EPSG:4326",
    )
    assert isinstance(assemble_geometry(gdf, tolerance=0).geometry.iloc[0], Polygon)


def test_a_collection_without_polygons_and_an_empty_polygon_become_null() -> None:
    gdf = gpd.GeoDataFrame(
        {"zip": ["A", "B"]},
        geometry=[GeometryCollection([Point(0, 0)]), Polygon()],
        crs="EPSG:4326",
    )
    out = assemble_geometry(gdf, tolerance=0)
    assert out.geometry.iloc[0] is None and out.geometry.iloc[1] is None


def test_an_unreadable_relationship_file_is_a_clear_build_error(tmp_path: Path) -> None:
    path = tmp_path / "rel.txt"
    path.write_bytes(b"\xff\xfe\x00bad\x80\x81")
    with pytest.raises(BuildError, match=r"rel.txt"):
        read_county_relationship(path)


def test_an_empty_relationship_file_is_a_clear_build_error(tmp_path: Path) -> None:
    path = tmp_path / "rel.txt"
    path.write_text("", encoding="utf-8")
    with pytest.raises(BuildError, match=r"rel.txt"):
        read_county_relationship(path)


def test_a_geonames_zip_without_its_member_is_a_clear_build_error(tmp_path: Path) -> None:
    import zipfile

    path = tmp_path / "US.zip"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("other.txt", "x")
    with pytest.raises(BuildError, match=r"US.txt"):
        read_geonames(path)


def test_an_empty_geonames_member_is_a_clear_build_error(tmp_path: Path) -> None:
    import zipfile

    path = tmp_path / "US.zip"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("US.txt", "")
    with pytest.raises(BuildError, match=r"US.txt"):
        read_geonames(path)


def test_zctas_constant_is_what_the_synthetic_data_uses() -> None:
    assert len(ZCTAS) == 6
