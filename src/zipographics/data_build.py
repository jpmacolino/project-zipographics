"""The data build: download, resolve, clean, join, validate and write the artifacts (SPEC §4).

Build-only; the running app never imports this module (an import-graph test enforces it). The
Census API key is handled in :mod:`zipographics.census_api`; nothing here sees or prints it.

Exit codes of ``scripts/build_data.py``: 0 success, 2 usage, 3 missing/rejected key, 4 network or
API failure, 5 validation failure (:class:`BuildError`).
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import os
import re
import sys
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import geopandas as gpd
import pandas as pd
import requests

from zipographics import __version__, config, metrics
from zipographics.census_api import (
    CensusApiError,
    CensusClient,
    MissingKeyError,
    RejectedKeyError,
    VarRequest,
)
from zipographics.errors import BuildError as BuildError  # re-exported
from zipographics.geo_build import (
    assemble_geometry,
    read_boundaries,
    read_county_relationship,
    read_geonames,
    read_zipcator_geometry,
)
from zipographics.metrics import MedianSpec, Metric, Var
from zipographics.redact import install_redaction, redact, uninstall_redaction
from zipographics.sentinels import UnknownSentinelError, clean_frame

logger = logging.getLogger(__name__)

Dataset = Literal["detailed", "profile"]
VarMeta = Mapping[str, str]  # one entry of variables.json: {"label": ..., "group": ...}


# ----------------------------------------------------------------------------- bracket bounds
_NUM = r"\$?([0-9][0-9,]*)"
_BOUND_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(rf"less than {_NUM}$", re.I), "below"),
    (re.compile(r"under ([0-9]+) years?$", re.I), "below"),
    (re.compile(rf"{_NUM} or more$", re.I), "above"),
    (re.compile(r"([0-9]+) years and over$", re.I), "above"),
    (re.compile(r"(?:built )?([0-9]{4}) or later$", re.I), "above"),
    (re.compile(r"(?:built )?([0-9]{4}) or earlier$", re.I), "earlier"),
    (re.compile(rf"(?:built )?{_NUM} to {_NUM}(?: years)?$", re.I), "range"),
    (re.compile(r"([0-9]+) and ([0-9]+) years$", re.I), "range"),
    (re.compile(r"([0-9]+) years$", re.I), "single"),
]


def _number(text: str) -> float:
    return float(text.replace(",", ""))


def parse_bounds(label: str) -> tuple[float, float] | None:
    """The [lo, hi) bounds a bracket label describes, using the continuous convention
    (``$10,000 to $14,999`` is [10,000, 15,000)); ``None`` if the label is not a bracket."""
    tail = label.split("!!")[-1].strip().rstrip(":").strip()
    for pattern, kind in _BOUND_PATTERNS:
        m = pattern.match(tail)
        if m is None:
            continue
        nums = [_number(g) for g in m.groups()]
        if kind == "below":
            return -math.inf, nums[0]
        if kind == "above":
            return nums[0], math.inf
        if kind == "earlier":
            return -math.inf, nums[0] + 1
        if kind == "range":
            return nums[0], nums[1] + 1
        return nums[0], nums[0] + 1  # single
    return None


def bounds_match(label: tuple[float, float], expected: tuple[float, float]) -> bool:
    """Does a label's bounds equal the registry's? An open lowest bracket in the label matches an
    expected lower bound of 0 (income, value, rent and age use 0, SPEC §6.4)."""
    if label[1] != expected[1]:
        return False
    return label[0] == expected[0] or (label[0] == -math.inf and expected[0] == 0)


# ----------------------------------------------------------------------------- resolution
@dataclass(frozen=True, slots=True)
class ResolvedVar:
    """A registry variable resolved to a concrete Census variable for this vintage."""

    key: str
    id: str  # the estimate variable, e.g. B19013_001E or DP03_0099E
    base_id: str  # id without the trailing E, used to build E/M/EA names
    label: str
    table: str
    dataset: Dataset
    moved: bool = False  # the registry's ID no longer carried this label; found by label

    def as_metadata(self) -> dict[str, object]:
        return {
            "id": self.id,
            "label": self.label,
            "table": self.table,
            "dataset": self.dataset,
            "moved": self.moved,
        }


def _is_estimate(info: VarMeta) -> bool:
    return str(info.get("label", "")).lower().startswith("estimate!!")


def _search(var: Var, meta: Mapping[str, VarMeta]) -> list[str]:
    """Estimate variables of the variable's table whose label matches its regex."""
    assert var.label is not None
    pattern = re.compile(var.label, re.IGNORECASE)
    return sorted(
        vid
        for vid, info in meta.items()
        if info.get("group") == var.table
        and _is_estimate(info)
        and vid.endswith("E")
        and pattern.search(str(info.get("label", "")))
    )


