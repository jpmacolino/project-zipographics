"""Trade-area aggregation, the per-ZIP table, benchmarks and the index (SPEC §5.5, §6).

One engine computes every metric from a *frame*: a DataFrame indexed by 5-character ZIP (or, for
benchmarks, by geography id) with ``<key>_e`` / ``<key>_m`` columns for each registry variable and
``<key>_code`` for published medians. The engine reduces component arrays either over components
only (per-ZIP table) or over components and ZIPs (trade area), so both paths share the formulas.

Rules (SPEC §4.6): medians are never averaged (several ZIPs interpolate from summed brackets;
a single geography shows the published median); aggregated MOEs are approximations; overlap
weights multiply counts and MOEs; unknown inputs give unknown outputs; a sum that loses a null
component is flagged ``incomplete``.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal

import numpy as np
import pandas as pd
from numpy.typing import NDArray

from zipographics import metrics, stats, vstats
from zipographics.facts import (
    STATE_FIPS,
    STATE_NAMES,
    StateEntry,
    StateTotals,
    state_entries,
)
from zipographics.metrics import (
    CountSpec,
    Metric,
    ProductMeanSpec,
    RatioSpec,
    ShareSpec,
)
from zipographics.stats import MedianCode, Tier

Source = Literal["published", "derived", "interpolated"]
F = NDArray[np.float64]

#: ACS annotation values are all at or below this; any frame value this low escaped the build.
_SENTINEL_FLOOR = -100_000_000
_CODES = {"none", "top", "bottom"}


@dataclass(frozen=True, slots=True)
class MetricValue:
    """One metric for the trade area or one ZIP. Shares are fractions (0-1), MOE alike."""

    metric_id: str
    estimate: float | None
    moe: float | None
    tier: Tier
    code: MedianCode = "none"
    incomplete: bool = False
    source: Source = "derived"


@dataclass(frozen=True, slots=True)
class IndexValue:
    value: int | None
    tier: Tier


@dataclass(frozen=True)
class TradeAreaProfile:
    zips: tuple[str, ...]
    weighted: bool
    values: dict[str, MetricValue]


# ----------------------------------------------------------------------------- data access
class _Data:
    """The columns a set of metrics needs, gathered once as float arrays of shape (n_zips,)."""

    def __init__(self, frame: pd.DataFrame, zips: Sequence[str], metric_list: Sequence[Metric]):
        if not zips:
            raise ValueError("no ZIPs to profile")
        if len(set(zips)) != len(zips):
            raise ValueError("duplicate ZIPs in the input would be counted twice")
        missing_zip = next((z for z in zips if z not in frame.index), None)
        if missing_zip is not None:
            raise KeyError(missing_zip)
        keys: dict[str, None] = {}
        for metric in metric_list:
            for key in metrics.variable_keys(metric):
                keys.setdefault(key)
        columns: list[str] = []
        for key in keys:
            columns += [f"{key}_e", f"{key}_m"]
            if metrics.VARIABLES[key].is_median:
                columns.append(f"{key}_code")  # a published median without its code fails open
        for col in columns:
            if col not in frame.columns:
                raise ValueError(f"frame is missing column {col}")
        sub = frame.loc[list(zips)]
        self.n = len(zips)
        self._e = {k: pd.to_numeric(sub[f"{k}_e"], errors="coerce").to_numpy(float) for k in keys}
        self._m = {k: pd.to_numeric(sub[f"{k}_m"], errors="coerce").to_numpy(float) for k in keys}
        for k in keys:  # the build nulls sentinels; refuse them here rather than sum them
            for col, arr in ((f"{k}_e", self._e[k]), (f"{k}_m", self._m[k])):
                if np.any(arr <= _SENTINEL_FLOOR):
                    raise ValueError(f"sentinel value in column {col}: the build must null these")
        for col in (c for c in columns if c.endswith("_code")):
            bad = set(sub[col].astype(object).tolist()) - _CODES
            if bad:
                raise ValueError(f"invalid median code in {col}: {sorted(map(str, bad))}")
        self._frame = sub

    def block(self, keys: Sequence[str]) -> tuple[F, F]:
        return np.vstack([self._e[k] for k in keys]), np.vstack([self._m[k] for k in keys])

    def code(self, key: str) -> NDArray[np.object_]:
        return self._frame[f"{key}_code"].to_numpy(dtype=object)


@dataclass(slots=True)
class _Agg:
    est: F
    moe: F
    incomplete: NDArray[np.bool_]


def _agg(e: F, m: F, coef: F, w: F, axes: tuple[int, ...]) -> _Agg:
    """Σ coef·w·x with MOE sqrt(Σ (coef·w·moe)²); null components are excluded and flagged."""
    we = e * coef[:, None] * w[None, :]
    wm = m * coef[:, None] * w[None, :]
    present = ~np.isnan(we)
    any_present = present.any(axis=axes)
    est = np.where(any_present, np.nansum(we, axis=axes), np.nan)
    moe_ok = ~(present & np.isnan(wm)).any(axis=axes)
    sq = np.where(present & ~np.isnan(wm), wm**2, 0.0).sum(axis=axes)
    moe = np.where(any_present & moe_ok, np.sqrt(sq), np.nan)
    return _Agg(est, moe, (~present).any(axis=axes))


def _ones(k: int) -> F:
    return np.ones(k)


# ----------------------------------------------------------------------------- one metric
@dataclass(slots=True)
class _Result:
    est: F
    moe: F
    incomplete: NDArray[np.bool_]
    code: NDArray[np.object_]
    source: Source


def _compute(
    metric: Metric, data: _Data, w: F, axes: tuple[int, ...], *, published_medians: bool
) -> _Result:
    spec = metric.spec
    shape = () if axes == (0, 1) else (data.n,)
    none_code = np.full(shape, "none", dtype=object)
    nan = np.full(shape, np.nan)

    if isinstance(spec, CountSpec):
        e, m = data.block([spec.var])
        a = _agg(e, m, _ones(1), w, axes)
        # a count scaled by an overlap weight is an estimate, not a published figure
        single = axes == (0,) or (data.n == 1 and bool(w[0] == 1.0))
        return _Result(a.est, a.moe, a.incomplete, none_code, "published" if single else "derived")

    if isinstance(spec, ShareSpec):
        num = _agg(*data.block(spec.num), _ones(len(spec.num)), w, axes)
        den = _agg(*data.block(spec.den), _ones(len(spec.den)), w, axes)
        with np.errstate(divide="ignore", invalid="ignore"):
            raw = num.est / den.est
        valid = ~np.isnan(num.est) & (den.est > 0)
        out_of_range = valid & ((raw > 1 + 1e-9) | (raw < 0))
        est = np.where(valid, np.clip(raw, 0.0, 1.0), np.nan)
        moe = vstats.moe_proportion(num.est, num.moe, den.est, den.moe)
        moe = np.where(valid, moe, np.nan)
        return _Result(
            est, moe, num.incomplete | den.incomplete | out_of_range, none_code, "derived"
        )

    if isinstance(spec, RatioSpec):
        coef = np.array([c for _, c in spec.num], dtype=float)
        num = _agg(*data.block([k for k, _ in spec.num]), coef, w, axes)
        den = _agg(*data.block(spec.den), _ones(len(spec.den)), w, axes)
        with np.errstate(divide="ignore", invalid="ignore"):
            est = np.where((den.est > 0) & ~np.isnan(num.est), num.est / den.est, np.nan)
        moe = np.where(np.isnan(est), np.nan, vstats.moe_ratio(num.est, num.moe, den.est, den.moe))
        return _Result(est, moe, num.incomplete | den.incomplete, none_code, "derived")

    if isinstance(spec, ProductMeanSpec):
        return _per_capita(spec, data, w, axes, none_code)

    # median
    if published_medians:
        e, m = data.block([spec.published])
        est = e[0] if axes == (0,) else e[0, 0]
        moe = m[0] if axes == (0,) else m[0, 0]
        code = data.code(spec.published)
        return _Result(
            np.asarray(est, dtype=float),
            np.where(np.isnan(est), np.nan, moe),
            np.zeros(shape, dtype=bool),
            code if axes == (0,) else code[0],
            "published",
        )
    return _interpolated_median(spec, data, w, nan)


def _per_capita(
    spec: ProductMeanSpec,
    data: _Data,
    w: F,
    axes: tuple[int, ...],
    none_code: NDArray[np.object_],
) -> _Result:
    rate_e, rate_m = data.block([spec.rate])
    base_e, base_m = data.block([spec.base])
    if axes == (0,) or data.n == 1:  # one geography: the published per-capita income
        est, moe = rate_e[0], rate_m[0]
        shape = est.shape if axes == (0,) else ()
        est_out = est if axes == (0,) else np.asarray(est[0])
        moe_out = moe if axes == (0,) else np.asarray(moe[0])
        return _Result(
            est_out,
            np.where(np.isnan(est_out), np.nan, moe_out),
            np.zeros(shape, dtype=bool),
            none_code,
            "published",
        )
    a, ma = rate_e[0], rate_m[0]
    b, mb = base_e[0] * w, base_m[0] * w
    valid = ~np.isnan(a) & ~np.isnan(b)  # a ZIP without a rate leaves numerator and base
    n_est = np.where(valid, a * b, np.nan)
    n_moe = np.where(valid, vstats.moe_product(a, ma, b, mb), np.nan)
    d_est = np.where(valid, b, np.nan)
    d_moe = np.where(valid, mb, np.nan)
    ones = _ones(1)
    unit = np.ones(data.n)
    num = _agg(n_est[None, :], n_moe[None, :], ones, unit, (0, 1))
    den = _agg(d_est[None, :], d_moe[None, :], ones, unit, (0, 1))
    with np.errstate(divide="ignore", invalid="ignore"):
        est = np.where((den.est > 0) & ~np.isnan(num.est), num.est / den.est, np.nan)
    moe = np.where(np.isnan(est), np.nan, vstats.moe_ratio(num.est, num.moe, den.est, den.moe))
    incomplete = np.asarray(num.incomplete | den.incomplete | (~valid).any())
    return _Result(est, moe, incomplete, none_code, "derived")


def _interpolated_median(spec: metrics.MedianSpec, data: _Data, w: F, nan: F) -> _Result:
    counts: list[float | None] = []
    moes: list[float | None] = []
    incomplete = False
    for bracket in spec.brackets:
        agg = _agg(*data.block(bracket.keys), _ones(len(bracket.keys)), w, (0, 1))
        b_est, b_moe = float(agg.est), float(agg.moe)
        incomplete = incomplete or bool(agg.incomplete)
        if np.isnan(b_est):  # excluded bracket: counts as 0 and is flagged
            counts.append(0.0)
            moes.append(0.0)
            incomplete = True
        else:
            counts.append(b_est)
            moes.append(None if np.isnan(b_moe) else b_moe)
    bounds = [(b.lo, b.hi) for b in spec.brackets]
    median = stats.median_from_counts([c or 0.0 for c in counts], bounds)
    if median is None:
        return _Result(
            nan, nan, np.asarray(incomplete), np.asarray("none", dtype=object), "interpolated"
        )
    moe = stats.median_moe(counts, moes, bounds) if median.code == "none" else None
    return _Result(
        np.asarray(median.value),
        np.asarray(np.nan if moe is None else moe),
        np.asarray(incomplete),
        np.asarray(median.code, dtype=object),
        "interpolated",
    )


def _scalar(metric: Metric, r: _Result) -> MetricValue:
    est = None if np.isnan(r.est) else float(r.est)
    moe = None if np.isnan(r.moe) else float(r.moe)
    code: MedianCode = str(r.code)  # type: ignore[assignment]
    return MetricValue(
        metric.id,
        est,
        moe,
        stats.tier(est, moe, coded=code != "none"),
        code,
        bool(r.incomplete),
        r.source,
    )


# ----------------------------------------------------------------------------- public: trade area
def _select(metric_ids: Sequence[str] | None) -> list[Metric]:
    return list(metrics.REGISTRY) if metric_ids is None else [metrics.BY_ID[i] for i in metric_ids]


def build_profile(
    frame: pd.DataFrame,
    zips: Sequence[str],
    *,
    weights: Mapping[str, float] | None = None,
    metric_ids: Sequence[str] | None = None,
) -> TradeAreaProfile:
    """The trade-area value of each metric for ``zips``.

    ``weights`` maps ZIP -> overlap fraction in (0, 1] (Zipcator input); ZIPs not mentioned get 1.
    One ZIP (or one benchmark geography) shows published medians and counts; several ZIPs
    interpolate medians from summed brackets.
    """
    for z, wt in (weights or {}).items():
        if not (math.isfinite(wt) and 0 < wt <= 1):
            raise ValueError(f"overlap weight for {z} must be in (0, 1], got {wt}")
    selected = _select(metric_ids)
    data = _Data(frame, zips, selected)
    w = np.array([1.0 if weights is None else weights.get(z, 1.0) for z in zips], dtype=float)
    single = data.n == 1
    values: dict[str, MetricValue] = {}
    for metric in selected:
        r = _compute(metric, data, w, (0, 1), published_medians=single)
        values[metric.id] = _scalar(metric, r)
    return TradeAreaProfile(tuple(zips), weights is not None, values)


# ----------------------------------------------------------------------------- public: per ZIP
@dataclass(frozen=True)
class ZipColumn:
    est: F
    moe: F
    tier: NDArray[np.object_]
    code: NDArray[np.object_]
    incomplete: NDArray[np.bool_]
    source: Source


@dataclass(frozen=True)
class ZipTable:
    zips: tuple[str, ...]
    columns: dict[str, ZipColumn]
    _position: dict[str, int] = field(repr=False, default_factory=dict)

    def value(self, zip_code: str, metric_id: str) -> MetricValue:
        i = self._position[zip_code]
        c = self.columns[metric_id]
        est, moe = c.est[i], c.moe[i]
        return MetricValue(
            metric_id,
            None if np.isnan(est) else float(est),
            None if np.isnan(moe) else float(moe),
            c.tier[i],
            str(c.code[i]),  # type: ignore[arg-type]
            bool(c.incomplete[i]),
            c.source,
        )

    def index_column(self, metric_id: str, benchmark: float | None) -> list[int | None]:
        """Per-ZIP index against a benchmark estimate; null for unknown or coded values."""
        c = self.columns[metric_id]
        idx = vstats.index_values(c.est, benchmark)
        idx = np.where(c.code != "none", np.nan, idx)
        return [None if np.isnan(v) else int(v) for v in idx]


def zip_table(
    frame: pd.DataFrame, zips: Sequence[str], *, metric_ids: Sequence[str] | None = None
) -> ZipTable:
    """Full-ZIP values of each metric for each ZIP (published medians), computed together."""
    selected = _select(metric_ids)
    data = _Data(frame, zips, selected)
    w = np.ones(data.n)
    columns: dict[str, ZipColumn] = {}
    for metric in selected:
        r = _compute(metric, data, w, (0,), published_medians=True)
        coded = r.code != "none"
        columns[metric.id] = ZipColumn(
            np.asarray(r.est, dtype=float),
            np.asarray(r.moe, dtype=float),
            vstats.tier(np.asarray(r.est, dtype=float), np.asarray(r.moe, dtype=float), coded),
            r.code,
            np.asarray(r.incomplete, dtype=bool),
            r.source,
        )
    return ZipTable(tuple(zips), columns, {z: i for i, z in enumerate(zips)})


# ----------------------------------------------------------------------------- index
def index_of(trade: MetricValue, bench: MetricValue) -> IndexValue:
    """``100 * trade / benchmark`` (SPEC §6.8); null if either side is unusable.

    Unusable: null estimate, a top/bottom-coded value (no index: "above the published range"),
    or a zero benchmark. The tier is the worse of the two inputs' tiers.
    """
    tier = stats.worse_tier(trade.tier, bench.tier)
    if trade.code != "none" or bench.code != "none":
        return IndexValue(None, tier)
    return IndexValue(stats.index_value(trade.estimate, bench.estimate), tier)


def index_profile(trade: TradeAreaProfile, bench: TradeAreaProfile) -> dict[str, IndexValue]:
    """Index of every indexable metric (counts use :func:`share_of` instead)."""
    return {
        mid: index_of(v, bench.values[mid])
        for mid, v in trade.values.items()
        if metrics.BY_ID[mid].indexable and mid in bench.values
    }


def share_of(trade: MetricValue, bench: MetricValue) -> float | None:
    """A count's share of the benchmark's total ("1.4 % of Florida's households")."""
    if trade.estimate is None or bench.estimate is None or bench.estimate <= 0:
        return None
    return trade.estimate / bench.estimate


# ----------------------------------------------------------------------------- benchmarks
def benchmark_profile(
    benchmarks: pd.DataFrame,
    level: str,
    geo_id: str,
    *,
    metric_ids: Sequence[str] | None = None,
) -> TradeAreaProfile:
    """Published values for one benchmark geography (a row of ``benchmarks.parquet``)."""
    rows = benchmarks[(benchmarks["geo_level"] == level) & (benchmarks["geo_id"] == geo_id)]
    if rows.empty:
        raise KeyError(f"{level}:{geo_id}")
    frame = rows.iloc[:1].set_index("geo_id")
    return build_profile(frame, [geo_id], metric_ids=metric_ids)


@dataclass(frozen=True, slots=True)
class BenchmarkRef:
    level: Literal["state", "county", "us"]
    geo_id: str
    name: str


@dataclass(frozen=True)
class BenchmarkOptions:
    """What the benchmark selector offers (SPEC §5.5) and the default for each level."""

    default: BenchmarkRef  # the dominant state
    default_county: BenchmarkRef | None
    states: tuple[BenchmarkRef, ...]  # represented states, largest input population first
    counties: tuple[BenchmarkRef, ...]
    us: BenchmarkRef
    puerto_rico_note: str | None


_COUNTY_ID = re.compile(r"[0-9]{5}")

PR_NOTE = (
    "The national benchmark covers the 50 states and DC; the Census Bureau's U.S. figures "
    "exclude Puerto Rico, so Puerto Rico ZIPs are compared with it only for context."
)


def _by_population(entries: Sequence[StateEntry]) -> list[str]:
    totals: dict[str, float] = {}
    for e in entries:
        totals[e.state] = totals.get(e.state, 0.0) + e.population
    return sorted(totals, key=lambda g: -totals[g])  # stable: ties keep first-seen order


def benchmark_options(zips: Sequence[str], facts: pd.DataFrame) -> BenchmarkOptions:
    """Benchmark choices for recognized ZIPs: default state, default county, national (§6.8).

    State and county ids are FIPS: a state's two digits, a county's five (state + county).
    """
    # the ACS ZCTA benchmarks cover the 50 states, DC and Puerto Rico only
    states = [e for e in state_entries(zips, facts) if e.state in STATE_FIPS]
    if not states:
        raise ValueError("no recognized ZIPs have a state")
    default_state = StateTotals(states).dominant()
    assert default_state is not None
    state_refs = tuple(
        BenchmarkRef("state", STATE_FIPS[s], STATE_NAMES.get(s, s)) for s in _by_population(states)
    )
    default_ref = BenchmarkRef("state", STATE_FIPS[default_state], STATE_NAMES[default_state])

    county_refs: tuple[BenchmarkRef, ...] = ()
    default_county: BenchmarkRef | None = None
    if "county_fips" in facts.columns:
        counties = [
            e
            for e in state_entries(zips, facts, column="county_fips")
            if _COUNTY_ID.fullmatch(e.state)  # 5 digits: state + county, never a bare county code
        ]
        if counties:
            names = facts["county"].to_dict() if "county" in facts.columns else {}
            first_name: dict[str, str] = {}
            for e in counties:
                name = names.get(e.zip)
                label = name if isinstance(name, str) and name.strip() else e.state
                first_name.setdefault(e.state, label)
            order = _by_population(counties)
            county_refs = tuple(BenchmarkRef("county", g, first_name[g]) for g in order)
            top = StateTotals(counties).dominant()
            default_county = next(r for r in county_refs if r.geo_id == top)

    has_pr = any(e.state == "PR" for e in states)
    return BenchmarkOptions(
        default=default_ref,
        default_county=default_county,
        states=state_refs,
        counties=county_refs,
        us=BenchmarkRef("us", "1", "United States"),
        puerto_rico_note=PR_NOTE if has_pr else None,
    )
