"""Synthetic Census API content, a fake client and fake file downloads for build tests.

A tiny registry (6 metrics, 12 variables) over 6 ZCTAs, 4 states, 4 counties and the nation. No
real Census data and no network. Includes a Puerto Rico ZCTA with a leading zero, an ACS sentinel in
a non-core variable, a top-coded median, and a controlled-estimate MOE.
"""

from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import geopandas as gpd
import pandas as pd
from shapely.geometry import box

from zipographics.census_api import VarRequest
from zipographics.data_build import DEFAULT_SOURCES, Registry
from zipographics.metrics import (
    Bracket,
    CountSpec,
    MedianSpec,
    Metric,
    ShareSpec,
    Var,
)

TOTAL = r"(?:^|!!)Total:?$"
ZCTAS = ["00601", "02108", "02109", "33602", "33603", "59001"]
STATES = {"12": "Florida", "25": "Massachusetts", "30": "Montana", "72": "Puerto Rico"}
COUNTIES = {  # 5-digit id -> name
    "12057": "Hillsborough County, Florida",
    "25025": "Suffolk County, Massachusetts",
    "30111": "Yellowstone County, Montana",
    "72001": "Adjuntas Municipio, Puerto Rico",
}
ZCTA_COUNTY = {
    "00601": "72001",
    "02108": "25025",
    "02109": "25025",
    "33602": "12057",
    "33603": "12057",
    "59001": "30111",
}

VARS: dict[str, Var] = {
    "B01003_001": Var("B01003_001", "B01003", TOTAL),
    "B11001_001": Var("B11001_001", "B11001", TOTAL),
    "B25003_001": Var("B25003_001", "B25003", TOTAL),
    "B25003_002": Var("B25003_002", "B25003", r"(?:^|!!)Owner occupied:?$"),
    "B19013_001": Var("B19013_001", "B19013", r"median household income", is_median=True),
    "B19001_002": Var("B19001_002", "B19001"),
    "B19001_003": Var("B19001_003", "B19001"),
    "B19001_004": Var("B19001_004", "B19001"),
    "DP03_UNINS": Var(
        "DP03_UNINS",
        "DP03",
        r"^estimate!!health insurance coverage!!civilian noninstitutionalized population"
        r"!!no health insurance coverage$",
        resolve="label",
        dataset="profile",
    ),
    "DP03_CIVNONINST": Var(
        "DP03_CIVNONINST",
        "DP03",
        r"^estimate!!health insurance coverage!!civilian noninstitutionalized population$",
        resolve="label",
        dataset="profile",
    ),
}
BRACKETS = (
    Bracket(("B19001_002",), 0, 10_000),
    Bracket(("B19001_003",), 10_000, 15_000),
    Bracket(("B19001_004",), 15_000, 20_000),
)


def _metric(mid: str, kind: str, unit: str, spec: Any, tag: Any = None) -> Metric:
    return Metric(mid, mid, unit, kind, spec, tag, "universe", "synthetic metric for tests")  # type: ignore[arg-type]


METRICS = (
    _metric("pop", "count", "count", CountSpec("B01003_001")),
    _metric("hh", "count", "count", CountSpec("B11001_001")),
    _metric(
        "owner", "share", "percent", ShareSpec(("B25003_002",), ("B25003_001",)), "proxy_other"
    ),
    _metric("median_hh_income", "median", "dollars", MedianSpec("B19013_001", BRACKETS), "income"),
    _metric("uninsured", "share", "percent", ShareSpec(("DP03_UNINS",), ("DP03_CIVNONINST",))),
)
REGISTRY = Registry(
    variables=VARS,
    metrics=METRICS,
    core=("pop", "hh", "median_hh_income", "owner"),
    population="B01003_001",
)

