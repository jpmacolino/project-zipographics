"""Margin-of-error formulas, reliability tiers, the index and interpolated medians (SPEC §6).

Every formula is quoted from the official documents and checked against their worked examples
(DECISIONS "Phase 2"): ACS General Handbook 2020 ch. 8 and the PUMS Accuracy document. They are
*approximations* (they ignore covariance) and are labeled so wherever users see them.

Estimates and MOEs are plain floats; ``None`` means "unknown" and propagates (an unknown input
gives an unknown result, never a silently wrong number).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from zipographics.config import CV_CAUTION, CV_GOOD, Z90

Tier = Literal["good", "caution", "unreliable"]
MedianCode = Literal["none", "top", "bottom"]
Bound = tuple[float, float]  # (lower, upper) of a bracket; lower may be -inf, upper may be inf

_TIER_ORDER: dict[Tier, int] = {"good": 0, "caution": 1, "unreliable": 2}
_EPS = 1e-9  # float noise tolerance at the tier boundaries and bracket edges


def se(moe: float | None) -> float | None:
    """Standard error from a 90 % margin of error: ``SE = MOE / 1.645`` (handbook formula 2)."""
    return None if moe is None else moe / Z90


def moe_sum(moes: Sequence[float | None], weights: Sequence[float] | None = None) -> float | None:
    """MOE of a sum: ``sqrt(sum (w_i * MOE_i)^2)`` (handbook formula 1; weights default to 1).

    Unknown if there are no components or any MOE is unknown. Every component is included,
    including zero estimates: the 2020 handbook has no "largest zero MOE only" rule (DECISIONS).
    """
    if not moes or any(m is None for m in moes):
        return None
    ws = weights if weights is not None else [1.0] * len(moes)
    return math.sqrt(sum((w * m) ** 2 for w, m in zip(ws, moes, strict=True) if m is not None))


def moe_proportion(
    x: float | None, mx: float | None, y: float | None, my: float | None
) -> float | None:
    """MOE of a proportion X/Y where X is a subset of Y (handbook formula 6).

    ``sqrt(MOE(X)^2 - P^2 MOE(Y)^2) / Y``; if the radicand is negative the plus form (the ratio
    formula) is used, as the handbook instructs. Result is in proportion units.
    """
    if x is None or mx is None or y is None or my is None or y <= 0:
        return None
    p = x / y
    rad = mx**2 - p**2 * my**2
    if rad < 0:
        rad = mx**2 + p**2 * my**2  # "substitute a 'plus' for the 'minus'"
    return math.sqrt(rad) / y


def moe_ratio(x: float | None, mx: float | None, y: float | None, my: float | None) -> float | None:
    """MOE of a ratio X/Y where X is not a subset of Y (handbook formula 7)."""
    if x is None or mx is None or y is None or my is None or y <= 0:
        return None
    r = x / y
    return math.sqrt(mx**2 + r**2 * my**2) / y


def moe_product(
    a: float | None, ma: float | None, b: float | None, mb: float | None
) -> float | None:
    """MOE of a product A*B: ``sqrt(A^2 MOE(B)^2 + B^2 MOE(A)^2)`` (handbook formula 9)."""
    if a is None or ma is None or b is None or mb is None:
        return None
    return math.sqrt(a**2 * mb**2 + b**2 * ma**2)


def cv(est: float | None, moe: float | None) -> float | None:
    """Coefficient of variation in percent: ``SE / estimate * 100`` (handbook formula 4)."""
    if est is None or moe is None or est == 0:
        return None
    return moe / Z90 / abs(est) * 100


def tier(est: float | None, moe: float | None, *, coded: bool = False) -> Tier:
    """Reliability tier (SPEC §6.6): good CV <= 15 %, caution <= 30 %, else unreliable.

    A zero estimate (CV undefined) is "caution"; a null estimate or MOE is "unreliable"; a top- or
    bottom-coded median is "caution" whatever its MOE (SPEC §6.2).
    """
    if coded and est is not None:
        return "caution"
    if est is None or moe is None:
        return "unreliable"
    if est == 0:
        return "caution"
    value = cv(est, moe)
    assert value is not None
    if value <= CV_GOOD + _EPS:
        return "good"
    if value <= CV_CAUTION + _EPS:
        return "caution"
    return "unreliable"


def worse_tier(a: Tier, b: Tier) -> Tier:
    return a if _TIER_ORDER[a] >= _TIER_ORDER[b] else b


def index_value(value: float | None, benchmark: float | None) -> int | None:
    """``100 * value / benchmark`` rounded half up; unknown if either is null or benchmark is 0."""
    if value is None or benchmark is None or benchmark == 0:
        return None
    return math.floor(100 * value / benchmark + 0.5)


# ------------------------------------------------------------------------------ medians
@dataclass(frozen=True, slots=True)
class Median:
    """An interpolated median. ``code`` is "top"/"bottom" when it lies in an open bracket, in
    which case ``value`` is that bracket's finite bound ("$200,000+")."""

    value: float
    code: MedianCode
    index: int


