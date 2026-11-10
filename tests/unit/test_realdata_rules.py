"""Build rules that the first real Census data forced (Phase 4; DECISIONS B16).

* Published medians are suppressed by the ACS for small areas, so they get their own coverage floor.
* ACS 2022+ publishes Connecticut by planning region while the 2020 relationship file still uses the
  old counties: those ZCTAs keep their county name but get no county benchmark.
* The boundary file includes island-area ZCTAs (VI, GU, MP, AS) that have no ACS data: they are
  dropped from the map, a few at most.
"""

from __future__ import annotations

import json
import warnings
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import box
from synth_acs import (
    COUNTIES,
    REGISTRY,
    ZCTA_COUNTY,
    ZCTAS,
    FakeClient,
    FileSession,
)

from zipographics import config, data_build
from zipographics.data_build import (
    DEFAULT_SOURCES,
    BuildError,
    acs_artifacts,
    build,
    validate_artifacts,
)
from zipographics.sentinels import clean_frame


def run_build(tmp_path: Path, session: Any, **kw: Any) -> Any:
    return build(
        tmp_path / "data", client=FakeClient(), session=session, registry=REGISTRY,
        min_rows=5, tolerance=0.002, **kw,
    )  # fmt: skip


def relationship_with(county_for: dict[str, str]) -> bytes:
    cols = [
        "GEOID_ZCTA5_20",
        "GEOID_COUNTY_20",
        "NAMELSAD_COUNTY_20",
        "AREALAND_PART",
        "AREAWATER_PART",
    ]
    lines = ["|".join(cols)]
    for z, c in {**ZCTA_COUNTY, **county_for}.items():
        lines.append(
            "|".join([z, c, COUNTIES.get(c, "Old County, State").split(",")[0], "1000", "10"])
        )
    return ("\n".join(lines) + "\n").encode("utf-8")


# ------------------------------------------------------------------------- published medians
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
    return big, art.benchmarks, art.resolved


def test_published_medians_have_their_own_ninety_percent_floor(tmp_path: Path) -> None:
    big, bench, resolved = clones(tmp_path)
    assert config.MEDIAN_COVERAGE_FLOOR == 0.90 and config.COVERAGE_FLOOR == 0.95
    big.iloc[:8, big.columns.get_loc("B19013_001_e")] = np.nan  # 92 % present, like the real data
    problems, coverage = validate_artifacts(big, bench, resolved, REGISTRY, min_rows=5)
    assert coverage["B19013_001"] == pytest.approx(0.92)
    assert problems == []


def test_a_median_below_ninety_percent_still_fails(tmp_path: Path) -> None:
    big, bench, resolved = clones(tmp_path)
    big.iloc[:12, big.columns.get_loc("B19013_001_e")] = np.nan  # 88 %
    problems, _ = validate_artifacts(big, bench, resolved, REGISTRY, min_rows=5)
    assert any("B19013_001" in p and "90%" in p for p in problems)


def test_counts_and_shares_keep_the_ninety_five_percent_floor(tmp_path: Path) -> None:
    big, bench, resolved = clones(tmp_path)
    big.iloc[:8, big.columns.get_loc("B25003_002_e")] = np.nan  # 92 % present
    problems, _ = validate_artifacts(big, bench, resolved, REGISTRY, min_rows=5)
    assert any("B25003_002" in p and "95%" in p for p in problems)


