"""Small synthetic ``data.Artifacts`` for the Phase 5 tests (analysis, filters, exports, report).

Only the cells the tests care about are filled: population, households, tenure, households with
children, the published median household income (with an optional top/bottom code) and the
B19001 income brackets (so a multi-ZIP median can be interpolated).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from synth_frame import empty_frame

from zipographics import data

#: household-income brackets B19001_002..017 as shares of households (sum 1.0); median about $62k
_BRACKET_SHAPE = [0.04, 0.03, 0.03, 0.03, 0.04, 0.04, 0.04, 0.04, 0.04, 0.04, 0.08, 0.12, 0.21,
                  0.11, 0.07, 0.04]  # fmt: skip


@dataclass(frozen=True)
class Z:
    """One ZIP (or benchmark geography) in a synthetic world."""

    pop: float | None
    hh: float | None
    owner: float = 0.6  # share of occupied units
    kids: float = 0.3  # share of households with children
    income: float | None = 60_000.0
    code: str = "none"  # code of the published median household income
    state: str = "FL"
    county: tuple[str, str] = ("12057", "Hillsborough County")
    city: str = "Tampa"
    #: relative MOE of the count cells (0.1 = ±10 %)
    rel_moe: float = 0.1
    extra: dict[str, tuple[float | None, float | None]] = field(default_factory=dict)


def _cells(z: Z) -> dict[str, tuple[float | None, float | None]]:
    def c(v: float | None) -> tuple[float | None, float | None]:
        return (None, None) if v is None else (v, round(abs(v) * z.rel_moe, 3))

    out: dict[str, tuple[float | None, float | None]] = {"B01003_001": c(z.pop)}
    if z.hh is not None:
        h = z.hh
        out.update(
            {
                "B11001_001": c(h),
                "B25003_001": c(h),
                "B25003_002": c(round(h * z.owner)),
                "B25003_003": c(h - round(h * z.owner)),
                "B11005_001": c(h),
                "B11005_002": c(round(h * z.kids)),
                "B19001_001": c(h),
            }
        )
        for i, share in enumerate(_BRACKET_SHAPE):
            out[f"B19001_{i + 2:03d}"] = c(round(h * share))
    else:
        out["B11001_001"] = (None, None)
    out["B19013_001"] = (z.income, None if z.income is None or z.code != "none" else 2_500.0)
    out.update(z.extra)
    return out


def frame_of(world: dict[str, Z]) -> pd.DataFrame:
    frame = empty_frame(list(world))
    for key, z in world.items():
        for var, (est, moe) in _cells(z).items():
            frame.loc[key, f"{var}_e"] = np.nan if est is None else est
            frame.loc[key, f"{var}_m"] = np.nan if moe is None else moe
        frame.loc[key, "B19013_001_code"] = z.code
    return frame


def make_artifacts(
    zips: dict[str, Z],
    benchmarks: dict[tuple[str, str], tuple[str, Z]] | None = None,
    *,
    vintage: int = 2024,
    geo: object | None = None,
) -> data.Artifacts:
    """``zips`` -> profile; ``benchmarks`` maps (level, geo_id) -> (name, Z).

    The default benchmark set has the nation, Florida, Georgia, Massachusetts, Puerto Rico and the
    counties used by the ZIPs, with owner shares 65 %, 66 %, ... so that indexes differ.
    """
    prof = frame_of(zips)
    state_fips = {"FL": "12", "GA": "13", "MA": "25", "PR": "72", "KS": "20", "MO": "29"}
    prof.insert(0, "city", [z.city for z in zips.values()])
    prof.insert(0, "county", [z.county[1] for z in zips.values()])
    prof.insert(0, "county_fips", [z.county[0] for z in zips.values()])
    prof.insert(0, "state", [z.state for z in zips.values()])
    prof.insert(0, "state_fips", [state_fips[z.state] for z in zips.values()])

    bench_spec = benchmarks if benchmarks is not None else default_benchmarks(zips)
    bframe = frame_of({f"{lvl}:{gid}": z for (lvl, gid), (_, z) in bench_spec.items()})
    bframe.index = pd.Index([gid for (_, gid) in bench_spec], name="geo_id")
    bframe.insert(0, "name", [name for name, _ in bench_spec.values()])
    bframe.insert(0, "geo_id", [gid for (_, gid) in bench_spec])
    bframe.insert(0, "geo_level", [lvl for (lvl, _) in bench_spec])
    bframe = bframe.reset_index(drop=True)
    meta = {"vintage": vintage, "built_at": "2026-11-10T00:00:00Z", "app_version": "0.0.0"}
    return data.Artifacts(prof, bframe, None, meta, None)  # type: ignore[arg-type]


def default_benchmarks(zips: dict[str, Z]) -> dict[tuple[str, str], tuple[str, Z]]:
    out: dict[tuple[str, str], tuple[str, Z]] = {
        ("us", "1"): ("United States", Z(330e6, 130e6, 0.65, 0.30, 75_000)),
        ("state", "12"): ("Florida", Z(22e6, 9e6, 0.66, 0.27, 71_000)),
        ("state", "13"): ("Georgia", Z(11e6, 4e6, 0.64, 0.33, 74_000)),
        ("state", "25"): ("Massachusetts", Z(7e6, 2.8e6, 0.62, 0.30, 96_000)),
        ("state", "72"): ("Puerto Rico", Z(3.2e6, 1.2e6, 0.70, 0.24, 24_000)),
        ("state", "20"): ("Kansas", Z(2.9e6, 1.1e6, 0.66, 0.31, 69_000)),
        ("state", "29"): ("Missouri", Z(6.1e6, 2.4e6, 0.66, 0.29, 65_000)),
    }
    for z in zips.values():
        fips, name = z.county
        out.setdefault(("county", fips), (name, Z(1.5e6, 600e3, 0.63, 0.28, 68_000)))
    return out
