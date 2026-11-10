"""An independent oracle for the golden scenarios (SPEC 9.4, marker ``data``).

It reads the **raw Census API responses** cached in ``data/raw`` (the published numbers) and the
Census relationship file, with its own small parsers and **no import from ``zipographics``**, so
an expected value here is never a snapshot of the code under test. The arithmetic the scenarios
do with these numbers is written out in the tests (and in docs/QA_REPORT.md as worked tables).
"""

from __future__ import annotations

import csv
import io
import json
import math
import os
from collections import defaultdict
from functools import cache
from pathlib import Path

DATA = Path(os.environ.get("ZIPOGRAPHICS_DATA_DIR") or Path(__file__).resolve().parents[2] / "data")
SENTINELS = {-666666666, -999999999, -888888888, -222222222, -333333333, -555555555}

Cell = tuple[float, float]  # (estimate, margin of error); NaN when unpublished

#: household-income brackets of table B19001 (variables _002.._017): [low, high) in dollars
B19001 = [
    (0, 10_000), (10_000, 15_000), (15_000, 20_000), (20_000, 25_000), (25_000, 30_000),
    (30_000, 35_000), (35_000, 40_000), (40_000, 45_000), (45_000, 50_000), (50_000, 60_000),
    (60_000, 75_000), (75_000, 100_000), (100_000, 125_000), (125_000, 150_000),
    (150_000, 200_000), (200_000, math.inf),
]  # fmt: skip


def _num(text: object) -> float:
    if text is None or str(text).strip().lower() in {"", "null", "none", "nan"}:
        return math.nan
    return float(str(text))


def _est(text: object) -> float:
    v = _num(text)
    return math.nan if v in SENTINELS else v


def _moe(text: object, est: float) -> float:
    if math.isnan(est):
        return math.nan
    v = _num(text)
    if v == -555555555:
        return 0.0
    return math.nan if v in SENTINELS else v


@cache
def level(name: str) -> dict[str, dict[str, Cell]]:
    """{geography id: {variable id: (estimate, moe)}} for level zcta, state, county or us."""
    marker = {
        "zcta": "zip%20code%20tabulation%20area",
        "state": "for=state:*",
        "us": "for=us",
        "county": "for=county:*",
    }[name]
    out: dict[str, dict[str, Cell]] = defaultdict(dict)
    for meta in sorted((DATA / "raw" / "acs").rglob("*.meta.json")):
        url = json.loads(meta.read_text(encoding="utf-8"))["url"]
        if (
            marker not in url
            or (name == "state" and "county" in url)
            or (name == "us" and "state" in url)
        ):
            continue
        rows = json.loads(
            meta.with_name(meta.name.replace(".meta", "")).read_text(encoding="utf-8")
        )
        head = rows[0]
        names = [h[:-1] for h in head if h.endswith("E") and h[:-1] + "M" in head]
        index = {h: i for i, h in enumerate(head)}
        for row in rows[1:]:
            if name == "zcta":
                gid = row[index["zip code tabulation area"]]
            elif name == "state":
                gid = row[index["state"]]
            elif name == "county":
                gid = row[index["state"]] + row[index["county"]]
            else:
                gid = "1"
            record = out[gid]
            for var in names:
                e = _est(row[index[var + "E"]])
                record[var] = (e, _moe(row[index[var + "M"]], e))
    return dict(out)


def get(lv: str, geo: str, var: str) -> Cell:
    return level(lv)[geo][var]


def present(zcta: str) -> bool:
    return zcta in level("zcta")


# ------------------------------------------------------------------ the relationship file (D4)
@cache
def primary_county() -> dict[str, tuple[str, str]]:
    """{zcta: (county id, county name)} with the largest land overlap (the file's AREALAND_PART)."""
    text = (DATA / "raw" / "tab20_zcta520_county20_natl.txt").read_text(encoding="utf-8-sig")
    best: dict[str, tuple[float, str, str]] = {}
    for row in csv.DictReader(io.StringIO(text), delimiter="|"):
        z, county = row["GEOID_ZCTA5_20"], row["GEOID_COUNTY_20"]
        if not z or not county:
            continue
        land = float(row["AREALAND_PART"] or 0)
        if z not in best or land > best[z][0]:
            best[z] = (land, county, row["NAMELSAD_COUNTY_20"])
    return {z: (c, n) for z, (_, c, n) in best.items()}


# ------------------------------------------------------------------ the arithmetic, written out
def interpolated_median(counts: list[float], brackets: list[tuple[float, float]]) -> float:
    """Median by linear interpolation inside the bracket that holds the half-way household:
    L + (N/2 - cumulative below) / count * width. An open-ended top bracket returns its lower
    bound (the handbook's convention: no upper bound to interpolate to)."""
    total = sum(counts)
    half = total / 2
    below = 0.0
    for c, (lo, hi) in zip(counts, brackets, strict=True):
        if below + c >= half and c > 0:
            if math.isinf(hi):
                return lo
            return lo + (half - below) / c * (hi - lo)
        below += c
    return math.nan


def round_half_up(x: float) -> int:
    return math.floor(x + 0.5)


def cv_percent(est: float, moe: float) -> float:
    """MOE / 1.645 / estimate, in percent (SE = MOE / 1.645; the 90 % confidence level)."""
    return moe / 1.645 / est * 100


def tier(cv: float) -> str:
    return "good" if cv <= 15 else "caution" if cv <= 30 else "unreliable"


def share_moe(x: float, mx: float, y: float, my: float) -> float:
    """MOE of the proportion x / y (x a subset of y): sqrt(mx^2 - p^2 my^2) / y, falling back to the
    plus form when the radicand is negative (ACS handbook)."""
    p = x / y
    radicand = mx**2 - p**2 * my**2
    if radicand < 0:
        radicand = mx**2 + p**2 * my**2
    return math.sqrt(radicand) / y


def sum_moe(moes: list[float]) -> float:
    return math.sqrt(sum(m * m for m in moes))
