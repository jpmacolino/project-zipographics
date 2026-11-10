"""Load the built artifacts with schema checks (SPEC §4.3, §4.4). Used by the app at runtime.

Never imports the build modules, the Census client or ``dotenv`` (an import-graph test enforces
it): the running app needs no key and makes no network call.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import geopandas as gpd
import pandas as pd

from zipographics import config, metrics

MESSAGE = "Census data not built yet. Run `uv run python scripts/build_data.py`, then reload."
POPULATION_KEY = "B01003_001"
HOUSEHOLDS_KEY = "B11001_001"

_PROFILE_ATTRIBUTES = ("state_fips", "state", "county_fips", "county", "city")
_BENCHMARK_COLUMNS = ("geo_level", "geo_id", "name")


class DataNotBuiltError(RuntimeError):
    """Artifacts are missing or fail their schema check; the message says what to do."""


class _HasVariables(Protocol):
    variables: Mapping[str, metrics.Var]


@dataclass(frozen=True)
class Artifacts:
    profile: pd.DataFrame  # indexed by 5-character text ZIP
    benchmarks: pd.DataFrame
    geo: gpd.GeoDataFrame | None
    metadata: dict[str, Any]
    geo_note: str | None  # why the map is unavailable, if it is


def _not_built(detail: str) -> DataNotBuiltError:
    return DataNotBuiltError(f"{MESSAGE} ({detail})")


def _variables(registry: _HasVariables | None) -> Mapping[str, metrics.Var]:
    return registry.variables if registry is not None else metrics.VARIABLES


def _check_columns(frame: pd.DataFrame, columns: list[str], name: str) -> None:
    for column in columns:
        if column not in frame.columns:
            raise _not_built(f"{name} is missing column {column}")


def _read(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise _not_built(f"{path.name} not found")
    try:
        return pd.read_parquet(path)
    except Exception as exc:
        raise _not_built(f"{path.name} could not be read: {type(exc).__name__}") from None


def load(data_dir: Path | None = None, *, registry: _HasVariables | None = None) -> Artifacts:
    """Load and validate ``zcta_profile.parquet``, ``benchmarks.parquet``, ``metadata.json`` and,
    if present and valid, ``zcta_geo.parquet``. Raises :class:`DataNotBuiltError` otherwise."""
    folder = Path(data_dir) if data_dir is not None else config.data_dir()
    variables = _variables(registry)
    estimate_columns = [c for key in variables for c in (f"{key}_e", f"{key}_m")]
    var_columns = [
        *estimate_columns,
        *(f"{key}_code" for key, var in variables.items() if var.is_median),
    ]

    profile = _read(folder / "zcta_profile.parquet")
    _check_columns(profile, ["zip", *_PROFILE_ATTRIBUTES, *var_columns], "zcta_profile.parquet")
    if not all(isinstance(z, str) for z in profile["zip"]):
        raise _not_built("the zip column must hold text, never numbers")
    if not profile["zip"].str.fullmatch(r"[0-9]{5}").all():
        raise _not_built("the zip column must hold 5-character ZIPs")
    if not all(isinstance(s, str) for s in profile["state_fips"].dropna()):
        raise _not_built("the state_fips column must hold text")
    profile = profile.set_index("zip")

    benchmarks = _read(folder / "benchmarks.parquet")
    _check_columns(benchmarks, [*_BENCHMARK_COLUMNS, *estimate_columns], "benchmarks.parquet")
    if not all(isinstance(s, str) for s in benchmarks["geo_id"]):
        raise _not_built("the benchmark geo_id column must hold text")

    meta_path = folder / "metadata.json"
    if not meta_path.exists():
        raise _not_built("metadata.json not found")
    try:
        metadata = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise _not_built("metadata.json could not be read") from None

    geo: gpd.GeoDataFrame | None = None
    geo_note: str | None = None
    geo_path = folder / "zcta_geo.parquet"
    if not geo_path.exists():
        geo_note = (
            "The map is unavailable because zcta_geo.parquet has not been built. Run "
            "`uv run python scripts/build_data.py --only geo` to add it."
        )
    else:
        try:
            candidate = gpd.read_parquet(geo_path)
            ok = (
                "zip" in candidate.columns
                and all(isinstance(z, str) for z in candidate["zip"])
                and candidate.crs is not None
                and candidate.crs.to_epsg() == 4326
            )
        except Exception:
            ok = False
        if ok:
            geo = candidate
        else:
            geo_note = (
                "The map is unavailable: zcta_geo.parquet has an unexpected format. Rebuild it "
                "with `uv run python scripts/build_data.py --only geo`."
            )
    return Artifacts(profile, benchmarks, geo, metadata, geo_note)


def facts_from_profile(profile: pd.DataFrame) -> pd.DataFrame:
    """Per-ZIP facts for the review screen (SPEC §5.4): state, county, population, households."""
    facts = pd.DataFrame(
        {
            "state": profile["state"],
            "population": pd.to_numeric(profile[f"{POPULATION_KEY}_e"], errors="coerce"),
            "households": pd.to_numeric(profile[f"{HOUSEHOLDS_KEY}_e"], errors="coerce"),
            "county_fips": profile["county_fips"],
            "county": profile["county"],
            "city": profile["city"],
        },
        index=profile.index,
    )
    facts.index.name = "zip"
    return facts
