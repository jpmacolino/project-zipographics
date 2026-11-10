"""Corruption-catching checks on the real built artifacts (marker ``data``; Phase 4 QA finding 2).

The first data tests passed on artifacts with every ``_code`` column set to "none", owner and
renter columns swapped, a column scaled 10x and a relabelled map CRS. These tests would not:

* cross-table totals must agree ZCTA by ZCTA;
* an independent parser re-reads the raw API responses cached in ``data/raw`` and compares them
  with the published parquet cell by cell (sentinel rules written out again, not imported);
* the map is checked by point-in-polygon against known locations;
* hand-checked literal values pin a few ZCTAs.

The folder is ``config.data_dir()`` (``ZIPOGRAPHICS_DATA_DIR`` overrides it), so a mutated copy of
``data/`` can be tested to prove each check fails on it.
"""

from __future__ import annotations

import json
from collections import defaultdict
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import Point

from zipographics import config, data, metrics, profile

pytestmark = pytest.mark.data
DATA = config.data_dir()

if not (DATA / "zcta_profile.parquet").exists():  # pragma: no cover - only without a build
    pytest.skip("data/ has not been built (run scripts/build_data.py)", allow_module_level=True)

SENTINELS = {-666666666, -999999999, -888888888, -222222222, -333333333, -555555555}
MOE_NULL = {-666666666, -999999999, -888888888, -222222222, -333333333}


@pytest.fixture(scope="module")
def artifacts() -> data.Artifacts:
    return data.load(DATA)


@pytest.fixture(scope="module")
def prof(artifacts: data.Artifacts) -> pd.DataFrame:
    return artifacts.profile


@pytest.fixture(scope="module")
def bench(artifacts: data.Artifacts) -> pd.DataFrame:
    return artifacts.benchmarks


# ------------------------------------------------------------------ cross-table totals
def disagreement(prof: pd.DataFrame, a: str, b: str) -> float:
    both = prof[[f"{a}_e", f"{b}_e"]].dropna()
    assert len(both) > 30_000, f"{a}/{b} are barely populated"
    return float((both.iloc[:, 0] != both.iloc[:, 1]).mean())


@pytest.mark.parametrize("other", ["B01001_001", "B02001_001", "B03003_001"])
def test_total_population_agrees_across_tables(prof: pd.DataFrame, other: str) -> None:
    assert disagreement(prof, "B01003_001", other) < 0.001


@pytest.mark.parametrize(
    "other",
    ["B25003_001", "B19001_001", "B25044_001", "B25038_001", "B28002_001", "B11005_001"],
)
def test_household_totals_agree_across_tables(prof: pd.DataFrame, other: str) -> None:
    assert disagreement(prof, "B11001_001", other) < 0.005


def test_owner_and_renter_counts_add_to_occupied_units(prof: pd.DataFrame) -> None:
    both = prof[["B25003_002_e", "B25003_003_e", "B25003_001_e"]].dropna()
    assert (both.iloc[:, 0] + both.iloc[:, 1] == both.iloc[:, 2]).mean() > 0.999
    # and owners are the majority nationally (a swapped column pair would flip this)
    assert both["B25003_002_e"].sum() > both["B25003_003_e"].sum()


def test_male_and_female_age_cells_add_to_the_total_population(prof: pd.DataFrame) -> None:
    male = [f"B01001_{n:03d}" for n in range(3, 26)]
    female = [f"B01001_{n:03d}" for n in range(27, 50)]
    cols = [f"{c}_e" for c in (*male, *female)]
    sub = prof[prof["B01001_001_e"] > 0].dropna(subset=[*cols, "B01001_001_e"])
    assert len(sub) > 30_000
    assert ((sub[cols].sum(axis=1) == sub["B01001_001_e"]).mean()) > 0.999


def test_a_published_median_lies_between_its_bracket_bounds(prof: pd.DataFrame) -> None:
    # household income: bottom code 2,499 ("2,500-"), top code 250,001 ("250,000+")
    m = prof["B19013_001_e"].dropna()
    assert m.between(2_499, 250_001).all()
    assert (m[prof["B19013_001_code"] != "none"].isin([2_499, 250_001])).all()
    age = prof["B01002_001_e"].dropna()
    assert (
        age.between(0, 100).all() and age.between(15, 80).mean() > 0.99
    )  # dorm and retirement ZIPs


# ------------------------------------------------------------------ the _code columns
def test_code_counts_and_annotated_moes_are_paired(
    prof: pd.DataFrame, artifacts: data.Artifacts
) -> None:
    meta = artifacts.metadata
    cross = meta["code_cross_check"]
    total_coded = 0
    for key, var in metrics.VARIABLES.items():
        if not var.is_median:
            continue
        coded = prof[prof[f"{key}_code"] != "none"]
        total_coded += len(coded)
        assert coded[f"{key}_m"].isna().all(), key  # a coded median carries no margin of error
        counts = cross[key]["top"]["count"] + cross[key]["bottom"]["count"]
        assert counts == int(coded[f"{key}_e"].notna().sum()), key
    assert total_coded > 500  # top-coded incomes, home values and rents are common
    assert meta["sentinel_counts"].get("moe:-333333333", 0) > 0  # the coded medians' MOEs
    assert meta["sentinel_counts"].get("estimate:-666666666", 0) > 0


