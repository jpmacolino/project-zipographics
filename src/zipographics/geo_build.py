"""Readers for the Census boundary, relationship and GeoNames files; map geometry (SPEC §4.1).

D3: the 2020 ZCTA cartographic boundary file (polygons for the map; no area math, so it can be
simplified hard). D4: the ZCTA-to-county relationship file (state and primary county per ZCTA).
D5: GeoNames postal codes (city names). D3-alt: Zipcator's built ``zcta.parquet``, reused when
its schema matches (DECISIONS D6).
"""

from __future__ import annotations

import logging
import zipfile
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pyogrio
import shapely
from shapely.geometry import MultiPolygon, Polygon
from shapely.geometry.base import BaseGeometry

from zipographics.errors import BuildError
from zipographics.facts import STATE_FIPS

logger = logging.getLogger(__name__)

_ABBR_BY_FIPS = {fips: abbr for abbr, fips in STATE_FIPS.items()}
_CACHE_HINT = (
    "If this file came from the cache it may be corrupt or an error page: re-run with --refresh."
)
_GEONAMES_COLUMNS = [
    "country", "zip", "city", "state_name", "state_code", "county_name",
    "county_code", "admin3_name", "admin3_code", "lat", "lon", "accuracy",
]  # fmt: skip


def _require_zip(path: Path) -> None:
    if not zipfile.is_zipfile(path):
        raise BuildError(
            f"{path.name} is not a valid ZIP file (the download may be an error page). "
            "Re-run with --refresh; if it persists the URL may have moved."
        )


def read_county_relationship(path: Path) -> pd.DataFrame:
    """D4: state and primary county per ZCTA (the county with the largest land overlap)."""
    needed = ["GEOID_ZCTA5_20", "GEOID_COUNTY_20", "NAMELSAD_COUNTY_20", "AREALAND_PART",
              "AREAWATER_PART"]  # fmt: skip
    try:
        df = pd.read_csv(path, sep="|", dtype=str, encoding="utf-8-sig", keep_default_na=False)
    except (OSError, UnicodeDecodeError, pd.errors.ParserError, pd.errors.EmptyDataError) as exc:
        raise BuildError(f"could not read {path.name}: {exc}. {_CACHE_HINT}") from exc
    missing = [c for c in needed if c not in df.columns]
    if missing:
        raise BuildError(
            f"schema mismatch in {path.name}: missing column(s) {', '.join(missing)}. "
            f"The Census may have changed the relationship-file format. {_CACHE_HINT}"
        )
    df = df[df["GEOID_ZCTA5_20"].str.strip() != ""].copy()  # counties without a ZCTA
    df["land"] = pd.to_numeric(df["AREALAND_PART"], errors="coerce").fillna(0)
    df["water"] = pd.to_numeric(df["AREAWATER_PART"], errors="coerce").fillna(0)
    df["zip"] = df["GEOID_ZCTA5_20"].str.strip().str.zfill(5)
    # Largest land overlap wins; water-only ZCTAs fall back to water overlap; then county id.
    df = df.sort_values(
        ["zip", "land", "water", "GEOID_COUNTY_20"], ascending=[True, False, False, True]
    ).drop_duplicates("zip")
    county_fips = df["GEOID_COUNTY_20"].str.strip()
    out = pd.DataFrame(
        {
            "zip": df["zip"],
            "state_fips": county_fips.str[:2],
            "state": county_fips.str[:2].map(_ABBR_BY_FIPS),
            "county_fips": county_fips,
            "county": df["NAMELSAD_COUNTY_20"].str.strip(),
        }
    )
    return out.reset_index(drop=True)


def read_geonames(path: Path) -> pd.DataFrame:
    """D5: place name per ZIP (first row per postal code). CC BY 4.0 data."""
    _require_zip(path)
    member = f"{path.stem}.txt"  # US.zip -> US.txt, PR.zip -> PR.txt
    try:
        with zipfile.ZipFile(path) as zf, zf.open(member) as fh:
            df = pd.read_csv(
                fh, sep="\t", header=None, names=_GEONAMES_COLUMNS, dtype=str,
                keep_default_na=False, encoding="utf-8",
            )  # fmt: skip
    except (
        KeyError,
        OSError,
        UnicodeDecodeError,
        pd.errors.ParserError,
        pd.errors.EmptyDataError,
    ) as exc:
        raise BuildError(f"could not read {member} from {path.name}: {exc}. {_CACHE_HINT}") from exc
    if df.empty:
        raise BuildError(f"{member} in {path.name} has no rows. {_CACHE_HINT}")
    out = pd.DataFrame({"zip": df["zip"].str.strip().str.zfill(5), "city": df["city"].str.strip()})
    return out.drop_duplicates("zip", keep="first").reset_index(drop=True)


