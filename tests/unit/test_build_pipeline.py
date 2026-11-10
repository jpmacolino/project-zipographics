"""Tests for the data build pipeline in zipographics.data_build (SPEC §4.3, §4.4, §9.2).

A fake client and fake downloads stand in for the network (tests/synth_acs.py); a tiny registry
keeps it readable. Nothing here touches the real Census API or a real key.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import box
from synth_acs import (
    BRACKETS,
    COUNTIES,
    DETAILED_META,
    METRICS,
    PROFILE_META,
    REGISTRY,
    STATES,
    VARS,
    ZCTAS,
    FakeClient,
    FileSession,
    Synth,
)

from zipographics import __version__
from zipographics.census_api import VarRequest
from zipographics.data_build import (
    DEFAULT_SOURCES,
    BuildError,
    acs_artifacts,
    build,
    fetch_level,
    resolve_variables,
    validate_artifacts,
)
from zipographics.metrics import MedianSpec

RESOLVED = resolve_variables(
    VARS,
    {"detailed": DETAILED_META, "profile": PROFILE_META},
    [m.spec for m in METRICS if isinstance(m.spec, MedianSpec)],
)
KEY = "0123456789abcdef0123456789abcdef01234567"


def run_build(tmp_path: Path, *, client: Any = None, session: Any = None, **kw: Any):  # type: ignore[no-untyped-def]
    return build(
        tmp_path / "data",
        client=client or FakeClient(),
        session=session or FileSession(tmp_path),
        registry=REGISTRY,
        min_rows=5,
        tolerance=0.002,
        **kw,
    )


# ------------------------------------------------------------------------------ one geography level
def test_zcta_level_is_cleaned_renamed_and_keeps_text_zips() -> None:
    lvl = fetch_level(FakeClient(), 2024, "zcta", RESOLVED, VARS)
    df = lvl.data
    assert list(df.index) == ZCTAS
    assert all(isinstance(z, str) for z in df.index)
    assert df.index.name == "zip"
    # columns are named by registry key, including the Data Profile items resolved by label
    assert {"B01003_001_e", "B01003_001_m", "DP03_UNINS_e", "DP03_CIVNONINST_m"} <= set(df.columns)
    assert not any(c.startswith("DP03_0") for c in df.columns)
    assert df.loc["33602", "B01003_001_e"] == 2300 and df.loc["33602", "B01003_001_m"] == 230


def test_sentinels_become_nulls_codes_and_zero_moes() -> None:
    lvl = fetch_level(FakeClient(), 2024, "zcta", RESOLVED, VARS)
    df = lvl.data
    assert df.loc["02108", "B19013_001_e"] == 250001  # top-coded median: estimate kept
    assert math.isnan(df.loc["02108", "B19013_001_m"])  # -333333333 -> MOE null
    assert df.loc["02108", "B19013_001_code"] == "top"
    assert df.loc["02109", "B25003_002_m"] == 0.0  # -555555555 -> MOE 0
    assert math.isnan(df.loc["59001", "B19001_003_e"])  # -666666666 -> estimate null
    assert math.isnan(df.loc["59001", "B19001_003_m"])
    assert set(df["B19013_001_code"]) == {"none", "top"}
    assert "B01003_001_code" not in df.columns
    assert lvl.sentinel_counts == {
        "estimate:-666666666": 1,
        "moe:-333333333": 1,
        "moe:-555555555": 1,
        "moe:-222222222": 1,
    }


def test_no_sentinel_value_survives_in_any_numeric_column() -> None:
    for level in ("zcta", "state", "county", "us"):
        df = fetch_level(FakeClient(), 2024, level, RESOLVED, VARS).data
        numbers = df.select_dtypes("number")
        assert (numbers.fillna(0) > -100_000_000).all().all(), level


def test_state_county_and_us_levels_use_fips_ids_and_carry_names() -> None:
    client = FakeClient()
    state = fetch_level(client, 2024, "state", RESOLVED, VARS)
    county = fetch_level(client, 2024, "county", RESOLVED, VARS)
    us = fetch_level(client, 2024, "us", RESOLVED, VARS)
    assert list(state.data.index) == list(STATES)
    assert list(county.data.index) == list(COUNTIES)  # 5-digit state + county
    assert list(us.data.index) == ["1"]
    assert state.names is not None and state.names["72"] == "Puerto Rico"
    assert county.names is not None and county.names["12057"].startswith("Hillsborough")
    assert fetch_level(client, 2024, "zcta", RESOLVED, VARS).names is None


def test_an_unknown_large_negative_value_fails_the_build_with_exit_code_5() -> None:
    client = FakeClient(Synth(bad_sentinel=True))
    with pytest.raises(BuildError) as exc:
        fetch_level(client, 2024, "zcta", RESOLVED, VARS)
    assert exc.value.exit_code == 5 and "-123456789" in str(exc.value)


def test_requests_use_the_resolved_ids_and_ask_for_annotations_only_for_medians() -> None:
    seen: list[list[VarRequest]] = []

    class Spy(FakeClient):
        def fetch_table(self, dataset, vintage, level, variables):  # type: ignore[no-untyped-def]
            seen.append(list(variables))
            return super().fetch_table(dataset, vintage, level, variables)

    fetch_level(Spy(), 2024, "state", RESOLVED, VARS)
    detailed = {v.id: v for v in seen[0]}
    profile = {v.id: v for v in seen[1]}
    assert detailed["B19013_001"].is_median and not detailed["B01003_001"].is_median
    assert set(profile) == {"DP03_0099", "DP03_0095"}  # resolved Data Profile ids, not keys


# ------------------------------------------------------------------------------ ACS artifacts
def test_profile_has_attributes_first_then_one_row_per_zcta(tmp_path: Path) -> None:
    art = acs_artifacts(
        FakeClient(),
        2024,
        REGISTRY,
        FileSession(tmp_path),
        tmp_path / "raw",
        False,
        DEFAULT_SOURCES,
    )
    p = art.profile
    assert list(p.columns[:5]) == ["state_fips", "state", "county_fips", "county", "city"]
    assert list(p.index) == ZCTAS
    assert p.loc["00601", "state"] == "PR" and p.loc["00601", "state_fips"] == "72"
    assert p.loc["00601", "city"] == "Adjuntas"  # from the PR GeoNames file
    assert p.loc["33602", "county_fips"] == "12057"  # largest land overlap beat the 99999 county
    assert p.loc["33602", "county"] == "Hillsborough County"
    assert p.loc["02108", "state"] == "MA"


def test_benchmarks_cover_the_nation_states_and_counties(tmp_path: Path) -> None:
    art = acs_artifacts(
        FakeClient(),
        2024,
        REGISTRY,
        FileSession(tmp_path),
        tmp_path / "raw",
        False,
        DEFAULT_SOURCES,
    )
    b = art.benchmarks
    assert list(b.columns[:3]) == ["geo_level", "geo_id", "name"]
    assert sorted(b["geo_level"].unique()) == ["county", "state", "us"]
    assert list(b.loc[b["geo_level"] == "us", "geo_id"]) == ["1"]
    assert set(b.loc[b["geo_level"] == "state", "geo_id"]) == set(STATES)
    assert set(b.loc[b["geo_level"] == "county", "geo_id"]) == set(COUNTIES)
    assert all(isinstance(g, str) for g in b["geo_id"])
    assert b.loc[b["geo_id"] == "72", "name"].iloc[0] == "Puerto Rico"
    assert [c for c in b.columns[3:]] == [
        c for c in art.profile.columns[5:]
    ]  # same variable columns


def test_resolved_variables_and_sentinel_counts_are_reported(tmp_path: Path) -> None:
    art = acs_artifacts(
        FakeClient(),
        2024,
        REGISTRY,
        FileSession(tmp_path),
        tmp_path / "raw",
        False,
        DEFAULT_SOURCES,
    )
    assert set(art.resolved) == set(VARS)
    assert art.resolved["DP03_UNINS"].id == "DP03_0099E"
    assert art.sentinel_counts["estimate:-666666666"] == 1


# ------------------------------------------------------------------------------ validation
def happy(tmp_path: Path):  # type: ignore[no-untyped-def]
    art = acs_artifacts(
        FakeClient(),
        2024,
        REGISTRY,
        FileSession(tmp_path),
        tmp_path / "raw",
        False,
        DEFAULT_SOURCES,
    )
    return art.profile.copy(), art.benchmarks.copy(), art.resolved


def geo_for(zips: list[str]) -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        {"zip": zips}, geometry=[box(i, 0, i + 1, 1) for i, _ in enumerate(zips)], crs="EPSG:4326"
    )


def test_valid_artifacts_pass_and_report_coverage(tmp_path: Path) -> None:
    p, b, resolved = happy(tmp_path)
    problems, coverage = validate_artifacts(
        p, b, resolved, REGISTRY, geo=geo_for(ZCTAS), min_rows=5
    )
    assert problems == []
    assert coverage["B01003_001"] == 1.0
    assert coverage["B19001_003"] == pytest.approx(5 / 6)  # one ZCTA carried a sentinel


def test_too_few_rows_fail(tmp_path: Path) -> None:
    p, b, resolved = happy(tmp_path)
    problems, _ = validate_artifacts(p, b, resolved, REGISTRY, min_rows=33_000)
    assert any("33,000" in x for x in problems)


def test_zips_must_be_five_digit_strings(tmp_path: Path) -> None:
    p, b, resolved = happy(tmp_path)
    p.index = pd.Index([2108, 601, 1, 2, 3, 4])
    problems, _ = validate_artifacts(p, b, resolved, REGISTRY, min_rows=5)
    assert any("5-digit" in x for x in problems)
    p, b, resolved = happy(tmp_path)
    p.index = pd.Index(["2108", "00601", "02109", "33602", "33603", "59001"])
    assert any("5-digit" in x for x in validate_artifacts(p, b, resolved, REGISTRY, min_rows=5)[0])


def test_a_surviving_sentinel_value_fails(tmp_path: Path) -> None:
    p, b, resolved = happy(tmp_path)
    p.loc["33602", "B01003_001_e"] = -666666666.0
    problems, _ = validate_artifacts(p, b, resolved, REGISTRY, min_rows=5)
    assert any("sentinel" in x for x in problems)
    p, b, resolved = happy(tmp_path)
    b.loc[0, "B01003_001_m"] = -222222222.0
    assert any("sentinel" in x for x in validate_artifacts(p, b, resolved, REGISTRY, min_rows=5)[0])


@pytest.mark.parametrize(
    ("drop", "fragment"),
    [("state", "state benchmark"), ("county", "county benchmark"), ("us", "national benchmark")],
)
def test_every_referenced_geography_needs_a_benchmark_row(
    tmp_path: Path, drop: str, fragment: str
) -> None:
    p, b, resolved = happy(tmp_path)
    victim = {"state": "30", "county": "30111", "us": "1"}[drop]
    b = b[~((b["geo_level"] == drop) & (b["geo_id"] == victim))]
    problems, _ = validate_artifacts(p, b, resolved, REGISTRY, min_rows=5)
    assert any(fragment in x for x in problems), problems


def test_an_unresolved_registry_variable_fails(tmp_path: Path) -> None:
    p, b, resolved = happy(tmp_path)
    del resolved["B19001_004"]
    problems, _ = validate_artifacts(p, b, resolved, REGISTRY, min_rows=5)
    assert any("B19001_004" in x and "resolved" in x for x in problems)


def test_a_missing_variable_column_fails(tmp_path: Path) -> None:
    p, b, resolved = happy(tmp_path)
    p = p.drop(columns=["B25003_002_m"])
    problems, _ = validate_artifacts(p, b, resolved, REGISTRY, min_rows=5)
    assert any("B25003_002_m" in x for x in problems)


def test_a_core_kpi_variable_under_95_percent_coverage_fails(tmp_path: Path) -> None:
    p, b, resolved = happy(tmp_path)
    p.loc[["33602", "33603"], "B11001_001_e"] = np.nan  # households: 4/6 = 67 % among pop > 0
    problems, coverage = validate_artifacts(p, b, resolved, REGISTRY, min_rows=5)
    assert coverage["B11001_001"] == pytest.approx(4 / 6)
    assert any("B11001_001" in x and "95" in x for x in problems)


def test_non_core_variables_may_have_gaps(tmp_path: Path) -> None:
    p, b, resolved = happy(tmp_path)
    p.loc[:, "DP03_UNINS_e"] = np.nan  # not a core KPI variable
    problems, _ = validate_artifacts(p, b, resolved, REGISTRY, min_rows=5)
    assert problems == []


def test_geometry_zips_must_be_a_subset_of_the_profile(tmp_path: Path) -> None:
    p, b, resolved = happy(tmp_path)
    problems, _ = validate_artifacts(
        p, b, resolved, REGISTRY, geo=geo_for([*ZCTAS, "99999"]), min_rows=5
    )
    assert any("99999" in x and "geometry" in x for x in problems)


def test_null_geometries_fail(tmp_path: Path) -> None:
    p, b, resolved = happy(tmp_path)
    geo = geo_for(ZCTAS)
    geo.loc[2, "geometry"] = None
    problems, _ = validate_artifacts(p, b, resolved, REGISTRY, geo=geo, min_rows=5)
    assert any("null" in x for x in problems)


def test_zctas_without_a_state_beyond_one_percent_fail(tmp_path: Path) -> None:
    p, b, resolved = happy(tmp_path)
    p.loc[["33602", "33603"], "state_fips"] = None
    problems, _ = validate_artifacts(p, b, resolved, REGISTRY, min_rows=5)
    assert any("no state" in x for x in problems)


# ------------------------------------------------------------------------------ the whole build
def test_a_build_writes_the_four_artifacts_with_text_zips(tmp_path: Path) -> None:
    result = run_build(tmp_path)
    data = tmp_path / "data"
    assert sorted(p.name for p in data.iterdir() if p.is_file()) == [
        "benchmarks.parquet", "metadata.json", "zcta_geo.parquet", "zcta_profile.parquet",
    ]  # fmt: skip
    profile = pd.read_parquet(data / "zcta_profile.parquet")
    assert profile["zip"].tolist() == ZCTAS  # leading zeros intact
    assert all(isinstance(z, str) for z in profile["zip"])
    assert profile.loc[profile["zip"] == "02108", "B19013_001_code"].iloc[0] == "top"
    geo = gpd.read_parquet(data / "zcta_geo.parquet")
    assert geo["zip"].tolist() == ZCTAS and geo.crs.to_epsg() == 4326
    bench = pd.read_parquet(data / "benchmarks.parquet")
    assert {"us", "state", "county"} == set(bench["geo_level"])
    assert result.paths["profile"] == data / "zcta_profile.parquet"


def test_metadata_records_the_build_without_any_key(tmp_path: Path) -> None:
    result = run_build(tmp_path)
    text = (tmp_path / "data" / "metadata.json").read_text(encoding="utf-8")
    meta = json.loads(text)
    assert meta["vintage"] == 2024 and meta["app_version"] == __version__
    assert meta["row_counts"]["zcta_profile"] == 6 and meta["row_counts"]["geometry"] == 6
    assert meta["variables"]["DP03_UNINS"]["id"] == "DP03_0099E"
    assert meta["coverage"]["B01003_001"] == 1.0
    assert meta["sentinel_counts"]["estimate:-666666666"] == 1
    assert meta["code_cross_check"]["B19013_001"]["top"] == {"count": 1, "values": [250001.0]}
    assert meta["geometry"]["source"] == "census_cartographic_boundary_2020_500k"
    assert meta["geometry"]["tolerance_deg"] == 0.002
    assert meta["dataset_urls"]["detailed"] == "https://api.census.gov/data/2024/acs/acs5"
    assert any(s["name"] == "county_relationship" for s in meta["sources"])
    assert "key=" not in text and KEY not in text
    assert "built_at" in meta and result.metadata["vintage"] == 2024


def test_a_failed_validation_writes_nothing_and_keeps_the_old_files(tmp_path: Path) -> None:
    data = tmp_path / "data"
    data.mkdir()
    old = data / "zcta_profile.parquet"
    old.write_bytes(b"previous build")
    with pytest.raises(BuildError) as exc:
        run_build(tmp_path, client=FakeClient(Synth(null_core=True)))
    assert exc.value.exit_code == 5 and "Nothing was written" in str(exc.value)
    assert old.read_bytes() == b"previous build"
    assert not (data / "metadata.json").exists()


def test_downloaded_files_are_cached_and_refresh_downloads_again(tmp_path: Path) -> None:
    session = FileSession(tmp_path)
    run_build(tmp_path, session=session)
    first = len(session.calls)
    assert first == 4  # boundaries, relationship, GeoNames US and PR
    run_build(tmp_path, session=session)
    assert len(session.calls) == first  # all cached
    run_build(tmp_path, session=session, refresh=True)
    assert len(session.calls) == first * 2
    sidecars = list((tmp_path / "data" / "raw").rglob("*.meta.json"))
    assert len(sidecars) == 4
    for s in sidecars:
        info = json.loads(s.read_text(encoding="utf-8"))
        assert info["url"].startswith("https://") and "key=" not in info["url"]


def test_a_failed_download_is_a_clear_error(tmp_path: Path) -> None:
    session = FileSession(tmp_path)
    session.files.pop(DEFAULT_SOURCES.county_rel_url)
    with pytest.raises(BuildError, match="HTTP 404"):
        run_build(tmp_path, session=session)


def test_acs_only_skips_the_geometry_download(tmp_path: Path) -> None:
    session = FileSession(tmp_path)
    run_build(tmp_path, session=session, only="acs")
    assert DEFAULT_SOURCES.zcta_url not in session.calls
    assert not (tmp_path / "data" / "zcta_geo.parquet").exists()
    assert (tmp_path / "data" / "zcta_profile.parquet").exists()


def test_no_geo_is_the_same_as_acs_only(tmp_path: Path) -> None:
    session = FileSession(tmp_path)
    run_build(tmp_path, session=session, no_geo=True)
    assert DEFAULT_SOURCES.zcta_url not in session.calls


def test_geo_only_needs_no_client_and_keeps_the_acs_metadata(tmp_path: Path) -> None:
    run_build(tmp_path, only="acs")
    build(
        tmp_path / "data", client=None, session=FileSession(tmp_path), registry=REGISTRY,
        only="geo", min_rows=5, tolerance=0.002,
    )  # fmt: skip
    meta = json.loads((tmp_path / "data" / "metadata.json").read_text(encoding="utf-8"))
    assert "variables" in meta and meta["geometry"]["source"].startswith(
        "census"
    )  # merged, not replaced
    assert (tmp_path / "data" / "zcta_geo.parquet").exists()


def test_zipcator_geometry_is_reused_when_its_schema_matches(tmp_path: Path) -> None:
    zc = tmp_path / "zcta.parquet"
    geo_for(ZCTAS).assign(other=1).to_parquet(zc)
    session = FileSession(tmp_path)
    run_build(tmp_path, session=session, zipcator_parquet=zc)
    assert DEFAULT_SOURCES.zcta_url not in session.calls
    meta = json.loads((tmp_path / "data" / "metadata.json").read_text(encoding="utf-8"))
    assert meta["geometry"]["source"] == "zipcator_parquet"


def test_a_mismatched_zipcator_file_falls_back_to_the_census_download(tmp_path: Path) -> None:
    zc = tmp_path / "zcta.parquet"
    geo_for(ZCTAS).rename(columns={"zip": "code"}).to_parquet(zc)
    session = FileSession(tmp_path)
    run_build(tmp_path, session=session, zipcator_parquet=zc)
    assert DEFAULT_SOURCES.zcta_url in session.calls
    meta = json.loads((tmp_path / "data" / "metadata.json").read_text(encoding="utf-8"))
    assert meta["geometry"]["source"] == "census_cartographic_boundary_2020_500k"
    assert "zip" in meta["geometry"]["zipcator_parquet_skipped"]


def test_geometry_with_zips_missing_from_the_profile_fails_the_build(tmp_path: Path) -> None:
    session = FileSession(tmp_path, geo_zips=[*ZCTAS, "99999"])
    with pytest.raises(BuildError, match="99999"):
        run_build(tmp_path, session=session)


def test_registry_default_is_the_real_registry() -> None:
    from zipographics import metrics
    from zipographics.data_build import Registry

    reg = Registry.default()
    assert reg.variables is metrics.VARIABLES and reg.metrics == metrics.REGISTRY
    assert set(reg.core) == {"pop", "hh", "median_hh_income", "owner", "hh_kids"}
    assert reg.population == "B01003_001"
    assert BRACKETS  # imported for the synthetic registry
