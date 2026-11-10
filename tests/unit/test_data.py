"""Tests for zipographics.data: loading the built artifacts (SPEC §4.4, §9.2)."""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import pandas as pd
import pytest
from synth_acs import REGISTRY, ZCTAS, FakeClient, FileSession

from zipographics import data
from zipographics.data import DataNotBuiltError, facts_from_profile, load
from zipographics.data_build import build
from zipographics.facts import validate_facts
from zipographics.review import review_lines, summarize
from zipographics.zips import parse_paste

MESSAGE = "Census data not built yet. Run `uv run python scripts/build_data.py`, then reload."


@pytest.fixture
def built(tmp_path: Path) -> Path:
    build(
        tmp_path / "data",
        client=FakeClient(),
        session=FileSession(tmp_path),
        registry=REGISTRY,
        min_rows=5,
        tolerance=0.002,
    )
    return tmp_path / "data"


def test_a_missing_data_folder_raises_the_build_instruction(tmp_path: Path) -> None:
    with pytest.raises(DataNotBuiltError) as exc:
        load(tmp_path / "nope", registry=REGISTRY)
    assert str(exc.value).startswith(MESSAGE)


@pytest.mark.parametrize("missing", ["zcta_profile.parquet", "benchmarks.parquet", "metadata.json"])
def test_each_required_file_is_required(built: Path, missing: str) -> None:
    (built / missing).unlink()
    with pytest.raises(DataNotBuiltError) as exc:
        load(built, registry=REGISTRY)
    assert str(exc.value).startswith(MESSAGE) and missing in str(exc.value)


def test_the_map_is_optional_and_its_absence_is_explained(built: Path) -> None:
    (built / "zcta_geo.parquet").unlink()
    artifacts = load(built, registry=REGISTRY)
    assert artifacts.geo is None
    assert (
        artifacts.geo_note and "map" in artifacts.geo_note and "build_data.py" in artifacts.geo_note
    )
    assert len(artifacts.profile) == 6


def test_a_good_build_loads_with_text_zips_and_a_geometry_frame(built: Path) -> None:
    artifacts = load(built, registry=REGISTRY)
    assert list(artifacts.profile.index) == ZCTAS
    assert artifacts.profile.index.name == "zip"
    assert all(isinstance(z, str) for z in artifacts.profile.index)
    assert isinstance(artifacts.geo, gpd.GeoDataFrame) and list(artifacts.geo["zip"]) == ZCTAS
    assert artifacts.geo_note is None
    assert artifacts.metadata["vintage"] == 2024
    assert {"geo_level", "geo_id", "name"} <= set(artifacts.benchmarks.columns)


@pytest.mark.parametrize("column", ["B01003_001_e", "B19013_001_code", "state", "county_fips"])
def test_a_profile_missing_a_required_column_is_not_built(built: Path, column: str) -> None:
    path = built / "zcta_profile.parquet"
    pd.read_parquet(path).drop(columns=[column]).to_parquet(path)
    with pytest.raises(DataNotBuiltError) as exc:
        load(built, registry=REGISTRY)
    assert str(exc.value).startswith(MESSAGE) and column in str(exc.value)


def test_numeric_zips_in_a_profile_are_rejected(built: Path) -> None:
    path = built / "zcta_profile.parquet"
    frame = pd.read_parquet(path)
    frame["zip"] = [601, 2108, 2109, 33602, 33603, 59001]
    frame.to_parquet(path)
    with pytest.raises(DataNotBuiltError, match="zip"):
        load(built, registry=REGISTRY)


def test_benchmarks_missing_a_column_are_not_built(built: Path) -> None:
    path = built / "benchmarks.parquet"
    pd.read_parquet(path).drop(columns=["geo_level"]).to_parquet(path)
    with pytest.raises(DataNotBuiltError, match="geo_level"):
        load(built, registry=REGISTRY)


def test_a_corrupt_file_is_not_built(built: Path) -> None:
    (built / "zcta_profile.parquet").write_bytes(b"not parquet")
    with pytest.raises(DataNotBuiltError) as exc:
        load(built, registry=REGISTRY)
    assert str(exc.value).startswith(MESSAGE)


def test_a_geometry_file_with_the_wrong_schema_is_treated_as_missing(built: Path) -> None:
    gpd.GeoDataFrame(
        {"code": ["02108"]}, geometry=gpd.points_from_xy([0], [0]), crs=4326
    ).to_parquet(built / "zcta_geo.parquet")
    artifacts = load(built, registry=REGISTRY)
    assert artifacts.geo is None and "map" in (artifacts.geo_note or "")


def test_the_data_folder_defaults_to_the_configured_one(
    tmp_path: Path, built: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ZIPOGRAPHICS_DATA_DIR", str(built))
    assert load(registry=REGISTRY).metadata["vintage"] == 2024
    monkeypatch.setenv("ZIPOGRAPHICS_DATA_DIR", str(tmp_path / "empty"))
    with pytest.raises(DataNotBuiltError):
        load(registry=REGISTRY)


# ------------------------------------------------------------------------------ facts
def test_the_facts_frame_feeds_the_review_screen(built: Path) -> None:
    artifacts = load(built, registry=REGISTRY)
    facts = facts_from_profile(artifacts.profile)
    assert list(facts.columns[:5]) == ["state", "population", "households", "county_fips", "county"]
    assert validate_facts(facts) is facts
    assert facts.loc["33602", "state"] == "FL" and facts.loc["33602", "population"] == 2300
    assert facts.loc["00601", "population"] == 2000

    summary = summarize(parse_paste("2108, 33602, 59001, 33601"), facts)
    assert summary.recognized == ("02108", "33602", "59001")
    assert summary.not_found == ("33601",)
    assert summary.states == ("FL", "MA", "MT")
    assert any("repaired" in line for line in review_lines(summary))


def test_default_registry_names_the_population_and_household_variables() -> None:
    assert data.POPULATION_KEY == "B01003_001" and data.HOUSEHOLDS_KEY == "B11001_001"
