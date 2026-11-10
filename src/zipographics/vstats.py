"""NumPy-vectorized versions of the :mod:`zipographics.stats` formulas (NaN means unknown).

The profile engine computes one metric for all ZIPs at once with these, and for the trade area as
a 0-d array. ``tests/unit/test_vstats.py`` checks they agree with the scalar functions, which are
the ones verified against the handbook's worked examples.
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

from zipographics.config import CV_CAUTION, CV_GOOD, Z90

F = NDArray[np.float64]
_EPS = 1e-9
_NOISE = 1e-12
_INDEX_LIMIT = 1e9  # same sanity bound as stats.index_value


def _unknown(*arrays: F) -> NDArray[np.bool_]:
    out = np.isnan(arrays[0])
    for a in arrays[1:]:
        out = out | np.isnan(a)
    return out


def moe_proportion(x: F, mx: F, y: F, my: F) -> F:
    """Handbook formula 6 with the plus-form fallback; NaN if any input is unknown or y <= 0."""
    with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
        p = x / y
        plus = mx**2 + p**2 * my**2
        rad = mx**2 - p**2 * my**2
        noise = _NOISE * plus
        rad = np.where(rad < -noise, plus, np.where(rad < noise, 0.0, rad))
        out = np.sqrt(rad) / y
    bad = _unknown(x, mx, y, my) | ~(y > 0) | ~np.isfinite(out) | ~np.isfinite(plus)
    return np.where(bad, np.nan, out)


def moe_ratio(x: F, mx: F, y: F, my: F) -> F:
    """Handbook formula 7."""
    with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
        r = x / y
        out = np.sqrt(mx**2 + r**2 * my**2) / y
    return np.where(_unknown(x, mx, y, my) | ~(y > 0) | ~np.isfinite(out), np.nan, out)


def moe_product(a: F, ma: F, b: F, mb: F) -> F:
    """Handbook formula 9."""
    out = np.sqrt(a**2 * mb**2 + b**2 * ma**2)
    return np.where(_unknown(a, ma, b, mb), np.nan, out)


def tier(est: F, moe: F, coded: NDArray[np.bool_]) -> NDArray[np.object_]:
    """Reliability tier per element, same rules as :func:`zipographics.stats.tier`."""
    with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
        cv = moe / Z90 / np.abs(est) * 100
    known = ~np.isnan(est)
    out = np.full(est.shape, "unreliable", dtype=object)
    usable = known & ~np.isnan(moe) & (est != 0)
    out[usable & (cv <= CV_CAUTION + _EPS)] = "caution"
    out[usable & (cv <= CV_GOOD + _EPS)] = "good"
    out[known & (est == 0) & ~np.isnan(moe)] = (
        "caution"  # CV undefined; unknown MOE stays unreliable
    )
    out[known & coded] = "caution"
    return out


def index_values(est: F, bench: float | None) -> F:
    """``floor(100 * est / bench + 0.5)`` per element; NaN if est is unknown or bench unusable."""
    if bench is None or bench == 0 or np.isnan(bench):
        return np.full(est.shape, np.nan)
    with np.errstate(over="ignore", invalid="ignore"):
        out = np.floor(np.round(100 * est / bench, 9) + 0.5)
    return np.where(np.isnan(est) | ~np.isfinite(out) | (np.abs(out) > _INDEX_LIMIT), np.nan, out)
