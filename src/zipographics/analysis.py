"""One analysis object shared by the app, the exports, the report and the CLI (SPEC §5.4-5.5, §6).

``analyze`` takes the loaded artifacts, the parsed input and the Step-1 policy, and computes
everything a dashboard needs once: the review summary, the trade-area profile (overlap-weighted
when Zipcator data is present), the benchmark profile and indexes, and the per-ZIP table. Nothing
here selects ZIPs by demographics, so restricted mode computes the same numbers (it only limits
what may be *done* with them: see ``filters``, ``table`` and ``export``).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal

import pandas as pd

from zipographics import config, data, metrics, profile, stats
from zipographics.lenses import Lens, resolve
from zipographics.lenses import get as get_lens
from zipographics.models import ParsedInput, ReviewSummary, UsePolicy
from zipographics.profile import (
    BenchmarkOptions,
    BenchmarkRef,
    IndexValue,
    MetricValue,
    TradeAreaProfile,
    ZipTable,
)
from zipographics.restricted import is_restricted
from zipographics.review import summarize
from zipographics.ui import clean_text
from zipographics.verticals import BY_NAME, CONTEXT_LENS

Mode = Literal["full", "in_radius"]


@dataclass(frozen=True)
class Analysis:
    policy: UsePolicy
    project_name: str | None
    parsed: ParsedInput
    summary: ReviewSummary
    zips: tuple[str, ...]  # recognized ZIPs in input order
    mode: Mode
    weights: Mapping[str, float] | None  # in-radius only: ZIP -> overlap fraction
    options: BenchmarkOptions
    benchmark: BenchmarkRef
    trade: TradeAreaProfile
    bench: TradeAreaProfile
    index: dict[str, IndexValue]
    table: ZipTable
    lens: Lens
    vintage: int
    metadata: Mapping[str, object]
    attrs: pd.DataFrame  # recognized ZIPs: city, county, state
    # per-metric index columns, computed once (filters and exports ask for each many times)
    _index_cache: dict[str, list[IndexValue]] = field(
        default_factory=dict, init=False, repr=False, compare=False
    )

    # ------------------------------------------------------------------ labels
    @property
    def restricted(self) -> bool:
        """Restricted mode, read the strict way: the policy says so, or it names a restricted
        industry (so a policy built by mistake as unrestricted cannot unlock anything)."""
        return is_restricted(self.policy)

    @property
    def weighted(self) -> bool:
        return self.mode == "in_radius"

    @property
    def vintage_label(self) -> str:
        return f"ACS {self.vintage - 4}-{self.vintage} 5-year estimates"

    @property
    def title(self) -> str:
        return self.project_name or "Untitled project"

    # ------------------------------------------------------------------ values
    def value(self, zip_code: str, metric_id: str) -> MetricValue:
        """The full-ZIP value (published medians) of one metric for one recognized ZIP."""
        return self.table.value(zip_code, metric_id)

    def weight_of(self, zip_code: str) -> float:
        return 1.0 if self.weights is None else self.weights.get(zip_code, 1.0)

    def in_radius(self, zip_code: str, metric_id: str) -> float | None:
        """A count scaled by the ZIP's overlap (in-radius households or population); None when
        in-radius estimates are off or the count is unknown."""
        if self.weights is None:
            return None
        est = self.value(zip_code, metric_id).estimate
        return None if est is None else est * self.weight_of(zip_code)

    def zip_index(self, metric_id: str) -> list[IndexValue]:
        """Per-ZIP index against the benchmark, aligned with ``zips``; the tier is the worse of
        the ZIP's and the benchmark's (SPEC §6.8)."""
        cached = self._index_cache.get(metric_id)
        if cached is not None:
            return cached
        bench = self.bench.values[metric_id]
        values = self.table.index_column(metric_id, bench.estimate)
        col = self.table.columns[metric_id]
        out = [
            IndexValue(v, stats.worse_tier(col.tier[i], bench.tier)) for i, v in enumerate(values)
        ]
        self._index_cache[metric_id] = out
        return out

    def overlap_pct(self, zip_code: str) -> float | None:
        """The ZIP's overlap in percent (100 for a ZIP with no overlap value, which counts as a
        full ZIP); None when in-radius estimates are off."""
        return None if self.weights is None else self.weight_of(zip_code) * 100

    def share_of_benchmark(self, metric_id: str) -> float | None:
        """A count's share of the benchmark's total ("1.4 % of Florida's households")."""
        return profile.share_of(self.trade.values[metric_id], self.bench.values[metric_id])

    def row_facts(self, zip_code: str) -> dict[str, str | None]:
        row = self.attrs.loc[zip_code]
        return {k: (None if pd.isna(row[k]) else str(row[k])) for k in ("city", "county", "state")}


def _benchmark_ok(art: data.Artifacts, ref: BenchmarkRef) -> bool:
    b = art.benchmarks
    return bool(((b["geo_level"] == ref.level) & (b["geo_id"] == ref.geo_id)).any())


def analyze(
    art: data.Artifacts,
    parsed: ParsedInput,
    policy: UsePolicy,
    *,
    project_name: str | None = None,
    benchmark: BenchmarkRef | None = None,
    mode: Mode | None = None,
    lens: str | None = None,
    metric_ids: Sequence[str] | None = None,
) -> Analysis:
    """Profile the recognized ZIPs of ``parsed``. Raises ``ValueError`` for blocking problems
    (no recognized ZIP, more than the ZIP limit) and for an unknown benchmark or mode."""
    facts = data.facts_from_profile(art.profile)
    summary = summarize(parsed, facts, policy=policy, project_name=project_name)
    if summary.blocking:
        raise ValueError(summary.blocking[0])
    zips = summary.recognized

    if mode not in (None, "full", "in_radius"):
        raise ValueError(f"Unknown estimate mode {mode!r}: use full or in_radius.")
    if mode is None:
        mode = "in_radius" if parsed.is_zipcator and parsed.overlaps else "full"
    weights: dict[str, float] | None = None
    if mode == "in_radius":
        if not parsed.overlaps:
            raise ValueError("In-radius estimates need Zipcator overlap data (no overlap column).")
        weights = {z: parsed.overlaps[z] / 100.0 for z in zips if z in parsed.overlaps}

    options = profile.benchmark_options(zips, facts)
    ref = benchmark or options.default
    if not _benchmark_ok(art, ref):
        raise ValueError(f"The {ref.level} benchmark {ref.name!r} is not in the data.")

    ids = list(metric_ids) if metric_ids is not None else [m.id for m in metrics.REGISTRY]
    trade = profile.build_profile(art.profile, zips, weights=weights, metric_ids=ids)
    bench = profile.benchmark_profile(art.benchmarks, ref.level, ref.geo_id, metric_ids=ids)
    if lens is not None:
        chosen = resolve(lens, policy)
    elif is_restricted(policy):
        chosen = get_lens(CONTEXT_LENS)
    else:
        vertical = BY_NAME.get(policy.vertical or "")
        chosen = get_lens(vertical.lens if vertical else "General")
    name = clean_text(project_name, config.MAX_PROJECT_NAME) or None
    return Analysis(
        policy=policy,
        project_name=name,
        parsed=parsed,
        summary=summary,
        zips=tuple(zips),
        mode=mode,
        weights=weights,
        options=options,
        benchmark=ref,
        trade=trade,
        bench=bench,
        index=profile.index_profile(trade, bench),
        table=profile.zip_table(art.profile, zips, metric_ids=ids),
        lens=chosen,
        vintage=int(str(art.metadata.get("vintage", 0)) or 0),
        metadata=art.metadata,
        attrs=art.profile.loc[list(zips), ["city", "county", "state"]],
    )
