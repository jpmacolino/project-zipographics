"""Synthetic ACS frames (zip-indexed ``<key>_e`` / ``_m`` / ``_code`` columns) for profile tests."""

from __future__ import annotations

import numpy as np
import pandas as pd

from zipographics import metrics

Cell = tuple[float | None, float | None]  # (estimate, MOE)


def empty_frame(zips: list[str]) -> pd.DataFrame:
    """Every registry variable present, all null; published medians carry code 'none'."""
    data: dict[str, object] = {}
    for key, var in metrics.VARIABLES.items():
        data[f"{key}_e"] = np.full(len(zips), np.nan)
        data[f"{key}_m"] = np.full(len(zips), np.nan)
        if var.is_median:
            data[f"{key}_code"] = np.array(["none"] * len(zips), dtype=object)
    return pd.DataFrame(data, index=pd.Index(zips, name="zip", dtype="object"))


def make_frame(
    rows: dict[str, dict[str, Cell]], codes: dict[str, dict[str, str]] | None = None
) -> pd.DataFrame:
    """Build a frame from ``{zip: {key: (estimate, moe)}}``; unmentioned variables are null."""
    frame = empty_frame(list(rows))
    for z, cells in rows.items():
        for key, (est, moe) in cells.items():
            frame.loc[z, f"{key}_e"] = np.nan if est is None else est
            frame.loc[z, f"{key}_m"] = np.nan if moe is None else moe
    for z, per in (codes or {}).items():
        for key, code in per.items():
            frame.loc[z, f"{key}_code"] = code
    return frame


def random_frame(n: int, seed: int = 0, null_rate: float = 0.05) -> pd.DataFrame:
    """Random but non-negative estimates and MOEs for every variable; some nulls and zeros."""
    rng = np.random.default_rng(seed)
    zips = [f"{10000 + i:05d}" for i in range(n)]
    frame = empty_frame(zips)
    for key, var in metrics.VARIABLES.items():
        est = rng.integers(0, 2000, n).astype("float64")
        est[rng.random(n) < 0.05] = 0.0
        moe = np.round(rng.random(n) * 0.3 * est + rng.random(n) * 15, 2)
        gone = rng.random(n) < null_rate
        est[gone] = np.nan
        moe[gone | (rng.random(n) < null_rate)] = np.nan
        frame[f"{key}_e"] = est
        frame[f"{key}_m"] = np.where(np.isnan(est), np.nan, moe)
        if var.is_median:
            frame[f"{key}_code"] = rng.choice(["none", "none", "none", "top", "bottom"], n)
    return frame