#: variables.json content: id -> {label, group}; ids that the registry resolves by label differ
DETAILED_META = {
    "B01003_001E": {"label": "Estimate!!Total", "group": "B01003"},
    "B11001_001E": {"label": "Estimate!!Total:", "group": "B11001"},
    "B25003_001E": {"label": "Estimate!!Total:", "group": "B25003"},
    "B25003_002E": {"label": "Estimate!!Total:!!Owner occupied", "group": "B25003"},
    "B19013_001E": {
        "label": "Estimate!!Median household income in the past 12 months",
        "group": "B19013",
    },
    "B19001_002E": {"label": "Estimate!!Total:!!Less than $10,000", "group": "B19001"},
    "B19001_003E": {"label": "Estimate!!Total:!!$10,000 to $14,999", "group": "B19001"},
    "B19001_004E": {"label": "Estimate!!Total:!!$15,000 to $19,999", "group": "B19001"},
}
_BASE = "HEALTH INSURANCE COVERAGE!!Civilian noninstitutionalized population"
PROFILE_META = {
    "DP03_0095E": {"label": f"Estimate!!{_BASE}", "group": "DP03"},
    "DP03_0099E": {"label": f"Estimate!!{_BASE}!!No health insurance coverage", "group": "DP03"},
    "DP03_0099PE": {"label": f"Percent!!{_BASE}!!No health insurance coverage", "group": "DP03"},
}
#: registry key -> base id of the estimate the API serves
BASE_IDS = {k: k for k in VARS if not k.startswith("DP03")} | {
    "DP03_UNINS": "DP03_0099",
    "DP03_CIVNONINST": "DP03_0095",
}


