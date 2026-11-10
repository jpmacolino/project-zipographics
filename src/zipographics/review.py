"""The review-screen summary: what was recognized, repaired, rejected and flagged (SPEC §5.4).

All counts are computed here, never in the UI. :func:`review_lines` turns a summary into the
plain-text lines the screen and the CLI show, so both say the same thing.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

import pandas as pd

from zipographics.config import (
    MAX_ZIPS,
    SHOWN_INVALID,
    SHOWN_REPAIRED,
    SMALL_HOUSEHOLDS,
    SMALL_POPULATION,
)
from zipographics.facts import (
    STATE_NAMES,
    dominant_of,
    state_entries,
    validate_facts,
)
from zipographics.models import ParsedInput, ReviewSummary, UsePolicy


def summarize(
    parsed: ParsedInput,
    facts: pd.DataFrame,
    *,
    policy: UsePolicy | None = None,
    project_name: str | None = None,
) -> ReviewSummary:
    """Compare parsed input with the per-ZIP facts and collect everything worth telling the user."""
    validate_facts(facts)
    present = facts.index
    recognized = tuple(z for z in parsed.zips if z in present)
    not_found = tuple(z for z in parsed.zips if z not in present)

    no_residents: list[str] = []
    small: list[str] = []
    sub = facts.loc[list(recognized)]
    for z, pop, hh in zip(sub.index, sub["population"], sub["households"], strict=True):
        pop_known, hh_known = not math.isnan(pop), not math.isnan(hh)
        if pop_known and pop == 0:
            no_residents.append(z)
            continue
        if (pop_known and pop < SMALL_POPULATION) or (hh_known and hh < SMALL_HOUSEHOLDS):
            small.append(z)

    entries = state_entries(recognized, facts)
    state_of = {e.zip: e.state for e in entries}
    unexpected: list[tuple[str, str, str]] = []
    for tok in parsed.repaired:
        z = tok.zip
        if z is None or z not in state_of:
            continue
        rest = dominant_of(entries, exclude=z)
        if rest is not None and rest != state_of[z]:
            unexpected.append((z, state_of[z], rest))

    blocking: list[str] = []
    if not recognized:
        blocking.append("No ZIPs were recognized. Go back and check the list.")
    if len(parsed.zips) > MAX_ZIPS:
        blocking.append(
            f"Zipographics handles up to {MAX_ZIPS:,} ZIPs at a time. "
            "Split the list and run it in parts."
        )

    return ReviewSummary(
        entered=len(parsed.zips),
        recognized=recognized,
        not_found=not_found,
        no_residents=tuple(no_residents),
        repaired=parsed.repaired,
        repaired_unexpected_state=tuple(unexpected),
        truncated=parsed.truncated,
        invalid=parsed.invalid,
        duplicates=parsed.duplicates,
        small_population=tuple(small),
        zipcator=parsed.is_zipcator,
        blank_overlap=parsed.blank_overlap,
        rejected_rows=parsed.rejected_rows,
        overlap_conflicts=parsed.overlap_conflicts,
        states=tuple(sorted(set(state_of.values()))),
        benchmark_state=dominant_of(entries),
        blocking=tuple(blocking),
        industry=policy.vertical if policy else None,
        project_name=project_name,
        restricted=policy.restricted if policy else None,
    )


# ------------------------------------------------------------------------- text
def _plural(n: int, one: str, many: str) -> str:
    return one if n == 1 else many


def _listing(items: Sequence[str], limit: int) -> str:
    shown = ", ".join(items[:limit])
    return shown if len(items) <= limit else f"{shown}, and {len(items) - limit} more"


def _join_states(states: Sequence[str]) -> str:
    if len(states) <= 2:
        return " and ".join(states)
    return ", ".join(states[:-1]) + " and " + states[-1]


def review_lines(s: ReviewSummary) -> list[str]:
    """The plain-text lines for the review screen, each present only when it applies."""
    n = len(s.recognized)
    lines = [f"{n} {_plural(n, 'ZIP recognized', 'ZIPs recognized')}"]

    if s.not_found:
        k = len(s.not_found)
        listing = _listing(s.not_found, SHOWN_INVALID)
        if k == 1:
            lines.append(
                f"1 not found ({listing}): it has no residential Census data; likely a "
                "PO-box or single-organization ZIP, or not a ZIP code"
            )
        else:
            lines.append(
                f"{k} not found ({listing}): they have no residential Census data; likely "
                "PO-box or single-organization ZIPs, or not ZIP codes"
            )

    if s.no_residents:
        k = len(s.no_residents)
        listing = _listing(s.no_residents, SHOWN_INVALID)
        subject = _plural(k, f"{k} ZIP has", f"{k} ZIPs have")
        lines.append(
            f"{subject} no residential population in Census data ({listing}); "
            "kept, but contributes nothing"
        )

    if s.repaired:
        pairs = [f"{t.raw.strip()} → {t.zip}" for t in s.repaired]
        lines.append(
            f"{len(s.repaired)} repaired (leading zeros restored: "
            f"{_listing(pairs, SHOWN_REPAIRED)})"
        )

    if s.repaired_unexpected_state:
        parts = [
            f"{z} is in {state}, the rest are in {rest}"
            for z, state, rest in s.repaired_unexpected_state
        ]
        lines.append("Repaired ZIPs to check: " + "; ".join(parts))

    if s.truncated:
        lines.append(f"{len(s.truncated)} ZIP+4 truncated to 5 digits")

    if s.invalid:
        k = len(s.invalid)
        lines.append(
            f"{k} invalid {_plural(k, 'entry', 'entries')}: {_listing(s.invalid, SHOWN_INVALID)}"
        )

    if s.duplicates:
        k = s.duplicates
        lines.append(f"{k} {_plural(k, 'duplicate removed', 'duplicates removed')}")

    if s.small_population:
        k = len(s.small_population)
        subject = _plural(k, "1 has a small population", f"{k} have small populations")
        lines.append(
            f"{subject}, so some figures will be less reliable: "
            f"{_listing(s.small_population, SHOWN_INVALID)}"
        )

    if s.zipcator:
        lines.append("Zipcator export detected: in-radius estimates are on.")
        if s.blank_overlap:
            k = len(s.blank_overlap)
            if k == 1:
                head = "1 ZIP has no overlap value and is treated as a full ZIP"
            else:
                head = f"{k} ZIPs have no overlap value and are treated as full ZIPs"
            lines.append(f"{head}: {_listing(s.blank_overlap, SHOWN_INVALID)}")
        if s.rejected_rows:
            k = len(s.rejected_rows)
            rows = [f"{r.zip} ({r.raw_overlap}: {r.reason})" for r in s.rejected_rows]
            lines.append(
                f"{k} {_plural(k, 'row', 'rows')} rejected for an unusable overlap: "
                f"{_listing(rows, SHOWN_INVALID)}"
            )
        if s.overlap_conflicts:
            k = len(s.overlap_conflicts)
            head = "1 ZIP repeats" if k == 1 else f"{k} ZIPs repeat"
            lines.append(
                f"{head} with a different overlap; "
                f"the first value is used: {_listing(s.overlap_conflicts, SHOWN_INVALID)}"
            )

    if len(s.states) > 1 and s.benchmark_state is not None:
        name = STATE_NAMES.get(s.benchmark_state, s.benchmark_state)
        lines.append(
            f"Your ZIPs are in {_join_states(s.states)}. Benchmark: {name} "
            "(most of their population). You can change it."
        )

    context: list[str] = []
    if s.project_name:
        context.append(f"Project: {s.project_name}")
    if s.industry:
        context.append(f"Industry: {s.industry}")
    if s.restricted is not None:
        context.append(f"Restricted mode: {'on' if s.restricted else 'off'}")
    if context:
        lines.append(" · ".join(context))
    return lines
