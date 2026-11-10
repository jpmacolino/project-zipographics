"""Tests for the D3/D4/D5 readers and geometry assembly in zipographics.geo_build (SPEC §4.1)."""

from __future__ import annotations

import zipfile
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import Polygon, box

from zipographics.errors import BuildError
from zipographics.geo_build import (
    assemble_geometry,
    read_boundaries,
    read_county_relationship,
    read_geonames,
    read_zipcator_geometry,
)

REL_COLUMNS = [
    "OID_ZCTA5_20", "GEOID_ZCTA5_20", "NAMELSAD_ZCTA5_20", "AREALAND_ZCTA5_20",
    "OID_COUNTY_20", "GEOID_COUNTY_20", "NAMELSAD_COUNTY_20", "AREALAND_COUNTY_20",
    "AREALAND_PART", "AREAWATER_PART",
]  # fmt: skip


def write_rel(path: Path, rows: list[tuple[str, str, str, int, int]], bom: bool = False) -> Path:
    """rows: (zcta, county geoid, county name, land part, water part)."""
    lines = ["|".join(REL_COLUMNS)]
    for zcta, geoid, name, land, water in rows:
        lines.append(
            "|".join(
                ["1", zcta, f"ZCTA5 {zcta}", "5", "2", geoid, name, "9", str(land), str(water)]
            )
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8-sig" if bom else "utf-8")
    return path


# ------------------------------------------------------------------------------ D4 relationship
def test_each_zcta_gets_the_county_with_the_largest_land_overlap(tmp_path: Path) -> None:
    path = write_rel(
        tmp_path / "rel.txt",
        [
            ("33602", "12057", "Hillsborough County", 900, 10),
            ("33602", "12103", "Pinellas County", 100, 99),
            ("02108", "25025", "Suffolk County", 500, 0),
            ("00601", "72001", "Adjuntas Municipio", 300, 0),
        ],
    )
    rel = read_county_relationship(path).set_index("zip")
    assert rel.loc["33602", "county_fips"] == "12057"
    assert rel.loc["33602", "county"] == "Hillsborough County"
    assert (rel.loc["33602", "state_fips"], rel.loc["33602", "state"]) == ("12", "FL")
    assert (rel.loc["02108", "state"], rel.loc["00601", "state"]) == ("MA", "PR")
    assert list(rel.index) == sorted(rel.index)


def test_ties_on_land_fall_back_to_water_then_county_id(tmp_path: Path) -> None:
    path = write_rel(
        tmp_path / "rel.txt",
        [
            ("11111", "12003", "A County", 0, 5),  # water-only ZCTA: the larger water part wins
            ("11111", "12001", "B County", 0, 9),
            ("22222", "12009", "C County", 10, 1),
            ("22222", "12005", "D County", 10, 1),  # full tie: the lower county id wins
        ],
    )
    rel = read_county_relationship(path).set_index("zip")
    assert rel.loc["11111", "county_fips"] == "12001"
    assert rel.loc["22222", "county_fips"] == "12005"


def test_blank_zcta_rows_are_dropped_and_zips_stay_five_character_strings(tmp_path: Path) -> None:
    path = write_rel(
        tmp_path / "rel.txt",
        [("", "12057", "No ZCTA County", 5, 0), ("601", "72001", "Adjuntas Municipio", 3, 0)],
        bom=True,
    )
    rel = read_county_relationship(path)
    assert list(rel["zip"]) == ["00601"]
    assert all(isinstance(z, str) and len(z) == 5 for z in rel["zip"])
    assert rel["county_fips"].iloc[0] == "72001"


def test_a_relationship_file_with_a_changed_schema_fails_clearly(tmp_path: Path) -> None:
    path = tmp_path / "rel.txt"
    path.write_text("A|B\n1|2\n", encoding="utf-8")
    with pytest.raises(BuildError, match="GEOID_ZCTA5_20"):
        read_county_relationship(path)


# ------------------------------------------------------------------------------ D5 GeoNames
def write_geonames(path: Path, member: str, rows: list[tuple[str, str]]) -> Path:
    lines = [
        "\t".join(["US", z, city, "State", "ST", "County", "001", "", "", "1.0", "2.0", "4"])
        for z, city in rows
    ]
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr(member, "\n".join(lines) + "\n")
    return path


def test_geonames_gives_the_first_city_per_zip_with_zeros_kept(tmp_path: Path) -> None:
    path = write_geonames(
        tmp_path / "US.zip",
        "US.txt",
        [("2108", "Boston"), ("02108", "Duplicate"), ("33602", "Tampa")],
    )
    df = read_geonames(path)
    assert list(df["zip"]) == ["02108", "33602"]
    assert list(df["city"]) == ["Boston", "Tampa"]


def test_the_territory_file_member_follows_the_zip_name(tmp_path: Path) -> None:
    path = write_geonames(tmp_path / "PR.zip", "PR.txt", [("00601", "Adjuntas")])
    assert list(read_geonames(path)["zip"]) == ["00601"]


def test_a_geonames_download_that_is_not_a_zip_fails_clearly(tmp_path: Path) -> None:
    path = tmp_path / "US.zip"
    path.write_text("<html>error</html>", encoding="utf-8")
    with pytest.raises(BuildError, match="not a valid ZIP"):
        read_geonames(path)


# ------------------------------------------------------------------------------ D3 boundaries
def write_boundary_zip(
    tmp_path: Path, zips: list[str], geoms: list[object], column: str = "ZCTA5CE20"
) -> Path:
    folder = tmp_path / "shp"
    folder.mkdir()
    gdf = gpd.GeoDataFrame(
        {column: zips, "ALAND20": [1000] * len(zips)}, geometry=geoms, crs="EPSG:4269"
    )
    gdf.to_file(folder / "zcta.shp")
    out = tmp_path / "zcta.zip"
    with zipfile.ZipFile(out, "w") as zf:
        for f in folder.iterdir():
            zf.write(f, f.name)
    return out


def test_boundaries_are_read_as_text_zips_in_wgs84(tmp_path: Path) -> None:
    path = write_boundary_zip(tmp_path, ["02108", "00601"], [box(0, 0, 1, 1), box(1, 0, 2, 1)])
    gdf = read_boundaries(path)
    assert list(gdf["zip"]) == ["02108", "00601"]
    assert str(gdf.crs).endswith("4326")
    assert list(gdf.columns) == ["zip", "geometry"]


def test_a_boundary_file_without_the_zcta_column_fails_clearly(tmp_path: Path) -> None:
    path = write_boundary_zip(tmp_path, ["02108"], [box(0, 0, 1, 1)], column="OTHER")
    with pytest.raises(BuildError, match="ZCTA5CE20"):
        read_boundaries(path)


def test_a_boundary_download_that_is_not_a_zip_fails_clearly(tmp_path: Path) -> None:
    path = tmp_path / "zcta.zip"
    path.write_bytes(b"not a zip")
    with pytest.raises(BuildError, match="not a valid ZIP"):
        read_boundaries(path)


# ------------------------------------------------------------------------------ geometry
def noisy_square(x0: float, x1: float, n: int = 60) -> Polygon:
    """A square whose edges carry tiny wiggles (to be removed by simplification)."""
    pts = [(x0, 0.0)]
    pts += [(x0 + (x1 - x0) * i / n, 0.00001 * (i % 2)) for i in range(1, n)]
    pts += [(x1, 0.0), (x1, 1.0)]
    pts += [(x1 - (x1 - x0) * i / n, 1.0 + 0.00001 * (i % 2)) for i in range(1, n)]
    pts += [(x0, 1.0)]
    return Polygon(pts)


def make_gdf(zips: list[str], geoms: list[object]) -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame({"zip": zips}, geometry=geoms, crs="EPSG:4326")


def vertices(gdf: gpd.GeoDataFrame) -> int:
    return int(sum(len(g.exterior.coords) for g in gdf.geometry))


def test_simplification_reduces_vertices_and_keeps_zips_and_order() -> None:
    gdf = make_gdf(["02108", "02109"], [noisy_square(0, 1), noisy_square(1, 2)])
    out = assemble_geometry(gdf, tolerance=0.001)
    assert list(out["zip"]) == ["02108", "02109"]
    assert vertices(out) < vertices(gdf) / 3
    assert out.geometry.is_valid.all()
    assert str(out.crs).endswith("4326")


def test_zero_tolerance_leaves_geometry_unsimplified() -> None:
    gdf = make_gdf(["02108"], [noisy_square(0, 1)])
    assert vertices(assemble_geometry(gdf, tolerance=0)) == vertices(gdf)


def test_neighbours_keep_a_shared_boundary_after_simplification() -> None:
    gdf = make_gdf(["A", "B"], [box(0, 0, 1, 1), box(1, 0, 2, 1)])
    out = assemble_geometry(gdf, tolerance=0.01)
    a, b = out.geometry
    assert a.intersection(b).length == pytest.approx(1.0)  # still share the whole edge


def test_invalid_geometry_is_repaired_and_empty_geometry_stays_null() -> None:
    bowtie = Polygon([(0, 0), (1, 1), (1, 0), (0, 1)])  # self-intersecting
    gdf = make_gdf(["02108", "99999"], [bowtie, None])
    out = assemble_geometry(gdf, tolerance=0)
    assert out.geometry.iloc[0].is_valid and not out.geometry.iloc[0].is_empty
    assert out.geometry.iloc[1] is None


# ------------------------------------------------------------------------------ D3-alt
def test_zipcator_geometry_is_reused_when_its_schema_matches(tmp_path: Path) -> None:
    path = tmp_path / "zcta.parquet"
    make_gdf(["02108", "00601"], [box(0, 0, 1, 1), box(1, 0, 2, 1)]).assign(
        extra=[1, 2]
    ).to_parquet(path)
    gdf, reason = read_zipcator_geometry(path)
    assert reason is None and gdf is not None
    assert list(gdf.columns) == ["zip", "geometry"]
    assert list(gdf["zip"]) == ["02108", "00601"]


@pytest.mark.parametrize("problem", ["no_zip", "numeric_zip", "wrong_crs"])
def test_zipcator_geometry_with_a_mismatched_schema_is_skipped_with_a_reason(
    tmp_path: Path, problem: str
) -> None:
    path = tmp_path / "zcta.parquet"
    gdf = make_gdf(["02108"], [box(0, 0, 1, 1)])
    if problem == "no_zip":
        gdf = gdf.rename(columns={"zip": "code"})
    elif problem == "numeric_zip":
        gdf["zip"] = [2108]
    else:
        gdf = gdf.set_crs("EPSG:3857", allow_override=True)
    gdf.to_parquet(path)
    result, reason = read_zipcator_geometry(path)
    assert result is None and reason


def test_a_missing_zipcator_file_is_skipped_with_a_reason(tmp_path: Path) -> None:
    result, reason = read_zipcator_geometry(tmp_path / "nope.parquet")
    assert result is None and "not found" in (reason or "")


def test_the_pandas_zip_dtype_helper_never_yields_numbers() -> None:
    out = assemble_geometry(make_gdf(["00601"], [box(0, 0, 1, 1)]), tolerance=0)
    assert out["zip"].iloc[0] == "00601" and isinstance(out["zip"].iloc[0], str)
    assert isinstance(out, pd.DataFrame)