def _num(base: str, i: int, which: str) -> str:
    """Deterministic positive numbers: E grows with the geography index; M is 10 % of it."""
    scale = {
        "B01003_001": 2000,
        "B11001_001": 800,
        "B25003_001": 800,
        "B25003_002": 450,
        "B19013_001": 41000,
        "B19001_002": 30,
        "B19001_003": 40,
        "B19001_004": 50,
        "DP03_0095": 1900,
        "DP03_0099": 120,
    }[base]
    est = scale + 100 * i
    return str(est if which == "E" else est // 10)


@dataclass
class Synth:
    """Raw API tables per (dataset, level), with optional sabotage for failure tests."""

    drop_zcta: str | None = None  # remove a ZCTA from the data
    null_core: bool = False  # null the published median for most ZCTAs (coverage failure)
    bad_sentinel: bool = False  # an unknown large negative value
    extra: dict[str, Any] = field(default_factory=dict)

    def geos(self, level: str) -> list[dict[str, str]]:
        if level == "zcta":
            zs = [z for z in ZCTAS if z != self.drop_zcta]
            return [{"zip code tabulation area": z} for z in zs]
        if level == "state":
            return [{"NAME": n, "state": s} for s, n in STATES.items()]
        if level == "county":
            return [{"NAME": n, "state": c[:2], "county": c[2:]} for c, n in COUNTIES.items()]
        return [{"NAME": "United States", "us": "1"}]

    def table(self, dataset: str, level: str) -> pd.DataFrame:
        rows = []
        for i, geo in enumerate(self.geos(level)):
            row: dict[str, Any] = dict(geo)
            for key, base in BASE_IDS.items():
                if VARS[key].dataset != dataset:
                    continue
                row[f"{base}E"] = _num(base, i, "E")
                row[f"{base}M"] = _num(base, i, "M")
                if VARS[key].is_median:
                    row[f"{base}EA"] = None
            rows.append(row)
        df = pd.DataFrame(rows, dtype=object)
        if dataset == "detailed" and level == "zcta":
            z = list(df["zip code tabulation area"])
            at = {name: z.index(name) for name in ("02108", "02109", "59001", "33603") if name in z}
            if "02108" in at:  # top-coded median with a MOE that can't be computed
                df.loc[at["02108"], ["B19013_001E", "B19013_001M", "B19013_001EA"]] = [
                    "250001",
                    "-333333333",
                    "250000+",
                ]
            if "02109" in at:  # controlled estimate: MOE may be treated as zero
                df.loc[at["02109"], "B25003_002M"] = "-555555555"
            if "59001" in at:  # an ACS sentinel in a non-core variable
                df.loc[at["59001"], ["B19001_003E", "B19001_003M"]] = ["-666666666", "-222222222"]
            if self.null_core:
                df["B19013_001E"] = "-666666666"
            if self.bad_sentinel and "33603" in at:
                df.loc[at["33603"], "B11001_001E"] = "-123456789"
        return df


class FakeClient:
    """Stands in for CensusClient: serves variables.json and tables from a :class:`Synth`."""

    def __init__(self, synth: Synth | None = None, meta: tuple[dict, dict] | None = None) -> None:
        self.synth = synth or Synth()
        self.meta = meta or (DETAILED_META, PROFILE_META)
        self.calls: list[tuple[str, str]] = []

    def fetch_variables(self, vintage: int, dataset: str) -> dict[str, dict[str, str]]:
        self.calls.append(("variables", dataset))
        return self.meta[0] if dataset == "detailed" else self.meta[1]

    def fetch_table(
        self, dataset: str, vintage: int, level: str, variables: list[VarRequest]
    ) -> pd.DataFrame:
        self.calls.append((dataset, level))
        df = self.synth.table(dataset, level)
        wanted = {n for v in variables for n in v.names()}
        keep = [
            c
            for c in df.columns
            if c in wanted
            or c in ("NAME", "state", "county", "us")
            or c == "zip code tabulation area"
        ]
        return df[keep].copy()


# ---------------------------------------------------------------------------- downloaded files
def relationship_bytes() -> bytes:
    cols = [
        "GEOID_ZCTA5_20",
        "GEOID_COUNTY_20",
        "NAMELSAD_COUNTY_20",
        "AREALAND_PART",
        "AREAWATER_PART",
    ]
    lines = ["|".join(cols)]
    for z, c in ZCTA_COUNTY.items():
        name = COUNTIES[c].split(",")[0]
        lines.append("|".join([z, c, name, "1000", "10"]))
        lines.append(
            "|".join([z, "99999", "Smaller Overlap County", "5", "0"])
        )  # loses the overlap
    return ("\n".join(lines) + "\n").encode("utf-8")


def geonames_bytes(member: str, rows: list[tuple[str, str]]) -> bytes:
    lines = [
        "\t".join(["US", z, city, "S", "ST", "C", "1", "", "", "1", "2", "4"]) for z, city in rows
    ]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(member, "\n".join(lines) + "\n")
    return buf.getvalue()


def boundary_bytes(tmp_path: Path, zips: list[str] | None = None) -> bytes:
    zips = zips or ZCTAS
    geoms = [box(i, 0, i + 1, 1) for i, _ in enumerate(zips)]
    folder = tmp_path / "shp_build"
    folder.mkdir(exist_ok=True)
    gpd.GeoDataFrame(
        {"ZCTA5CE20": zips, "ALAND20": [1] * len(zips)}, geometry=geoms, crs="EPSG:4269"
    ).to_file(folder / "zcta.shp")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for f in sorted(folder.iterdir()):
            zf.write(f, f.name)
    return buf.getvalue()


class FakeDownload:
    def __init__(self, content: bytes, status: int = 200) -> None:
        self.content, self.status_code = content, status
        self.text = content.decode("utf-8", errors="replace")


class FileSession:
    """A session whose ``get`` serves the three downloadable files by URL."""

    def __init__(self, tmp_path: Path, geo_zips: list[str] | None = None) -> None:
        s = DEFAULT_SOURCES
        self.files = {
            s.zcta_url: boundary_bytes(tmp_path, geo_zips),
            s.county_rel_url: relationship_bytes(),
            s.geonames_us_url: geonames_bytes(
                "US.txt",
                [
                    ("02108", "Boston"),
                    ("02109", "Boston"),
                    ("33602", "Tampa"),
                    ("33603", "Tampa"),
                    ("59001", "Absarokee"),
                ],
            ),
            s.geonames_pr_url: geonames_bytes("PR.txt", [("00601", "Adjuntas")]),
        }
        self.calls: list[str] = []

    def get(self, url: str, **kwargs: Any) -> FakeDownload:
        self.calls.append(url)
        if url not in self.files:
            return FakeDownload(b"not found", 404)
        return FakeDownload(self.files[url])