def resolve_variables(
    variables: Mapping[str, Var],
    meta: Mapping[Dataset, Mapping[str, VarMeta]],
    brackets: Sequence[MedianSpec],
) -> dict[str, ResolvedVar]:
    """Resolve each registry variable against ``variables.json`` and verify bracket bounds.

    IDs are primary for detailed tables, with the label regex as a guard; if an ID's label no
    longer matches (or the ID vanished) the variable is searched by label within its table.
    Data Profile items are resolved by label only. Missing, ambiguous or mismatched variables
    raise :class:`BuildError` naming the registry key.
    """
    resolved: dict[str, ResolvedVar] = {}
    for key, var in variables.items():
        dataset_meta = meta[var.dataset]
        found: str | None = None
        moved = False
        if var.resolve == "id":
            vid = f"{key}E"
            info = dataset_meta.get(vid)
            if info is not None and (
                var.label is None or re.search(var.label, str(info.get("label", "")), re.I)
            ):
                found = vid
            elif var.label is None:
                raise BuildError(
                    f"variable {key}: {vid} is not in the {var.dataset} variables for this "
                    "vintage (a bracket cell without a label cannot be searched). The ACS "
                    "table layout may have changed."
                )
        if found is None:
            if var.label is None:
                raise BuildError(f"variable {key} has no label pattern to resolve it by")
            candidates = _search(var, dataset_meta)
            if not candidates:
                raise BuildError(
                    f"variable {key}: no variable in table {var.table} matches the label "
                    f"pattern {var.label!r}. The ACS label may have changed; update the registry."
                )
            if len(candidates) > 1:
                raise BuildError(
                    f"variable {key}: label pattern {var.label!r} is ambiguous in table "
                    f"{var.table}: {', '.join(candidates)}."
                )
            found = candidates[0]
            moved = var.resolve == "id"
        resolved[key] = ResolvedVar(
            key=key,
            id=found,
            base_id=found[:-1],
            label=str(dataset_meta[found].get("label", "")),
            table=var.table,
            dataset=var.dataset,
            moved=moved,
        )

    for spec in brackets:
        for bracket in spec.brackets:
            for key in bracket.keys:
                label = resolved[key].label
                bounds = parse_bounds(label)
                if bounds is None or not bounds_match(bounds, (bracket.lo, bracket.hi)):
                    raise BuildError(
                        f"bracket {key} ({resolved[key].id}) has label {label!r}, which does not "
                        f"match the expected bounds [{bracket.lo}, {bracket.hi}). The ACS "
                        "brackets may have changed; update the registry."
                    )
    return resolved


# ----------------------------------------------------------------------------- configuration
@dataclass(frozen=True)
class Sources:
    """Where the non-API files come from (none of these URLs carries a key)."""

    zcta_url: str = "https://www2.census.gov/geo/tiger/GENZ2020/shp/cb_2020_us_zcta520_500k.zip"
    county_rel_url: str = (
        "https://www2.census.gov/geo/docs/maps-data/data/rel2020/zcta520/"
        "tab20_zcta520_county20_natl.txt"
    )
    geonames_us_url: str = "https://download.geonames.org/export/zip/US.zip"
    geonames_pr_url: str = "https://download.geonames.org/export/zip/PR.zip"


