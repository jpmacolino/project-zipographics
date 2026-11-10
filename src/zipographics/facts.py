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

#: USPS abbreviation -> state FIPS code (the benchmark table's ``geo_id`` for states).
STATE_FIPS: dict[str, str] = {
    "AL": "01", "AK": "02", "AZ": "04", "AR": "05", "CA": "06", "CO": "08", "CT": "09",
    "DE": "10", "DC": "11", "FL": "12", "GA": "13", "HI": "15", "ID": "16", "IL": "17",
    "IN": "18", "IA": "19", "KS": "20", "KY": "21", "LA": "22", "ME": "23", "MD": "24",
    "MA": "25", "MI": "26", "MN": "27", "MS": "28", "MO": "29", "MT": "30", "NE": "31",
    "NV": "32", "NH": "33", "NJ": "34", "NM": "35", "NY": "36", "NC": "37", "ND": "38",
    "OH": "39", "OK": "40", "OR": "41", "PA": "42", "RI": "44", "SC": "45", "SD": "46",
    "TN": "47", "TX": "48", "UT": "49", "VT": "50", "VA": "51", "WA": "53", "WV": "54",
    "WI": "55", "WY": "56", "PR": "72",
}  # fmt: skip

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
    if facts.index.has_duplicates:
        raise ValueError("facts frame index has duplicate ZIPs")
    return facts


class StateEntry(NamedTuple):
    zip: str
    state: str
    population: float


def state_entries(
    zips: Sequence[str], facts: pd.DataFrame, column: str = "state"
) -> list[StateEntry]:
    """(zip, group, population) for each ZIP that has a value in ``column``, in input order.

    ``column`` is ``state`` by default; ``county_fips`` gives the county grouping for the default
    county benchmark (the group is stored in the ``state`` field). Unknown population counts as 0.
    """
    sub = facts.reindex(list(zips))
    out: list[StateEntry] = []
    for z, state, pop in zip(sub.index, sub[column], sub["population"], strict=True):
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


class StateTotals:
    """Per-state population totals that answer "dominant state, ignoring one ZIP" in O(states).

    Same rule as :func:`dominant_of` (which is the slow reference the tests compare against),
    but built once, so excluding each of n repaired ZIPs costs O(n), not O(n^2).
    """

    def __init__(self, entries: Iterable[StateEntry]) -> None:
        self._where: dict[str, tuple[int, str, float]] = {}
        self._total: dict[str, float] = {}
        self._positions: dict[str, list[int]] = {}
        for pos, e in enumerate(entries):
            self._where[e.zip] = (pos, e.state, e.population)
            self._total[e.state] = self._total.get(e.state, 0.0) + e.population
            self._positions.setdefault(e.state, []).append(pos)

    def dominant(self, exclude: str | None = None) -> str | None:
        hit = self._where.get(exclude) if exclude is not None else None
        best: str | None = None
        best_key: tuple[float, int] | None = None
        for state, positions in self._positions.items():
            total, first = self._total[state], positions[0]
            if hit is not None and hit[1] == state:
                total -= hit[2]
                if len(positions) == 1:
                    continue  # that was the state's only ZIP
                if positions[0] == hit[0]:
                    first = positions[1]
            key = (total, -first)  # largest total; ties to the earliest remaining ZIP
            if best_key is None or key > best_key:
                best, best_key = state, key
        return best


def dominant_state(
    zips: Sequence[str], facts: pd.DataFrame, *, exclude: str | None = None
) -> str | None:
    """Default benchmark state for a set of ZIPs (SPEC §6.8), optionally ignoring one ZIP."""
    return dominant_of(state_entries(zips, facts), exclude)
