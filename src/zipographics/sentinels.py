"""ACS annotation values (sentinels) become nulls at build time (SPEC §6.1, CLAUDE.md).

No sentinel value may ever reach a sum, mean, median, index, chart or export as a number.
Treatment, per DECISIONS V6 (to be re-verified against the 5-year notes page in Phase 4):

* estimate column: any of the six values -> null, and its MOE -> null;
* MOE column: -222222222 and -333333333 -> null MOE, estimate kept; -555555555 (estimate controlled
  to an independent estimate, "may be treated as zero") -> MOE 0; the estimate-type sentinels
  (-666666666, -999999999, -888888888) -> null MOE;
* any other value below -100,000,000 -> :class:`UnknownSentinelError` (the build fails rather than
  guess), so a new annotation value can't slip through as a huge negative number;
* a null estimate always has a null MOE.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Mapping

import numpy as np
import pandas as pd

#: Every annotation value we know. Order is stable for tests and metadata.
ALL_SENTINELS: tuple[int, ...] = (
    -666666666,
    -999999999,
    -888888888,
    -222222222,
    -333333333,
    -555555555,
)
_MOE_NULL = frozenset({-666666666, -999999999, -888888888, -222222222, -333333333})
_MOE_ZERO = -555555555
_LARGE_NEGATIVE = -100_000_000

_TOP = re.compile(r"^[0-9][0-9,]*\+$")
_BOTTOM = re.compile(r"^[0-9][0-9,]*-$")


class UnknownSentinelError(ValueError):
    """A large negative value that is not a documented ACS annotation value."""


def _numeric(values: pd.Series) -> pd.Series:
    return pd.to_numeric(values.replace("", None), errors="coerce").astype("float64")


def _check_unknown(num: pd.Series, column: str) -> None:
    unknown = num[(num < _LARGE_NEGATIVE) & ~num.isin(ALL_SENTINELS)]
    if not unknown.empty:
        raise UnknownSentinelError(
            f"unknown large negative value {int(unknown.iloc[0])} in the {column} column: not a "
            "documented ACS annotation value; check the ACS notes page before continuing"
        )


def clean_pair(estimate: pd.Series, moe: pd.Series) -> tuple[pd.Series, pd.Series, dict[str, int]]:
    """Return (estimate, moe, sentinel counts) as float64 with sentinels replaced.

    Counts are keyed ``"estimate:<value>"`` / ``"moe:<value>"`` for ``metadata.json``.
    """
    est = _numeric(estimate)
    err = _numeric(moe)
    _check_unknown(est, "estimate")
    _check_unknown(err, "moe")

    counts: Counter[str] = Counter()
    for column, series in (("estimate", est), ("moe", err)):
        found = series[series.isin(ALL_SENTINELS)].value_counts()
        for value, n in zip(found.index.tolist(), found.tolist(), strict=True):
            counts[f"{column}:{int(value)}"] += int(n)

    est = est.mask(est.isin(ALL_SENTINELS), np.nan)
    err = err.mask(err.isin(_MOE_NULL), np.nan).mask(err == _MOE_ZERO, 0.0)
    err = err.mask(est.isna(), np.nan)  # a null estimate never carries a MOE
    return est, err, dict(counts)


def median_code(annotation: pd.Series) -> pd.Series:
    """``top``/``bottom``/``none`` from a median's estimate-annotation field.

    Accepts the documented ``median+`` / ``median-`` and the numeric forms such as ``250000+``.
    A bare ``-`` is the annotation of an uncomputable estimate, not a bottom code. (The exact
    strings the API returns are checked against real data in Phase 4.)
    """

    def one(value: object) -> str:
        if not isinstance(value, str):
            return "none"
        text = value.strip()
        if text == "median+" or _TOP.match(text):
            return "top"
        if text == "median-" or _BOTTOM.match(text):
            return "bottom"
        return "none"

    return annotation.map(one).astype("object")


def clean_frame(
    raw: pd.DataFrame, key: str, variables: Mapping[str, bool]
) -> tuple[pd.DataFrame, dict[str, int]]:
    """Clean a raw API frame into ``<VAR>_e`` / ``<VAR>_m`` (and ``<VAR>_code`` for medians).

    ``key`` names the geography column (kept as the string index ``zip``); ``variables`` maps each
    variable ID to whether it is a median (needs the ``<VAR>EA`` annotation column).
    """
    out = pd.DataFrame(index=pd.Index(raw[key].astype(str), name="zip"))
    totals: Counter[str] = Counter()
    for var, is_median in variables.items():
        est, err, counts = clean_pair(raw[f"{var}E"], raw[f"{var}M"])
        out[f"{var}_e"] = est.to_numpy()
        out[f"{var}_m"] = err.to_numpy()
        totals.update(counts)
        if is_median:
            ea = raw[f"{var}EA"] if f"{var}EA" in raw.columns else pd.Series([None] * len(raw))
            out[f"{var}_code"] = median_code(ea).to_numpy()
    return out, dict(totals)