DEFAULT_SOURCES = Sources()
#: Douglas-Peucker tolerance in degrees for the map polygons. The map needs no area math, so this
#: is coarser than Zipcator's 0.0005 (~40 MB); Phase 4 measures the resulting file size.
DEFAULT_TOLERANCE = 0.002
MIN_ROWS = config.MIN_ZCTA_ROWS
_SENTINEL_FLOOR = -100_000_000
_STATE_GAP_LIMIT = 0.01  # more than 1 % of ZCTAs without a state means a broken join
_LEVELS = ("zcta", "state", "county", "us")
_GEO_SOURCE_CENSUS = "census_cartographic_boundary_2020_500k"


@dataclass(frozen=True)
class Registry:
    """What the build fetches: variables, the metrics that use them and the core KPI metrics."""

    variables: Mapping[str, Var]
    metrics: Sequence[Metric]
    core: Sequence[str]
    population: str  # key of the population variable (the "population > 0" filter)

    @classmethod
    def default(cls) -> Registry:
        return cls(metrics.VARIABLES, metrics.REGISTRY, config.CORE_METRICS, "B01003_001")


# ----------------------------------------------------------------------------- downloads
def _now() -> datetime:
    return datetime.now(UTC)


def _stamp(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def download_file(
    url: str,
    dest: Path,
    *,
    session: Any,
    refresh: bool = False,
    now: Callable[[], datetime] = _now,
) -> Path:
    """Download a key-free URL to ``dest`` (cached; ``refresh`` re-downloads) with a sidecar."""
    if dest.exists() and not refresh:
        logger.info("using cached %s (pass --refresh to re-download)", dest.name)
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    logger.info("downloading %s", url)
    failure: str | None = None
    response: Any = None
    try:
        response = session.get(url, timeout=(15, 300))
    except requests.RequestException as exc:
        failure = f"{type(exc).__name__}: {exc}"
    if failure is not None:
        raise BuildError(f"network error downloading {url}: {failure}. Check your connection.", 4)
    if response.status_code != 200:
        raise BuildError(
            f"{url} returned HTTP {response.status_code}. The data source may have moved: find the "
            "current official location, update the build and note it in docs/DECISIONS.md.",
            4,
        )
    part = dest.with_name(dest.name + ".part")
    part.write_bytes(response.content)
    part.replace(dest)
    sidecar = {"url": url, "downloaded_at": _stamp(now()), "bytes": len(response.content)}
    dest.with_name(dest.name + ".meta.json").write_text(json.dumps(sidecar), encoding="utf-8")
    logger.info("saved %s (%.1f MB)", dest.name, len(response.content) / 1e6)
    return dest


def _source_record(name: str, url: str, path: Path) -> dict[str, Any]:
    try:
        info = json.loads(path.with_name(path.name + ".meta.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        info = {}
    return {
        "name": name,
        "url": url,
        "downloaded_at": info.get("downloaded_at"),
        "bytes": info.get("bytes", path.stat().st_size if path.exists() else None),
    }


# ----------------------------------------------------------------------------- ACS levels
@dataclass(frozen=True)
class LevelData:
    data: pd.DataFrame  # indexed by geography id (text); columns <key>_e/_m/_code
    names: pd.Series | None  # display names (state/county/us only)
    sentinel_counts: dict[str, int]


def _geo_id(raw: pd.DataFrame, level: str) -> pd.Series:
    if level == "zcta":
        return raw["zip code tabulation area"].astype(str)
    if level == "state":
        return raw["state"].astype(str)
    if level == "county":
        return raw["state"].astype(str) + raw["county"].astype(str)
    return raw["us"].astype(str)


def fetch_level(
    client: Any,
    vintage: int,
    level: str,
    resolved: Mapping[str, ResolvedVar],
    variables: Mapping[str, Var],
) -> LevelData:
    """Fetch every resolved variable at one geography level, clean it and name columns by key."""
    frames: list[pd.DataFrame] = []
    counts: Counter[str] = Counter()
    names: pd.Series | None = None
    for dataset in ("detailed", "profile"):
        chosen = [r for r in resolved.values() if r.dataset == dataset]
        if not chosen:
            continue
        if len({r.base_id for r in chosen}) != len(chosen):
            raise BuildError(
                f"two registry variables resolved to the same {dataset} Census variable"
            )
        requests_ = [VarRequest(r.base_id, is_median=variables[r.key].is_median) for r in chosen]
        raw = client.fetch_table(dataset, vintage, level, requests_).copy()
        raw["geo_id"] = _geo_id(raw, level)
        if raw["geo_id"].duplicated().any():
            raise BuildError(f"the Census API returned duplicate {level} rows")
        if level != "zcta" and names is None and "NAME" in raw.columns:
            names = raw.set_index("geo_id")["NAME"]
        try:
            cleaned, level_counts = clean_frame(
                raw, key="geo_id", variables={r.base_id: variables[r.key].is_median for r in chosen}
            )
        except UnknownSentinelError as exc:
            raise BuildError(str(exc)) from None
        rename: dict[str, str] = {}
        for r in chosen:
            rename[f"{r.base_id}_e"] = f"{r.key}_e"
            rename[f"{r.base_id}_m"] = f"{r.key}_m"
            rename[f"{r.base_id}_code"] = f"{r.key}_code"
        frames.append(cleaned.rename(columns=rename))
        counts.update(level_counts)
    data = frames[0]
    for other in frames[1:]:
        if set(other.index) != set(data.index):
            raise BuildError(f"the detailed and profile datasets returned different {level} sets")
        data = data.join(other, how="left")
    data.index.name = "zip" if level == "zcta" else "geo_id"
    return LevelData(data, names, dict(counts))


@dataclass(frozen=True)
class AcsArtifacts:
    profile: pd.DataFrame  # indexed by zip
    benchmarks: pd.DataFrame
    resolved: dict[str, ResolvedVar]
    sentinel_counts: dict[str, int]
    sources: list[dict[str, Any]]


def acs_artifacts(
    client: Any,
    vintage: int,
    registry: Registry,
    session: Any,
    raw_dir: Path,
    refresh: bool,
    sources: Sources,
    now: Callable[[], datetime] = _now,
) -> AcsArtifacts:
    """Resolve variables, fetch all four geography levels, join attributes, build benchmarks."""
    meta: dict[Dataset, Mapping[str, VarMeta]] = {
        "detailed": client.fetch_variables(vintage, "detailed"),
        "profile": client.fetch_variables(vintage, "profile"),
    }
    bracket_specs = [m.spec for m in registry.metrics if isinstance(m.spec, MedianSpec)]
    resolved = resolve_variables(registry.variables, meta, bracket_specs)
    logger.info("resolved %d variables for ACS %s", len(resolved), vintage)

    levels: dict[str, LevelData] = {}
    for level in _LEVELS:
        levels[level] = fetch_level(client, vintage, level, resolved, registry.variables)
        logger.info("%s: %s rows", level, f"{len(levels[level].data):,}")

    rel_path = download_file(
        sources.county_rel_url, raw_dir / Path(sources.county_rel_url).name,
        session=session, refresh=refresh, now=now,
    )  # fmt: skip
    us_path = download_file(
        sources.geonames_us_url, raw_dir / Path(sources.geonames_us_url).name,
        session=session, refresh=refresh, now=now,
    )  # fmt: skip
    pr_path = download_file(
        sources.geonames_pr_url, raw_dir / Path(sources.geonames_pr_url).name,
        session=session, refresh=refresh, now=now,
    )  # fmt: skip
    rel = read_county_relationship(rel_path)
    geonames = pd.concat([read_geonames(us_path), read_geonames(pr_path)], ignore_index=True)
    geonames = geonames.drop_duplicates("zip", keep="first")  # the US file wins a conflict

    zcta = levels["zcta"].data
    attrs = rel.set_index("zip")[["state_fips", "state", "county_fips", "county"]]
    profile = zcta.join(attrs).join(geonames.set_index("zip")["city"])
    profile = profile[["state_fips", "state", "county_fips", "county", "city", *zcta.columns]]
    profile.index.name = "zip"

    parts = []
    for level in ("us", "state", "county"):
        lvl = levels[level]
        part = lvl.data.copy()
        part.insert(0, "name", (lvl.names.reindex(part.index) if lvl.names is not None else None))
        part.insert(0, "geo_id", part.index.astype(str))
        part.insert(0, "geo_level", level)
        parts.append(part)
    benchmarks = pd.concat(parts, ignore_index=True)

    totals: Counter[str] = Counter()
    for lvl in levels.values():
        totals.update(lvl.sentinel_counts)
    source_records = [
        _source_record("county_relationship", sources.county_rel_url, rel_path),
        _source_record("geonames_us", sources.geonames_us_url, us_path),
        _source_record("geonames_pr", sources.geonames_pr_url, pr_path),
    ]
    return AcsArtifacts(profile, benchmarks, resolved, dict(totals), source_records)


# ----------------------------------------------------------------------------- validation
def _core_keys(registry: Registry) -> list[str]:
    by_id = {m.id: m for m in registry.metrics}
    keys: dict[str, None] = {}
    for mid in registry.core:
        metric = by_id[mid]
        spec = metric.spec
        for key in (
            (spec.published,) if isinstance(spec, MedianSpec) else metrics.variable_keys(metric)
        ):
            keys.setdefault(key)
    return list(keys)


def validate_artifacts(
    profile: pd.DataFrame,
    benchmarks: pd.DataFrame,
    resolved: Mapping[str, ResolvedVar],
    registry: Registry,
    *,
    geo: gpd.GeoDataFrame | None = None,
    min_rows: int = MIN_ROWS,
) -> tuple[list[str], dict[str, float]]:
    """The SPEC §4.4 output checks. Returns (problems, per-variable coverage)."""
    problems: list[str] = []
    if len(profile) < min_rows:
        problems.append(f"only {len(profile):,} ZCTA rows; expected at least {min_rows:,}")
    zips = list(profile.index)
    if not all(isinstance(z, str) and re.fullmatch(r"[0-9]{5}", z) for z in zips):
        problems.append("zip values must be 5-digit strings")
    if not profile.index.is_unique:
        problems.append("duplicate ZIPs in the profile")

    unresolved = sorted(set(registry.variables) - set(resolved))
    for key in unresolved:
        problems.append(f"variable {key} was not resolved")
    for frame, name in ((profile, "profile"), (benchmarks, "benchmarks")):
        for key in registry.variables:
            for suffix in ("_e", "_m"):
                if f"{key}{suffix}" not in frame.columns:
                    problems.append(f"column {key}{suffix} is missing from the {name}")
        numbers = frame.select_dtypes("number")
        for col in numbers.columns:
            bad = int((numbers[col] <= _SENTINEL_FLOOR).sum())
            if bad:
                problems.append(f"{bad} sentinel value(s) survived in {name} column {col}")

    # every geography referenced by a ZCTA has a benchmark row
    levels = benchmarks["geo_level"] if "geo_level" in benchmarks.columns else pd.Series(dtype=str)
    if not (levels == "us").any():
        problems.append("no national benchmark row")
    for level, column in (("state", "state_fips"), ("county", "county_fips")):
        if column not in profile.columns:
            continue
        wanted = set(profile[column].dropna())
        have = set(benchmarks.loc[levels == level, "geo_id"])
        missing = sorted(wanted - have)
        if missing:
            problems.append(f"no {level} benchmark for {', '.join(missing[:5])}")
    if "state_fips" in profile.columns and len(profile):
        gap = float(profile["state_fips"].isna().mean())
        if gap > _STATE_GAP_LIMIT:
            problems.append(
                f"{gap:.1%} of ZCTAs have no state; the county relationship join failed"
            )

    # coverage among ZCTAs that have people
    coverage: dict[str, float] = {}
    pop_col = f"{registry.population}_e"
    if pop_col in profile.columns:
        populated = profile[profile[pop_col] > 0]
        for key in registry.variables:
            col = f"{key}_e"
            if col in profile.columns:
                coverage[key] = float(populated[col].notna().mean()) if len(populated) else 0.0
        for key in _core_keys(registry):
            share = coverage.get(key, 0.0)
            if share < config.COVERAGE_FLOOR:
                problems.append(
                    f"core KPI variable {key} is non-null for only {share:.1%} of ZCTAs with "
                    f"population (need {config.COVERAGE_FLOOR:.0%})"
                )
    else:
        problems.append(f"column {pop_col} is missing, so coverage cannot be checked")

    if geo is not None:
        extra = sorted(set(geo["zip"]) - set(zips))
        if extra:
            problems.append(f"geometry has ZIPs with no profile row: {', '.join(extra[:5])}")
        empty = int(geo.geometry.isna().sum() + geo.geometry.is_empty.sum())
        if empty:
            problems.append(f"{empty} null or empty geometries")
    return problems, coverage


def _code_cross_check(profile: pd.DataFrame, registry: Registry) -> dict[str, Any]:
    """Counts and bound values of top/bottom-coded published medians (DECISIONS V7)."""
    out: dict[str, Any] = {}
    for key, var in registry.variables.items():
        if not var.is_median or f"{key}_code" not in profile.columns:
            continue
        entry: dict[str, Any] = {}
        for kind in ("top", "bottom"):
            chosen = profile.loc[profile[f"{key}_code"] == kind, f"{key}_e"].dropna()
            entry[kind] = {
                "count": len(chosen),
                "values": sorted({float(v) for v in chosen})[:5],
            }
        out[key] = entry
    return out


# ----------------------------------------------------------------------------- orchestration
@dataclass(frozen=True)
class BuildResult:
    paths: dict[str, Path]
    metadata: dict[str, Any] = field(default_factory=dict)


def _write_atomic(path: Path, writer: Callable[[Path], None]) -> None:
    tmp = path.with_name(path.name + ".tmp")
    try:
        writer(tmp)
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)


def _geometry(
    sources: Sources,
    raw_dir: Path,
    session: Any,
    refresh: bool,
    tolerance: float,
    zipcator_parquet: Path | None,
    now: Callable[[], datetime],
) -> tuple[gpd.GeoDataFrame, dict[str, Any], list[dict[str, Any]]]:
    info: dict[str, Any] = {}
    records: list[dict[str, Any]] = []
    gdf: gpd.GeoDataFrame | None = None
    if zipcator_parquet is not None:
        gdf, reason = read_zipcator_geometry(zipcator_parquet)
        if gdf is not None:
            info = {
                "source": "zipcator_parquet",
                "tolerance_deg": None,
                "file": zipcator_parquet.name,
            }
            logger.info("reusing Zipcator geometry from %s", zipcator_parquet.name)
        else:
            info["zipcator_parquet_skipped"] = reason
            logger.info("not reusing Zipcator geometry: %s", reason)
    if gdf is None:
        path = download_file(
            sources.zcta_url, raw_dir / Path(sources.zcta_url).name,
            session=session, refresh=refresh, now=now,
        )  # fmt: skip
        gdf = assemble_geometry(read_boundaries(path), tolerance)
        info.update(
            source=_GEO_SOURCE_CENSUS,
            tolerance_deg=tolerance,
            method="shapely.coverage_simplify (shared edges simplified once)",
        )
        records.append(_source_record("zcta_boundaries", sources.zcta_url, path))
    return gdf, info, records


def _write_parquet(frame: pd.DataFrame, path: Path) -> None:
    def write(tmp: Path) -> None:
        frame.to_parquet(tmp, compression="zstd")

    _write_atomic(path, write)


def _write_text(text: str, path: Path) -> None:
    def write(tmp: Path) -> None:
        tmp.write_text(text, encoding="utf-8")

    _write_atomic(path, write)


def _geometry_problems(geo: gpd.GeoDataFrame, profile_zips: set[str]) -> list[str]:
    problems: list[str] = []
    extra = sorted(set(geo["zip"]) - profile_zips)
    if extra:
        problems.append(f"geometry has ZIPs with no profile row: {', '.join(extra[:5])}")
    empty = int(geo.geometry.isna().sum() + geo.geometry.is_empty.sum())
    if empty:
        problems.append(f"{empty} null or empty geometries")
    return problems


def _acs_metadata(
    art: AcsArtifacts, vintage: int, registry: Registry, coverage: dict[str, float]
) -> dict[str, Any]:
    base = f"{census_base_url()}/{vintage}/acs/acs5"
    return {
        "vintage": vintage,
        "dataset_urls": {"detailed": base, "profile": f"{base}/profile"},  # key-free
        "variables": {k: v.as_metadata() for k, v in art.resolved.items()},
        "coverage": coverage,
        "sentinel_counts": art.sentinel_counts,
        "code_cross_check": _code_cross_check(art.profile, registry),
        "zcta_without_state": int(art.profile["state_fips"].isna().sum()),
    }


def census_base_url() -> str:
    from zipographics.census_api import BASE_URL

    return BASE_URL


def build(
    data_dir: Path,
    *,
    client: Any,
    session: Any,
    vintage: int = config.DEFAULT_VINTAGE,
    refresh: bool = False,
    only: str = "all",
    no_geo: bool = False,
    sources: Sources = DEFAULT_SOURCES,
    tolerance: float = DEFAULT_TOLERANCE,
    zipcator_parquet: Path | None = None,
    min_rows: int = MIN_ROWS,
    now: Callable[[], datetime] = _now,
    registry: Registry | None = None,
) -> BuildResult:
    """Run the build and publish the artifacts in ``data_dir``. Nothing is written unless the
    output validates; raw downloads are reused unless ``refresh``."""
    registry = registry or Registry.default()
    data_dir = Path(data_dir)
    raw_dir = data_dir / "raw"
    data_dir.mkdir(parents=True, exist_ok=True)
    do_acs = only in ("acs", "all")
    do_geo = only in ("geo", "all") and not no_geo
    if do_acs and client is None:
        raise BuildError("the ACS step needs a Census client", 2)
    profile_path = data_dir / "zcta_profile.parquet"
    geo_path = data_dir / "zcta_geo.parquet"
    meta_path = data_dir / "metadata.json"

    art = (
        acs_artifacts(client, vintage, registry, session, raw_dir, refresh, sources, now)
        if do_acs
        else None
    )
    geo: gpd.GeoDataFrame | None = None
    geo_info: dict[str, Any] = {}
    geo_records: list[dict[str, Any]] = []
    if do_geo:
        geo, geo_info, geo_records = _geometry(
            sources, raw_dir, session, refresh, tolerance, zipcator_parquet, now
        )
    elif geo_path.exists():
        geo = gpd.read_parquet(geo_path)  # check the new profile against the existing map

    problems: list[str] = []
    coverage: dict[str, float] = {}
    if art is not None:
        problems, coverage = validate_artifacts(
            art.profile, art.benchmarks, art.resolved, registry, geo=geo, min_rows=min_rows
        )
    elif geo is not None and profile_path.exists():
        zips = set(pd.read_parquet(profile_path, columns=["zip"])["zip"])
        problems = _geometry_problems(geo, zips)
    if problems:
        raise BuildError(
            "output validation failed: " + "; ".join(problems) + ". Nothing was written. "
            "Re-run with --refresh; if it persists the source format changed.",
            5,
        )

    existing: dict[str, Any] = {}
    if meta_path.exists():
        try:
            existing = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            existing = {}
    metadata: dict[str, Any] = dict(existing)
    metadata.update(built_at=_stamp(now()), app_version=__version__)
    counts: dict[str, int] = dict(existing.get("row_counts", {}))
    records: dict[str, dict[str, Any]] = {r["name"]: r for r in existing.get("sources", [])}
    paths: dict[str, Path] = {}

    if art is not None:
        metadata.update(_acs_metadata(art, vintage, registry, coverage))
        _write_parquet(art.profile.reset_index(), profile_path)
        _write_parquet(art.benchmarks, data_dir / "benchmarks.parquet")
        paths.update(profile=profile_path, benchmarks=data_dir / "benchmarks.parquet")
        counts.update(zcta_profile=len(art.profile), benchmarks=len(art.benchmarks))
        records.update({r["name"]: r for r in art.sources})
    if geo is not None and do_geo:
        metadata["geometry"] = geo_info
        _write_parquet(geo, geo_path)
        paths["geometry"] = geo_path
        counts["geometry"] = len(geo)
        records.update({r["name"]: r for r in geo_records})
    metadata["row_counts"] = counts
    metadata["sources"] = list(records.values())
    _write_text(json.dumps(metadata, indent=2), meta_path)
    paths["metadata"] = meta_path
    logger.info("wrote %s", ", ".join(p.name for p in paths.values()))
    return BuildResult(paths, metadata)


# ----------------------------------------------------------------------------- command line
def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="build_data.py",
        description="Download Census ACS data and build the local artifacts in data/.",
    )
    parser.add_argument("--refresh", action="store_true", help="ignore cached downloads")
    parser.add_argument(
        "--vintage", type=int, default=config.DEFAULT_VINTAGE, help="ACS 5-year vintage"
    )
    parser.add_argument("--only", choices=("acs", "geo", "all"), default="all")
    parser.add_argument("--no-geo", action="store_true", help="skip the map geometry")
    parser.add_argument(
        "--tolerance", type=float, default=DEFAULT_TOLERANCE, help="map simplification, degrees"
    )
    parser.add_argument(
        "--data-dir", type=Path, default=None, help="output folder (default: data/)"
    )
    return parser


def main(
    argv: Sequence[str] | None = None,
    environ: Mapping[str, str] | None = None,
    *,
    session: Any = None,
    registry: Registry | None = None,
) -> int:
    """The build's command line. Returns the exit code (0, 2, 3, 4 or 5); never a traceback."""
    parser = _parser()
    try:
        args = parser.parse_args(list(argv) if argv is not None else None)
    except SystemExit as exc:  # argparse already printed the usage message
        return int(exc.code) if isinstance(exc.code, int) else 2
    if args.no_geo and args.only == "geo":
        print("usage error: --no-geo contradicts --only geo", file=sys.stderr)
        return 2
    env = os.environ if environ is None else environ
    key = (env.get("CENSUS_API_KEY") or "").strip()
    secrets = [key] if key else []

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(message)s"))
    package_logger = logging.getLogger("zipographics")
    package_logger.addHandler(handler)
    previous_level = package_logger.level
    package_logger.setLevel(logging.INFO)
    install_redaction(secrets)
    try:
        data_dir = args.data_dir or config.data_dir()
        http = session if session is not None else requests.Session()
        client = None
        if args.only in ("acs", "all"):
            client = CensusClient(
                key, cache_root=data_dir / "raw", session=http, refresh=args.refresh
            )
        zc_env = (env.get(config.ZIPCATOR_PARQUET_ENV) or "").strip()
        build(
            data_dir,
            client=client,
            session=http,
            vintage=args.vintage,
            refresh=args.refresh,
            only=args.only,
            no_geo=args.no_geo,
            tolerance=args.tolerance,
            zipcator_parquet=Path(zc_env) if zc_env else None,
            registry=registry,
        )
        return 0
    except (MissingKeyError, RejectedKeyError) as exc:
        print(redact(str(exc), secrets), file=sys.stderr)
        return 3
    except CensusApiError as exc:
        print(redact(str(exc), secrets), file=sys.stderr)
        return 4  # network, proxy, server or unexpected API response
    except BuildError as exc:
        print(redact(str(exc), secrets), file=sys.stderr)
        return exc.exit_code
    except Exception as exc:
        print(redact(f"Unexpected error ({type(exc).__name__}): {exc}", secrets), file=sys.stderr)
        return 1
    finally:
        package_logger.removeHandler(handler)
        package_logger.setLevel(previous_level)
        uninstall_redaction()