# ------------------------------------------------------------------------- county benchmark gaps
def test_a_county_without_an_acs_row_keeps_its_name_but_loses_its_fips(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(config, "COUNTY_GAP_LIMIT", 0.5)  # the synthetic data has 6 ZCTAs
    session = FileSession(tmp_path)
    session.files[DEFAULT_SOURCES.county_rel_url] = relationship_with({"33603": "12999"})
    art = acs_artifacts(
        FakeClient(), 2024, REGISTRY, session, tmp_path / "raw", False, DEFAULT_SOURCES
    )
    assert pd.isna(art.profile.loc["33603", "county_fips"])
    assert art.profile.loc["33603", "county"] == "Old County"  # the name is still shown
    assert art.profile.loc["33603", "state"] == "FL"  # the state benchmark is unaffected
    assert art.profile.loc["33602", "county_fips"] == "12057"
    assert art.county_gaps == {"zctas": 1, "county_fips": ["12999"], "states": ["FL"]}


def test_the_gap_is_recorded_in_the_metadata_and_the_build_passes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(config, "COUNTY_GAP_LIMIT", 0.5)
    session = FileSession(tmp_path)
    session.files[DEFAULT_SOURCES.county_rel_url] = relationship_with({"33603": "12999"})
    run_build(tmp_path, session)
    meta = json.loads((tmp_path / "data" / "metadata.json").read_text(encoding="utf-8"))
    assert meta["county_benchmark_gaps"] == {"zctas": 1, "county_fips": ["12999"], "states": ["FL"]}


def test_too_many_county_gaps_fail_the_build(tmp_path: Path) -> None:
    session = FileSession(tmp_path)
    session.files[DEFAULT_SOURCES.county_rel_url] = relationship_with(
        {"33603": "12999", "33602": "12998"}
    )
    with pytest.raises(BuildError, match="county benchmark"):
        run_build(tmp_path, session)  # 2 of 6 ZCTAs (33 %) is far above the 2 % limit


def test_no_gaps_means_an_empty_record(tmp_path: Path) -> None:
    art = acs_artifacts(
        FakeClient(),
        2024,
        REGISTRY,
        FileSession(tmp_path),
        tmp_path / "raw",
        False,
        DEFAULT_SOURCES,
    )
    assert art.county_gaps == {"zctas": 0, "county_fips": [], "states": []}


# ------------------------------------------------------------------------- island-area polygons
def read_zips(path: Path) -> list[str]:
    return list(gpd.read_parquet(path)["zip"])


def test_polygons_without_a_profile_row_are_dropped_and_recorded(tmp_path: Path) -> None:
    run_build(tmp_path, FileSession(tmp_path, geo_zips=[*ZCTAS, "00802", "00820"]))
    assert read_zips(tmp_path / "data" / "zcta_geo.parquet") == ZCTAS
    meta = json.loads((tmp_path / "data" / "metadata.json").read_text(encoding="utf-8"))
    assert meta["geometry"]["dropped_without_profile"] == ["00802", "00820"]
    assert meta["row_counts"]["geometry"] == 6


def test_a_boundary_file_with_many_unmatched_polygons_is_rejected(tmp_path: Path) -> None:
    extras = [f"{20000 + i}" for i in range(config.MAX_GEOMETRY_EXTRA + 1)]
    with pytest.raises(BuildError, match="polygons with no profile row"):
        run_build(tmp_path, FileSession(tmp_path, geo_zips=[*ZCTAS, *extras]))


def test_geo_only_drops_polygons_missing_from_the_profile_on_disk(tmp_path: Path) -> None:
    build(tmp_path / "data", client=FakeClient(), session=FileSession(tmp_path), registry=REGISTRY,
          min_rows=5, only="acs")  # fmt: skip
    build(tmp_path / "data", client=None, session=FileSession(tmp_path, geo_zips=[*ZCTAS, "99999"]),
          registry=REGISTRY, only="geo", min_rows=5)  # fmt: skip
    assert read_zips(tmp_path / "data" / "zcta_geo.parquet") == ZCTAS


def test_a_truncated_map_is_still_rejected(tmp_path: Path) -> None:
    with pytest.raises(BuildError, match="covers only"):
        run_build(tmp_path, FileSession(tmp_path, geo_zips=ZCTAS[:2]))


def test_drop_helper_returns_the_dropped_zips_in_order() -> None:
    geo = gpd.GeoDataFrame(
        {"zip": ["A", "B", "C"]}, geometry=[box(0, 0, 1, 1)] * 3, crs="EPSG:4326"
    )
    kept, dropped = data_build.drop_unprofiled(geo, {"A", "C"})
    assert list(kept["zip"]) == ["A", "C"] and dropped == ["B"]


# ------------------------------------------------------------------------- no pandas warnings
def test_cleaning_hundreds_of_variables_does_not_fragment_the_frame() -> None:
    n = 300
    raw = {"zcta": ["02108", "00601"]}
    for i in range(n):
        raw[f"B{i:05d}_001E"] = ["1", "2"]
        raw[f"B{i:05d}_001M"] = ["1", "1"]
    variables = {f"B{i:05d}_001": False for i in range(n)}
    with warnings.catch_warnings():
        warnings.simplefilter("error")  # PerformanceWarning would raise
        out, _ = clean_frame(pd.DataFrame(raw), key="zcta", variables=variables)
    assert out.shape == (2, 2 * n)