def _find_bracket(p: float, counts: Sequence[float]) -> tuple[int, float, float] | None:
    """(index, cumulative count below it, its count) for the bracket holding proportion p."""
    total = sum(counts)
    if total <= 0:
        return None
    target = p * total
    tol = _EPS * total
    cum = 0.0
    for i, c in enumerate(counts):
        if c > 0 and cum + c >= target - tol:
            return i, cum, c
        cum += c
    return None  # not reachable for 0 < p <= 1 and total > 0


def value_at_proportion(
    p: float, counts: Sequence[float], bounds: Sequence[Bound]
) -> tuple[float, MedianCode] | None:
    """Linear interpolation of the value below which proportion ``p`` of the counts lie.

    ``value = L + (p*N - C) / f * W`` where C is the count below the bracket, f its count and
    [L, L+W) its bounds (ACS "linear interpolation method", PUMS Accuracy "Medians").
    """
    found = _find_bracket(p, counts)
    if found is None:
        return None
    i, below, f = found
    lo, hi = bounds[i]
    if math.isinf(hi):
        return lo, "top"
    if math.isinf(lo):
        return hi, "bottom"
    return lo + (p * sum(counts) - below) / f * (hi - lo), "none"


def median_from_counts(counts: Sequence[float], bounds: Sequence[Bound]) -> Median | None:
    """The median of a bracketed distribution, or None for an empty one."""
    found = _find_bracket(0.5, counts)
    if found is None:
        return None
    res = value_at_proportion(0.5, counts, bounds)
    assert res is not None
    return Median(res[0], res[1], found[0])


def median_moe(
    counts: Sequence[float | None],
    moes: Sequence[float | None],
    bounds: Sequence[Bound],
) -> float | None:
    """Approximate MOE of an interpolated median (SPEC §6.4, DECISIONS D8).

    The Census method (PUMS Accuracy, "Medians") takes the 68 % interval of the 50 % point,
    ``p = 0.5 ± SE(p)``, interpolates the values there, and halves the difference. Design factors
    won't be published after 2024, so SE(p) is derived from the bracket MOEs: the proportion
    formula (6) for the cumulative count through the median bracket over N, at P = 0.5.
    Unknown when any bracket is unknown or an end of the interval falls in an open bracket.
    """
    if any(c is None for c in counts) or any(m is None for m in moes):
        return None
    cs = [float(c) for c in counts if c is not None]
    ms = [float(m) for m in moes if m is not None]
    total = sum(cs)
    median = median_from_counts(cs, bounds)
    if median is None or median.code != "none":
        return None
    n_moe = math.sqrt(sum(m * m for m in ms))
    x_moe = math.sqrt(sum(m * m for m in ms[: median.index + 1]))
    rad = x_moe**2 - 0.25 * n_moe**2
    if rad < 0:
        rad = x_moe**2 + 0.25 * n_moe**2
    se_p = math.sqrt(rad) / total / Z90
    p_lo, p_hi = max(0.5 - se_p, _EPS), min(0.5 + se_p, 1.0)
    lo = value_at_proportion(p_lo, cs, bounds)
    hi = value_at_proportion(p_hi, cs, bounds)
    if lo is None or hi is None or lo[1] != "none" or hi[1] != "none":
        return None
    return Z90 * (hi[0] - lo[0]) / 2
