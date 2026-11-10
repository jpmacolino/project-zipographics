"""Per-ZIP facts the review screen needs, state names, and the benchmark-state rule.

A *facts frame* is a small pandas DataFrame indexed by 5-character string ZIP with columns
``state`` (USPS abbreviation), ``population`` and ``households`` (float, NaN when unknown).
The data loader (Phase 4) builds it from ``zcta_profile.parquet``; tests build synthetic ones.

The default benchmark rule lives here (SPEC §6.8): the state with the largest summed population
across the recognized ZIPs; ties go to the state whose ZIP comes first in the input.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from typing import NamedTuple

import pandas as pd

FACT_COLUMNS = ("state", "population", "households")

STATE_NAMES: dict[str, str] = {
    "AL": "Alabama",
    "AK": "Alaska",
    "AZ": "Arizona",
    "AR": "Arkansas",
    "CA": "California",
    "CO": "Colorado",
    "CT": "Connecticut",
    "DE": "Delaware",
    "DC": "District of Columbia",
    "FL": "Florida",
    "GA": "Georgia",
    "HI": "Hawaii",
    "ID": "Idaho",
    "IL": "Illinois",
    "IN": "Indiana",
    "IA": "Iowa",
    "KS": "Kansas",
    "KY": "Kentucky",
    "LA": "Louisiana",
    "ME": "Maine",
    "MD": "Maryland",
    "MA": "Massachusetts",
    "MI": "Michigan",
    "MN": "Minnesota",
    "MS": "Mississippi",
    "MO": "Missouri",
    "MT": "Montana",
    "NE": "Nebraska",
    "NV": "Nevada",
    "NH": "New Hampshire",
    "NJ": "New Jersey",
    "NM": "New Mexico",
    "NY": "New York",
    "NC": "North Carolina",
    "ND": "North Dakota",
    "OH": "Ohio",
    "OK": "Oklahoma",
    "OR": "Oregon",
    "PA": "Pennsylvania",
    "PR": "Puerto Rico",
    "RI": "Rhode Island",
    "SC": "South Carolina",
    "SD": "South Dakota",
    "TN": "Tennessee",
    "TX": "Texas",
    "UT": "Utah",
    "VT": "Vermont",
    "VA": "Virginia",
    "WA": "Washington",
    "WV": "West Virginia",
    "WI": "Wisconsin",
    "WY": "Wyoming",
}

_ZIP = re.compile(r"[0-9]{5}")


def validate_facts(facts: pd.DataFrame) -> pd.DataFrame:
    """Check the shape of a facts frame (ZIP strings as the index; the three columns)."""
    missing = [c for c in FACT_COLUMNS if c not in facts.columns]
    if missing:
        raise ValueError(f"facts frame is missing columns: {', '.join(missing)}")
    if not all(isinstance(z, str) for z in facts.index):
        raise ValueError("facts frame index must be string ZIPs (never numbers)")
    if not all(_ZIP.fullmatch(z) for z in facts.index):
        raise ValueError("facts frame index must hold 5-character ZIPs")
    return facts


class StateEntry(NamedTuple):
    zip: str
    state: str
    population: float


def state_entries(zips: Sequence[str], facts: pd.DataFrame) -> list[StateEntry]:
    """(zip, state, population) for each ZIP that has a state in ``facts``, in input order.

    Unknown population counts as 0.
    """
    sub = facts.reindex(list(zips))
    out: list[StateEntry] = []
    for z, state, pop in zip(sub.index, sub["state"], sub["population"], strict=True):
        if isinstance(state, str) and state:
            out.append(StateEntry(z, state, 0.0 if pd.isna(pop) else float(pop)))
    return out


def dominant_of(entries: Iterable[StateEntry], exclude: str | None = None) -> str | None:
    """The state with the largest summed population; ties go to the earliest in input order."""
    totals: dict[str, float] = {}
    for entry in entries:
        if entry.zip == exclude:
            continue
        totals[entry.state] = totals.get(entry.state, 0.0) + entry.population
    if not totals:
        return None
    best = max(totals.values())
    # dict preserves first-seen order, so the first state at the maximum is the earliest one
    return next(state for state, total in totals.items() if total == best)


def dominant_state(
    zips: Sequence[str], facts: pd.DataFrame, *, exclude: str | None = None
) -> str | None:
    """Default benchmark state for a set of ZIPs (SPEC §6.8), optionally ignoring one ZIP."""
    return dominant_of(state_entries(zips, facts), exclude)