def test_null_json_cells_are_counted_in_the_metadata(artifacts: data.Artifacts) -> None:
    counts = artifacts.metadata["sentinel_counts"]
    assert counts.get("estimate:null", 0) > 0 and counts.get("moe:null", 0) > 0


def test_the_metadata_states_its_coverage_basis_and_map_note(
    artifacts: data.Artifacts, prof: pd.DataFrame
) -> None:
    basis = artifacts.metadata["coverage_basis"]
    assert basis["zctas_total"] == len(prof)
    assert basis["zctas_with_population"] == int((prof["B01003_001_e"] > 0).sum())
    assert "indicative" in artifacts.metadata["geometry"]["note"]


# ------------------------------------------------------------------ independent raw re-parse
def _num(text: Any) -> float:
    if text is None or str(text).strip().lower() in {"", "null", "none", "nan"}:
        return float("nan")
    return float(text)


def _est(text: Any) -> float:
    value = _num(text)
    return float("nan") if value in SENTINELS else value


def _moe(text: Any, estimate: float) -> float:
    if np.isnan(estimate):
        return float("nan")
    value = _num(text)
    if value == -555555555:
        return 0.0
    return float("nan") if value in MOE_NULL else value


def raw_zcta_cells() -> dict[str, dict[str, tuple[float, float]]]:
    """{ZCTA: {Census variable id: (estimate, moe)}} from the cached ZCTA-level responses."""
    cells: dict[str, dict[str, tuple[float, float]]] = defaultdict(dict)
    folder = DATA / "raw" / "acs"
    for meta_file in sorted(folder.rglob("*.meta.json")):
        url = json.loads(meta_file.read_text(encoding="utf-8")).get("url", "")
        if "zip%20code%20tabulation%20area" not in url:
            continue
        rows = json.loads(
            meta_file.with_name(meta_file.name.replace(".meta", "")).read_text("utf-8")
        )
        header = rows[0]
        zip_at = header.index("zip code tabulation area")
        names = [h[:-1] for h in header if h.endswith("E") and h[:-1] + "M" in header]
        for row in rows[1:]:
            record = cells[row[zip_at]]
            for name in names:
                estimate = _est(row[header.index(name + "E")])
                record[name] = (estimate, _moe(row[header.index(name + "M")], estimate))
    return cells


@pytest.fixture(scope="module")
def raw_cells() -> dict[str, dict[str, tuple[float, float]]]:
    cells = raw_zcta_cells()
    if len(cells) < 30_000:
        pytest.skip("data/raw has no cached ZCTA responses to compare against")
    return cells


