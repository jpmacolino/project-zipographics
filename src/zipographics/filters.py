"""Filter rules and their evaluation, policy-enforced (SPEC §5.5, §5.7, §6.2).

A rule compares one metric of each ZIP (its own full-ZIP value, or its index against the chosen
benchmark) with a threshold. Rules combine with AND. Null values never qualify. A top- or
bottom-coded median compares as a *bound*: "$250,000+" satisfies ``>= 200,000`` but is
"uncertain" for ``<= 300,000`` and does not qualify.

Restricted mode is enforced here, not only in the UI: ``apply`` refuses any non-empty rule list
(for every metric, tagged or not) before it looks at the rules.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from zipographics import metrics
from zipographics.analysis import Analysis
from zipographics.models import Rule
from zipographics.restricted import require_unrestricted
from zipographics.stats import coded_bound
from zipographics.ui import GEQ, LEQ, displayed_value, fmt_threshold

MAX_RULES = 6


@dataclass(frozen=True, slots=True)
class ZipMatch:
    zip: str
    qualifies: bool
    #: it passes every rule but at least one passing comparison rests on an unreliable estimate
    on_unreliable: bool = False
    #: metrics whose coded median bound could not decide a rule (so the ZIP did not qualify)
    uncertain: tuple[str, ...] = ()


@dataclass(frozen=True)
class FilterResult:
    rules: tuple[Rule, ...]
    active: bool
    qualifying: tuple[str, ...]
    matches: dict[str, ZipMatch]
    unreliable_matches: tuple[str, ...]
    matching_households: float
    total_households: float

    def summary_line(self) -> str | None:
        """ "7 of 15 ZIPs match (households: 12,400 of 31,900)"; None when no rule is active."""
        if not self.active:
            return None
        return (
            f"{len(self.qualifying)} of {len(self.matches)} ZIPs match "
            f"(households: {self.matching_households:,.0f} of {self.total_households:,.0f})"
        )


def describe(rule: Rule) -> str:
    """A rule in words: ``Homeowners >= 60 %`` or ``Households with children, index >= 115``."""
    metric = metrics.BY_ID[rule.metric]
    sign = GEQ if rule.op == ">=" else LEQ
    threshold = fmt_threshold(metric, rule.value, rule.basis)
    if rule.basis == "index":
        return f"{metric.name}, index {sign} {threshold}"
    return f"{metric.name} {sign} {threshold}"


def validate(rules: Sequence[Rule]) -> None:
    """Raise ``ValueError`` for a rule list the evaluator cannot run."""
    if len(rules) > MAX_RULES:
        raise ValueError(f"Use at most {MAX_RULES} rules.")
    for r in rules:
        if r.metric not in metrics.BY_ID:
            raise ValueError(f"Unknown metric: {r.metric!r}")
        metric = metrics.BY_ID[r.metric]
        if r.op not in (">=", "<="):
            raise ValueError(f"Unknown comparison {r.op!r}: use >= or <=.")
        if r.basis not in ("value", "index"):
            raise ValueError(f"Unknown basis {r.basis!r}: use value or index.")
        if not math.isfinite(r.value):
            raise ValueError("A rule's value must be a finite number.")
        if r.basis == "index" and not metric.indexable:
            raise ValueError(f"{metric.name} is a count and has no index; compare its value.")
        if r.basis == "value" and metric.unit == "percent" and not 0 <= r.value <= 1:
            raise ValueError(f"{metric.name} is a share: give a fraction between 0 and 1.")


def _test(op: str, x: float, threshold: float) -> bool:
    """``x op threshold`` with slack for float noise (7.0 % shown is not 0.07 plus 1e-17)."""
    slack = 1e-9 * max(1.0, abs(threshold))
    return x >= threshold - slack if op == ">=" else x <= threshold + slack


def _judge(a: Analysis, rule: Rule, i: int, zip_code: str) -> tuple[bool, bool, bool]:
    """(passes, unreliable, uncertain) of one rule for one ZIP."""
    value = a.value(zip_code, rule.metric)
    est = value.estimate
    if est is None:
        return False, False, False
    if rule.basis == "index":
        idx = a.zip_index(rule.metric)[i]
        if idx.value is None:  # unknown or coded: no index
            return False, False, False
        return _test(rule.op, idx.value, rule.value), idx.tier == "unreliable", False
    unreliable = value.tier == "unreliable"
    metric = metrics.BY_ID[rule.metric]
    if value.code == "none":
        return _test(rule.op, displayed_value(metric, est), rule.value), unreliable, False
    bound = displayed_value(metric, coded_bound(est, value.code))
    if value.code == "top":  # the true value is at least `bound`
        if rule.op == ">=":
            ok = bound >= rule.value
            return ok, False, not ok  # below the bound's reach the true value may still be >= v
        return False, False, bound <= rule.value  # at most v: unknowable; below the bound: no
    if rule.op == "<=":  # bottom-coded: the true value is at most `bound`
        ok = bound <= rule.value
        return ok, False, not ok
    return False, False, bound >= rule.value


def apply(
    a: Analysis,
    rules: Sequence[Rule],
    *,
    exclude_unreliable: bool = False,
) -> FilterResult:
    """Evaluate ``rules`` (AND) over the recognized ZIPs of ``a``.

    The policy is the Analysis's own (there is no second one to pass). Raises
    :class:`~zipographics.errors.RestrictedUseError` when it is restricted and ``rules`` is not
    empty. An empty list means no filtering: every ZIP qualifies.
    """
    if rules:
        require_unrestricted(a.policy, "filter")
        validate(rules)
    hh = a.table.columns["hh"].est if "hh" in a.table.columns else None
    matches: dict[str, ZipMatch] = {}
    for i, z in enumerate(a.zips):
        if not rules:
            matches[z] = ZipMatch(z, True)
            continue
        passes, flagged, uncertain = True, False, []
        for r in rules:
            ok, bad, unsure = _judge(a, r, i, z)
            passes &= ok
            flagged |= ok and bad
            if unsure:
                uncertain.append(r.metric)
        keep = passes and not (flagged and exclude_unreliable)
        matches[z] = ZipMatch(
            z, keep, flagged if passes else False, () if passes else tuple(uncertain)
        )
    qualifying = tuple(z for z in a.zips if matches[z].qualifies)
    unreliable = tuple(z for z in a.zips if matches[z].on_unreliable)
    # the summary follows the In-radius / Full toggle, like the KPI cards (DECISIONS P15)
    households = [
        (a.in_radius(z, "hh") or 0.0)
        if a.weighted
        else (float(hh[i]) if hh is not None and hh[i] == hh[i] else 0.0)
        for i, z in enumerate(a.zips)
    ]
    pos = {z: i for i, z in enumerate(a.zips)}
    return FilterResult(
        rules=tuple(rules),
        active=bool(rules),
        qualifying=qualifying,
        matches=matches,
        unreliable_matches=unreliable,
        matching_households=sum(households[pos[z]] for z in qualifying),
        total_households=sum(households),
    )


__all__ = ["MAX_RULES", "FilterResult", "ZipMatch", "apply", "describe", "validate"]
