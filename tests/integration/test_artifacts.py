"""Integration tests on the real built artifacts (marker ``data``; SPEC §9.3).

Run after the data build: ``uv run pytest -m data``. They read ``data/`` (never the network).
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest

from zipographics import data, metrics, profile, stats
from zipographics.data import facts_from_profile
from zipographics.review import review_lines, summarize
from zipographics.zips import parse_paste

pytestmark = pytest.mark.data
DATA = Path(__file__).resolve().parents[2] / "data"

if not (DATA / "zcta_profile.parquet").exists():  # pragma: no cover - only without a build
    pytest.skip("data/ has not been built (run scripts/build_data.py)", allow_module_level=True)


@pytest.fixture(scope="module")
def artifacts() -> data.Artifacts:
    return data.load(DATA)


@pytest.fixture(scope="module")
def prof(artifacts: data.Artifacts) -> pd.DataFrame:
    return artifacts.profile


@pytest.fixture(scope="module")
def bench(artifacts: data.Artifacts) -> pd.DataFrame:
    return artifacts.benchmarks


def national(bench: pd.DataFrame, ids: list[str]) -> dict[str, float | None]:
    p = profile.benchmark_profile(bench, "us", "1", metric_ids=ids)
    return {i: p.values[i].estimate for i in ids}


# ------------------------------------------------------------------------------ smoke
def test_row_counts_and_zip_text(prof: pd.DataFrame, artifacts: data.Artifacts) -> None:
    assert len(prof) >= 33_000
    assert prof.index.is_unique
    assert all(isinstance(z, str) and re.fullmatch(r"[0-9]{5}", z) for z in prof.index)
    assert {"00601", "02108", "33602", "99501"} <= set(prof.index)  # PR, Boston, Tampa, Anchorage
    assert artifacts.metadata["row_counts"]["zcta_profile"] == len(prof)


def test_33601_is_not_a_zcta_and_is_reported_as_not_found(prof: pd.DataFrame) -> None:
    # SPEC §5.4 / golden scenario 8: a PO-box or unique ZIP has no ZCTA, so no Census data
    assert "33601" not in prof.index
    summary = summarize(parse_paste("33602 33601 2108"), facts_from_profile(prof))
    assert summary.not_found == ("33601",)
    assert summary.recognized == ("33602", "02108")
    assert any("1 repaired" in line for line in review_lines(summary))


def test_every_registry_column_exists_in_both_tables(
    prof: pd.DataFrame, bench: pd.DataFrame
) -> None:
    for key, var in metrics.VARIABLES.items():
        for table in (prof, bench):
            assert f"{key}_e" in table.columns and f"{key}_m" in table.columns, key
        if var.is_median:
            assert f"{key}_code" in prof.columns


def test_no_sentinel_or_infinity_in_any_numeric_column(
    prof: pd.DataFrame, bench: pd.DataFrame
) -> None:
    for name, frame in (("profile", prof), ("benchmarks", bench)):
        numbers = frame.select_dtypes("number")
        assert not (numbers.fillna(0) <= -100_000_000).any().any(), name
        assert np.isfinite(numbers.fillna(0).to_numpy()).all(), name


def test_benchmarks_are_complete(
    prof: pd.DataFrame, bench: pd.DataFrame, artifacts: data.Artifacts
) -> None:
    assert (bench["geo_level"] == "us").sum() == 1
    states = set(bench.loc[bench["geo_level"] == "state", "geo_id"])
    counties = set(bench.loc[bench["geo_level"] == "county", "geo_id"])
    assert len(states) == 52  # 50 states + DC + Puerto Rico
    assert set(prof["state_fips"].dropna()) <= states
    assert set(prof["county_fips"].dropna()) <= counties
    gaps = artifacts.metadata["county_benchmark_gaps"]
    assert gaps["states"] == ["CT"] and gaps["zctas"] == int(
        (prof["county"].notna() & prof["county_fips"].isna()).sum()
    )
    assert all(isinstance(g, str) for g in bench["geo_id"])


def test_metadata_is_key_free_and_complete(artifacts: data.Artifacts) -> None:
    text = (DATA / "metadata.json").read_text(encoding="utf-8")
    assert "key=" not in text and "CENSUS_API_KEY" not in text
    meta = artifacts.metadata
    assert meta["vintage"] == 2024 and meta["app_version"]
    assert len(meta["variables"]) == len(metrics.VARIABLES)
    assert not [k for k, v in meta["variables"].items() if v["moved"]]


def test_the_map_covers_the_profile_within_the_size_target(
    artifacts: data.Artifacts, prof: pd.DataFrame
) -> None:
    geo = artifacts.geo
    assert isinstance(geo, gpd.GeoDataFrame) and geo.crs.to_epsg() == 4326
    assert set(geo["zip"]) <= set(prof.index) and geo["zip"].is_unique
    assert geo.geometry.notna().all() and geo.geometry.is_valid.all()
    assert len(geo) / len(prof) > 0.99
    assert (DATA / "zcta_geo.parquet").stat().st_size <= 30 * 1024 * 1024  # SPEC §4.3 (about 30 MB)
    assert (DATA / "zcta_profile.parquet").stat().st_size < 60 * 1024 * 1024


# ------------------------------------------------------------------------------ plausibility
def test_national_benchmarks_are_plausible(bench: pd.DataFrame) -> None:
    n = national(
        bench,
        ["pop", "hh", "owner", "renter", "median_hh_income", "median_age", "poverty", "hh_kids",
         "ba_plus", "veh_per_hh", "mean_hh_income", "broadband", "uninsured", "hispanic"],
    )  # fmt: skip
    assert 330e6 < n["pop"] < 340e6  # type: ignore[operator]
    assert 125e6 < n["hh"] < 135e6  # type: ignore[operator]
    assert 0.62 < n["owner"] < 0.68 and abs(n["owner"] + n["renter"] - 1) < 1e-9  # type: ignore[operator]
    assert 70_000 < n["median_hh_income"] < 90_000  # type: ignore[operator]
    assert 37 < n["median_age"] < 40.5  # type: ignore[operator]
    assert 0.11 < n["poverty"] < 0.15 and 0.28 < n["hh_kids"] < 0.34  # type: ignore[operator]
    assert 0.33 < n["ba_plus"] < 0.40  # type: ignore[operator]
    assert 1.5 < n["veh_per_hh"] < 2.0  # type: ignore[operator]
    assert 90_000 < n["mean_hh_income"] < 130_000  # type: ignore[operator]
    assert 0.85 < n["broadband"] < 0.95 and 0.04 < n["uninsured"] < 0.12  # type: ignore[operator]
    assert 0.17 < n["hispanic"] < 0.20  # type: ignore[operator]


def test_a_single_zcta_shows_its_published_values(prof: pd.DataFrame) -> None:
    tampa = profile.build_profile(
        prof, ["33602"], metric_ids=["pop", "hh", "median_hh_income", "owner"]
    )
    v = tampa.values
    assert v["pop"].estimate and v["pop"].estimate > 1_000 and v["pop"].source == "published"
    assert v["median_hh_income"].estimate and 20_000 < v["median_hh_income"].estimate < 200_000
    assert 0 <= v["owner"].estimate <= 1  # type: ignore[operator]
    assert v["pop"].estimate == pytest.approx(float(prof.loc["33602", "B01003_001_e"]))


# ---------------------------------------------------------------------- resolution integrity
def populated(prof: pd.DataFrame, keys: list[str]) -> pd.DataFrame:
    sub = prof[prof["B01003_001_e"] > 0]
    return sub.dropna(subset=[f"{k}_e" for k in keys])


def test_race_shares_partition_the_population(prof: pd.DataFrame) -> None:
    ids = [
        "race_white",
        "race_black",
        "race_aian",
        "race_asian",
        "race_nhpi",
        "race_other",
        "race_two_plus",
    ]
    sample = populated(prof, ["B02001_001", *[f"B02001_{n:03d}" for n in range(2, 9)]]).index[:4000]
    table = profile.zip_table(prof, list(sample), metric_ids=ids)
    total = sum(table.columns[i].est for i in ids)
    assert (
        np.nanmax(np.abs(total - 1)) < 1e-9
    )  # shares of one-race-alone and two-or-more sum to 100 %


def test_income_age_and_housing_age_bands_partition_their_universes(prof: pd.DataFrame) -> None:
    inc = [
        "inc_lt25",
        "inc_25_50",
        "inc_50_75",
        "inc_75_100",
        "inc_100_150",
        "inc_150_200",
        "inc_200p",
    ]
    age = [
        "age_0_17",
        "age_18_24",
        "age_25_34",
        "age_35_44",
        "age_45_54",
        "age_55_64",
        "age_65_74",
        "age_75p",
    ]
    built = ["built_2010p", "built_1980_2009", "built_1960_1979", "built_pre1960"]
    table = profile.zip_table(prof, list(prof.index), metric_ids=[*inc, *age, *built])
    for group in (inc, age, built):
        total = sum(np.nan_to_num(table.columns[i].est, nan=np.nan) for i in group)
        ok = ~np.isnan(total)
        assert ok.mean() > 0.95
        assert np.abs(total[ok] - 1).max() < 1e-6, group


def test_derived_groups_equal_the_sum_of_their_bands(prof: pd.DataFrame) -> None:
    ids = [
        "age_18_34", "age_18_24", "age_25_34", "age_65p", "age_65_74", "age_75p",
        "inc_100p", "inc_100_150", "inc_150_200", "inc_200p", "owner", "renter",
    ]  # fmt: skip
    t = profile.zip_table(prof, list(prof.index), metric_ids=ids)
    c = t.columns
    assert np.nanmax(np.abs(c["age_18_34"].est - (c["age_18_24"].est + c["age_25_34"].est))) < 1e-9
    assert np.nanmax(np.abs(c["age_65p"].est - (c["age_65_74"].est + c["age_75p"].est))) < 1e-9
    inc = c["inc_100_150"].est + c["inc_150_200"].est + c["inc_200p"].est
    assert np.nanmax(np.abs(c["inc_100p"].est - inc)) < 1e-9
    both = c["owner"].est + c["renter"].est
    assert np.nanmax(np.abs(both[~np.isnan(both)] - 1)) < 1e-9


def test_zcta_populations_roughly_add_up_to_the_nation(
    prof: pd.DataFrame, bench: pd.DataFrame
) -> None:
    zcta_total = float(prof["B01003_001_e"].sum())
    us = float(bench.loc[bench["geo_level"] == "us", "B01003_001_e"].iloc[0])
    assert 0.97 < zcta_total / us < 1.03  # ZCTAs approximate (not equal) the 50 states + DC + PR


def test_top_and_bottom_coded_medians_are_flagged(
    prof: pd.DataFrame, artifacts: data.Artifacts
) -> None:
    cc = artifacts.metadata["code_cross_check"]
    assert cc["B19013_001"]["top"]["values"] == [250001.0] and cc["B19013_001"]["top"]["count"] > 50
    assert cc["B25077_001"]["top"]["values"] == [2000001.0]
    assert cc["B25064_001"]["top"]["values"] == [3501.0]
    coded = prof[prof["B19013_001_code"] == "top"]
    assert (coded["B19013_001_e"] == 250001).all() and coded["B19013_001_m"].isna().all()
    assert set(prof["B19013_001_code"]) <= {"none", "top", "bottom"}


# ---------------------------------------------------------------------- median gap (SPEC 6.4)
def test_interpolated_medians_track_the_published_ones_and_their_moes_are_sane(
    prof: pd.DataFrame, capsys: pytest.CaptureFixture[str]
) -> None:
    metric = "median_hh_income"
    sample_pool = prof[
        (prof["B11001_001_e"] >= 200)
        & prof["B19013_001_e"].notna()
        & (prof["B19013_001_code"] == "none")
    ]
    sample = sample_pool.sample(1500, random_state=12345).index
    pub, interp, moe_pub, moe_int = [], [], [], []
    for z in sample:
        v = profile.bracket_median(prof, [z], metric)
        if v.estimate is None or v.code != "none":
            continue
        pub.append(float(prof.loc[z, "B19013_001_e"]))
        moe_pub.append(float(prof.loc[z, "B19013_001_m"]))
        interp.append(v.estimate)
        moe_int.append(np.nan if v.moe is None else v.moe)
    pub_a, int_a = np.array(pub), np.array(interp)
    gap = np.abs(int_a - pub_a) / pub_a * 100
    ratio = np.array(moe_int) / np.array(moe_pub)
    ratio = ratio[np.isfinite(ratio)]
    report = (
        f"MEDIAN GAP n={len(gap)}: median {np.median(gap):.2f}%  "
        f"p95 {np.percentile(gap, 95):.2f}%  "
        f"max {gap.max():.1f}% | MOE ratio (interpolated / published) "
        f"median {np.median(ratio):.2f} "
        f"p10 {np.percentile(ratio, 10):.2f} p90 {np.percentile(ratio, 90):.2f} (n={len(ratio)})"
    )
    with capsys.disabled():
        print("\n" + report)
    assert np.median(gap) < 5.0 and np.percentile(gap, 95) < 15.0
    assert 0.3 < np.median(ratio) < 3.0


# ------------------------------------------------------------------------------ app-facing
def test_facts_feed_the_review_screen_for_a_boston_paste(prof: pd.DataFrame) -> None:
    facts = facts_from_profile(prof)
    text = "2108, 2109, 2110, 2111, 2113, 2114, 2115, 2116"  # Excel-mangled 02108-02116
    s = summarize(parse_paste(text), facts)
    assert len(s.recognized) == 8 and s.states == ("MA",) and s.benchmark_state == "MA"
    assert len(s.repaired) == 8 and s.repaired_unexpected_state == ()


def test_profile_for_a_thousand_real_zips_fits_the_budget(
    prof: pd.DataFrame, bench: pd.DataFrame
) -> None:
    zips = list(prof.index[prof["B01003_001_e"] > 0][:1000])
    base = profile.benchmark_profile(bench, "us", "1")
    start = time.perf_counter()
    trade = profile.build_profile(prof, zips, weights={z: 0.9 for z in zips})
    table = profile.zip_table(prof, zips)
    idx = profile.index_profile(trade, base)
    for m in metrics.REGISTRY:
        table.index_column(m.id, base.values[m.id].estimate)
    assert time.perf_counter() - start <= 1.0 and len(idx) > 50
    assert stats.index_value(1.0, 1.0) == 100


def test_loading_the_artifacts_is_fast_enough() -> None:
    start = time.perf_counter()
    data.load(DATA)
    assert time.perf_counter() - start <= 6.0  # SPEC §7: <= 3 s cold on the target laptop; CI slack
    assert json.loads((DATA / "metadata.json").read_text(encoding="utf-8"))["vintage"] == 2024