def read_boundaries(path: Path) -> gpd.GeoDataFrame:
    """D3: ZCTA polygons in EPSG:4326 with a text ``zip`` column."""
    _require_zip(path)
    try:
        raw = pyogrio.read_dataframe(f"zip://{path.resolve().as_posix()}")
    except Exception as exc:
        raise BuildError(f"could not read the boundary shapefile in {path.name}: {exc}") from exc
    if "ZCTA5CE20" not in raw.columns:
        raise BuildError(
            f"schema mismatch in {path.name}: missing column ZCTA5CE20 "
            f"(found: {', '.join(map(str, raw.columns))}). The Census may have changed the format."
        )
    gdf = raw.set_crs(4326) if raw.crs is None else raw.to_crs(4326)
    out = gpd.GeoDataFrame(
        {"zip": gdf["ZCTA5CE20"].astype(str).str.strip().str.zfill(5)},
        geometry=gdf.geometry.to_numpy(),
        crs="EPSG:4326",
    )
    logger.info("read %s ZCTA polygons", f"{len(out):,}")
    return out


def _polygonal(geom: BaseGeometry | None) -> BaseGeometry | None:
    """Keep only polygon parts of a (repaired) geometry; None if nothing is left."""
    if geom is None or geom.is_empty:
        return None
    if isinstance(geom, Polygon | MultiPolygon):
        return geom
    polys: list[Polygon] = []
    for part in shapely.get_parts(geom):
        if isinstance(part, Polygon) and not part.is_empty:
            polys.append(part)
        elif isinstance(part, MultiPolygon):
            polys.extend(p for p in part.geoms if not p.is_empty)
    if not polys:
        return None
    return polys[0] if len(polys) == 1 else MultiPolygon(polys)


def assemble_geometry(gdf: gpd.GeoDataFrame, tolerance: float) -> gpd.GeoDataFrame:
    """Repair, then simplify (``tolerance`` in degrees; 0 = off) the map polygons.

    Uses topology-preserving *coverage* simplification (``shapely.coverage_simplify``): an edge
    shared by two neighbours is simplified once and identically for both, so a clean partition
    stays a clean partition. Rows are never dropped; empty geometries become None.
    """
    geoms = gdf.geometry
    invalid = ~geoms.is_valid & ~geoms.is_empty & ~geoms.isna()
    if invalid.any():
        logger.info("repairing %d invalid geometries", int(invalid.sum()))
        geoms = geoms.copy()
        geoms[invalid] = shapely.make_valid(geoms[invalid].to_numpy())
    arr = pd.Series([_polygonal(g) for g in geoms], dtype=object).to_numpy()
    if tolerance > 0:
        usable = ~(shapely.is_missing(arr) | shapely.is_empty(arr))
        if usable.any():
            arr = arr.copy()
            arr[usable] = shapely.coverage_simplify(arr[usable], tolerance)
    return gpd.GeoDataFrame(
        {"zip": gdf["zip"].astype(str).to_numpy()},
        geometry=gpd.GeoSeries(arr, crs=gdf.crs).to_numpy(),
        crs=gdf.crs,
    )


def read_zipcator_geometry(path: Path) -> tuple[gpd.GeoDataFrame | None, str | None]:
    """D3-alt: reuse Zipcator geometry. Returns (frame, None) or (None, why it was skipped)."""
    if not path.exists():
        return None, f"{path} not found"
    try:
        gdf = gpd.read_parquet(path)
    except Exception as exc:
        return None, f"could not read {path.name}: {exc}"
    if "zip" not in gdf.columns:
        return None, f"{path.name} has no 'zip' column"
    if not all(isinstance(z, str) for z in gdf["zip"]):
        return None, f"{path.name} has a non-text 'zip' column"
    if gdf.crs is None or gdf.crs.to_epsg() != 4326:
        return None, f"{path.name} is not in EPSG:4326"
    return gpd.GeoDataFrame(gdf[["zip", "geometry"]], geometry="geometry", crs=gdf.crs), None
