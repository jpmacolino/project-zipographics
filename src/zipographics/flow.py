"""Small wiring helpers for the Streamlit app: step gating, benchmark choices, filter-rule input
conversion, sort choices. Kept in the library so they are unit-tested; the app file is layout only
(SPEC §8).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from zipographics import metrics, verticals
from zipographics.analysis import Analysis
from zipographics.models import Basis, Op, Rule, UsePolicy
from zipographics.profile import BenchmarkOptions, BenchmarkRef
from zipographics.review import review_lines


# ------------------------------------------------------------------------- step 1
def step1_ready(industry: str | None, answer: str | None) -> bool:
    """Continue is enabled once the industry is chosen and the question answered (a restricted
    industry's question is pre-answered)."""
    if industry is None or industry not in verticals.BY_NAME:
        return False
    return verticals.is_locked(industry) or answer in ("Yes", "No")


def policy_for(industry: str, answer: str | None) -> UsePolicy:
    """The Step-1 policy: ``answer`` is "Yes", "No" or None (locked industries need none)."""
    return verticals.make_policy(industry, None if answer is None else answer == "Yes")


# ------------------------------------------------------------------------- benchmark
@dataclass(frozen=True, slots=True)
class BenchmarkChoice:
    label: str
    ref: BenchmarkRef


_LEVEL = {"state": "state", "county": "county", "us": "national"}


def benchmark_choices(options: BenchmarkOptions) -> list[BenchmarkChoice]:
    """State(s) represented (default first), counties represented, then the nation."""
    refs = [options.default] + [r for r in options.states if r != options.default]
    counties = list(options.counties)
    if options.default_county is not None:  # the default county leads the county group
        counties = [options.default_county] + [r for r in counties if r != options.default_county]
    refs += [*counties, options.us]
    out: list[BenchmarkChoice] = []
    seen: set[str] = set()
    for r in refs:
        label = f"{r.name} ({_LEVEL[r.level]})"
        if label not in seen:
            seen.add(label)
            out.append(BenchmarkChoice(label, r))
    return out


def find_choice(choices: list[BenchmarkChoice], label: str | None) -> BenchmarkChoice:
    """The choice called ``label``, or the first (the default) when there is none."""
    return next((c for c in choices if c.label == label), choices[0])


def span_message(a: Analysis) -> str | None:
    """ "Your ZIPs are in FL and GA. Benchmark: Florida ..." when the ZIPs span states."""
    return next((x for x in review_lines(a.summary) if x.startswith("Your ZIPs are in")), None)


# ------------------------------------------------------------------------- filter rules
def _percent_value(metric: str, basis: str) -> bool:
    return basis == "value" and metrics.BY_ID[metric].unit == "percent"


def rule_from_inputs(metric: str, op: str, number: float, basis: str) -> Rule:
    """A rule from what the user typed: a share is typed as a percent (60), stored as 0.6."""
    value = number / 100 if _percent_value(metric, basis) else number
    return Rule(metric, op, float(value), basis)  # type: ignore[arg-type]


def rule_to_inputs(rule: Rule) -> tuple[str, Op, float, Basis]:
    """The widget values for a rule (the inverse of :func:`rule_from_inputs`)."""
    number = rule.value * 100 if _percent_value(rule.metric, rule.basis) else rule.value
    return rule.metric, rule.op, round(number, 6), rule.basis


def value_unit(metric: str, basis: str) -> Literal["%", "$", "index", ""]:
    """The unit shown next to a rule's number."""
    if basis == "index":
        return "index"
    unit = metrics.BY_ID[metric].unit
    return "%" if unit == "percent" else "$" if unit == "dollars" else ""


def metric_labels() -> dict[str, str]:
    return {m.id: m.name for m in metrics.REGISTRY}


def bases_for(metric: str) -> list[str]:
    return ["value", "index"] if metrics.BY_ID[metric].indexable else ["value"]


# ------------------------------------------------------------------------- table ordering
def sort_choices(*, restricted: bool) -> list[tuple[str, str]]:
    """(key, label) choices for "Sort by": restricted mode offers only as-entered and by ZIP."""
    if restricted:
        return [("input", "As entered"), ("zip", "By ZIP")]
    return [("input", "Input order"), ("zip", "ZIP"), *[(m.id, m.name) for m in metrics.REGISTRY]]