def test_every_published_cell_equals_an_independent_parse_of_the_raw_responses(
    prof: pd.DataFrame,
    artifacts: data.Artifacts,
    raw_cells: dict[str, dict[str, tuple[float, float]]],
) -> None:
    rng = np.random.default_rng(20241109)
    sample = list(rng.choice(prof.index.to_numpy(), size=500, replace=False))
    sample += ["00601", "02108", "33602", "99501", "60601", "10001"]  # fixed anchors
    # Rare cases would be missed by a random sample (a mutant that turned every 0 margin of error
    # into null survived one): add every ZCTA with a controlled (0) margin, and samples of ZCTAs
    # with a null margin next to a real estimate and with a null estimate.
    zero_moe, null_moe, null_est = [], [], []
    for z, cells in raw_cells.items():
        if z not in prof.index:
            continue
        if any(m == 0 for _, m in cells.values()):
            zero_moe.append(z)
        elif any(np.isnan(m) and not np.isnan(e) for e, m in cells.values()):
            null_moe.append(z)
        elif any(np.isnan(e) for e, _ in cells.values()):
            null_est.append(z)
    assert len(zero_moe) >= 10  # the raw responses really do contain controlled estimates
    sample += zero_moe + sorted(null_moe)[:: max(1, len(null_moe) // 200)]
    sample += sorted(null_est)[:: max(1, len(null_est) // 200)]
    ids = {key: info["id"][:-1] for key, info in artifacts.metadata["variables"].items()}
    checked = 0
    for z in sample:
        for key, census_id in ids.items():
            if census_id not in raw_cells[z]:
                continue
            est, moe = raw_cells[z][census_id]
            got_e, got_m = float(prof.at[z, f"{key}_e"]), float(prof.at[z, f"{key}_m"])
            assert (np.isnan(est) and np.isnan(got_e)) or est == got_e, (z, key, est, got_e)
            assert (np.isnan(moe) and np.isnan(got_m)) or moe == got_m, (z, key, moe, got_m)
            checked += 1
    assert checked > 500 * 150  # most registry variables are cached at ZCTA level


def test_every_cached_zcta_is_in_the_profile(
    prof: pd.DataFrame, raw_cells: dict[str, dict[str, tuple[float, float]]]
) -> None:
    assert set(raw_cells) == set(prof.index)


# ------------------------------------------------------------------ the map
@pytest.mark.parametrize(
    ("zip_code", "lat", "lon"),
    [
        ("02108", 42.357, -71.063),  # Beacon Hill, Boston
        ("33602", 27.950, -82.460),  # downtown Tampa
        ("00901", 18.466, -66.105),  # Old San Juan
        ("99501", 61.217, -149.88),  # Anchorage
        ("10001", 40.750, -73.997),  # Chelsea, Manhattan
    ],
)
def test_a_zip_polygon_contains_its_known_location(
    artifacts: data.Artifacts, zip_code: str, lat: float, lon: float
) -> None:
    geo = artifacts.geo
    assert geo is not None
    shape = geo.loc[geo["zip"] == zip_code, "geometry"]
    if shape.empty:
        pytest.skip(f"{zip_code} is not in the map")
    point = Point(lon, lat)
    # simplification and the 500k file can move an edge; allow ~1 km
    assert shape.iloc[0].distance(point) < 0.01, zip_code


def test_map_polygons_sit_where_their_state_is(
    artifacts: data.Artifacts, prof: pd.DataFrame
) -> None:
    geo = artifacts.geo
    assert isinstance(geo, gpd.GeoDataFrame)
    centre = geo.geometry.representative_point()
    state = prof.loc[geo["zip"], "state"].to_numpy()
    lon, lat = centre.x.to_numpy(), centre.y.to_numpy()
    box = {"MA": (-73.6, -69.8, 41.2, 42.95), "FL": (-87.7, -79.9, 24.4, 31.1)}
    for abbr, (x0, x1, y0, y1) in box.items():
        mask = state == abbr
        assert mask.sum() > 100
        assert ((lon[mask] >= x0) & (lon[mask] <= x1) & (lat[mask] >= y0) & (lat[mask] <= y1)).all()


# ------------------------------------------------------------------ literal values
def test_boston_02108_literal_values(prof: pd.DataFrame) -> None:
    # values from the API's raw response for ZCTA 02108 (ACS 2020-2024): more owners than renters
    row = prof.loc["02108"]
    assert row["state"] == "MA" and row["state_fips"] == "25"
    assert row["county"] == "Suffolk County"
    assert row["B01003_001_e"] == 3794
    assert (row["B25003_001_e"], row["B25003_002_e"], row["B25003_003_e"]) == (1973, 999, 974)
    assert row["B19013_001_e"] == 212_928


def test_tampa_33602_is_in_hillsborough(prof: pd.DataFrame) -> None:
    row = prof.loc["33602"]
    assert row["state"] == "FL" and str(row["county"]).startswith("Hillsborough")


def test_san_juan_00901_is_puerto_rico(prof: pd.DataFrame) -> None:
    assert prof.loc["00901", "state"] == "PR" and prof.loc["00901", "state_fips"] == "72"


def test_state_populations_are_plausible(bench: pd.DataFrame) -> None:
    states = bench[bench["geo_level"] == "state"].set_index("geo_id")["B01003_001_e"]
    assert 38e6 < states["06"] < 40.5e6  # California
    assert 29e6 < states["48"] < 32e6  # Texas
    assert 0.5e6 < states["56"] < 0.7e6  # Wyoming
    assert 3e6 < states["72"] < 3.6e6  # Puerto Rico


def test_national_income_distribution_is_ordered(bench: pd.DataFrame) -> None:
    p = profile.benchmark_profile(bench, "us", "1", metric_ids=["inc_lt25", "inc_200p", "owner"])
    assert 0.1 < p.values["inc_lt25"].estimate < 0.25 < 0.3  # type: ignore[operator]
    assert 0.05 < p.values["inc_200p"].estimate < 0.15  # type: ignore[operator]


def test_race_shares_partition_a_random_sample_of_all_states(prof: pd.DataFrame) -> None:
    ids = ["race_white", "race_black", "race_aian", "race_asian", "race_nhpi", "race_other",
           "race_two_plus"]  # fmt: skip
    cells = ["B02001_001", *[f"B02001_{n:03d}" for n in range(2, 9)]]
    pool = prof[prof["B01003_001_e"] > 0].dropna(subset=[f"{c}_e" for c in cells])
    sample = list(pool.sample(3000, random_state=7).index)
    assert len(set(prof.loc[sample, "state"])) > 40  # not a one-region sample
    table = profile.zip_table(prof, sample, metric_ids=ids)
    total = sum(table.columns[i].est for i in ids)
    assert np.nanmax(np.abs(total - 1)) < 1e-9
